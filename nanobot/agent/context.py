"""Context builder for assembling agent prompts."""

import asyncio
import base64
import mimetypes
import platform
from pathlib import Path
from typing import Any, TYPE_CHECKING

from nanobot.utils.helpers import current_time_str

from nanobot.agent.memory import MemoryStore
from nanobot.utils.prompt_templates import render_template
from nanobot.agent.skills import SkillsLoader
from nanobot.utils.helpers import build_assistant_message, detect_image_mime

if TYPE_CHECKING:
    from nanobot.agent.reme_adapter import RemeMemoryAdapter


class ContextBuilder:
    """Builds the context (system prompt + messages) for the agent."""

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"]
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"

    def __init__(
        self,
        workspace: Path,
        timezone: str | None = None,
        reme_adapter: "RemeMemoryAdapter | None" = None,
    ):
        self.workspace = workspace
        self.timezone = timezone
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)
        self.reme_adapter = reme_adapter

    def build_system_prompt(
        self,
        skill_names: list[str] | None = None,
        current_query: str | None = None,
    ) -> str:
        """Build the system prompt from identity, bootstrap files, memory, and skills.

        Args:
            skill_names: Optional list of skill names to include
            current_query: Optional current user query for semantic memory retrieval
        """
        parts = [self._get_identity()]

        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        # Memory retrieval - prefer ReMe semantic search if available
        memory = self._get_memory_content(current_query)
        if memory:
            parts.append(f"# Memory\n\n{memory}")

        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")

        skills_summary = self.skills.build_skills_summary()
        if skills_summary:
            parts.append(render_template("agent/skills_section.md", skills_summary=skills_summary))

        return "\n\n---\n\n".join(parts)

    def _get_memory_content(self, current_query: str | None = None) -> str:
        """Get memory content, using semantic retrieval if ReMe is available.

        Args:
            current_query: Current user message for semantic memory retrieval

        Important:
            - Skips retrieval for "[token-probe]" which is an internal estimation probe
            - Never triggers retrieval during token estimation to prevent infinite loops
        """
        # CRITICAL: Skip memory retrieval for token estimation probes
        # "[token-probe]" is used by Consolidator.estimate_session_prompt_tokens()
        # to estimate token count. Retrieval here would cause:
        # 1. Unnecessary 40-60s delay during estimation
        # 2. Potential infinite loops when estimation triggers consolidation
        if current_query == "[token-probe]":
            return ""

        if self.reme_adapter:
            try:
                # Use semantic retrieval with current query
                return self.reme_adapter.get_memory_context(current_query)
            except Exception as e:
                from loguru import logger
                logger.warning(f"ReMe retrieval failed, falling back to file memory: {e}")

        # Fallback to file-based memory
        return self.memory.get_memory_context()

    def _get_identity(self) -> str:
        """Get the core identity section."""
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        return render_template(
            "agent/identity.md",
            workspace_path=workspace_path,
            runtime=runtime,
            platform_policy=render_template("agent/platform_policy.md", system=system),
        )

    @staticmethod
    def _build_runtime_context(
        channel: str | None, chat_id: str | None, timezone: str | None = None,
    ) -> str:
        """Build untrusted runtime metadata block for injection before the user message."""
        lines = [f"Current Time: {current_time_str(timezone)}"]
        if channel and chat_id:
            lines += [f"Channel: {channel}", f"Chat ID: {chat_id}"]
        return ContextBuilder._RUNTIME_CONTEXT_TAG + "\n" + "\n".join(lines)

    @staticmethod
    def _merge_message_content(left: Any, right: Any) -> str | list[dict[str, Any]]:
        if isinstance(left, str) and isinstance(right, str):
            return f"{left}\n\n{right}" if left else right

        def _to_blocks(value: Any) -> list[dict[str, Any]]:
            if isinstance(value, list):
                return [item if isinstance(item, dict) else {"type": "text", "text": str(item)} for item in value]
            if value is None:
                return []
            return [{"type": "text", "text": str(value)}]

        return _to_blocks(left) + _to_blocks(right)

    def _load_bootstrap_files(self) -> str:
        """Load all bootstrap files from workspace."""
        parts = []

        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")

        return "\n\n".join(parts) if parts else ""

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        current_role: str = "user",
    ) -> list[dict[str, Any]]:
        """Build the complete message list for an LLM call.

        Args:
            history: Conversation history
            current_message: Current user message (used for semantic memory retrieval)
            skill_names: Optional skill names to include
            media: Optional media files
            channel: Channel name
            chat_id: Chat ID
            current_role: Role of current message sender
        """
        runtime_ctx = self._build_runtime_context(channel, chat_id, self.timezone)
        user_content = self._build_user_content(current_message, media)

        # Merge runtime context and user content into a single user message
        # to avoid consecutive same-role messages that some providers reject.
        if isinstance(user_content, str):
            merged = f"{runtime_ctx}\n\n{user_content}"
        else:
            merged = [{"type": "text", "text": runtime_ctx}] + user_content
        messages = [
            # Pass current_message for semantic memory retrieval
            {"role": "system", "content": self.build_system_prompt(skill_names, current_query=current_message)},
            *history,
        ]
        if messages[-1].get("role") == current_role:
            last = dict(messages[-1])
            last["content"] = self._merge_message_content(last.get("content"), merged)
            messages[-1] = last
            return messages
        messages.append({"role": current_role, "content": merged})
        return messages

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images."""
        if not media:
            return text

        images = []
        for path in media:
            p = Path(path)
            if not p.is_file():
                continue
            raw = p.read_bytes()
            # Detect real MIME type from magic bytes; fallback to filename guess
            mime = detect_image_mime(raw) or mimetypes.guess_type(path)[0]
            if not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(raw).decode()
            images.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
                "_meta": {"path": str(p)},
            })

        if not images:
            return text
        return images + [{"type": "text", "text": text}]

    def add_tool_result(
        self, messages: list[dict[str, Any]],
        tool_call_id: str, tool_name: str, result: Any,
    ) -> list[dict[str, Any]]:
        """Add a tool result to the message list."""
        messages.append({"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": result})
        return messages

    def add_assistant_message(
        self, messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
        thinking_blocks: list[dict] | None = None,
    ) -> list[dict[str, Any]]:
        """Add an assistant message to the message list."""
        messages.append(build_assistant_message(
            content,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
            thinking_blocks=thinking_blocks,
        ))
        return messages
