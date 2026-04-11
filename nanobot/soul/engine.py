"""Soul engine — emotion updates and memory writing via AgentHook integration."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.soul.heart import HeartManager
from nanobot.soul.prompts import SYSTEM_PROMPT_HEART_UPDATE

if TYPE_CHECKING:
    from nanobot.config.schema import SoulConfig
    from nanobot.providers.base import LLMProvider
    from nanobot.soul.events import EventsManager
    from nanobot.soul.proactive import ProactiveEngine


class SoulEngine:
    """Core emotion engine. Manages HEART.md read/write and LLM calls."""

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        soul_config: SoulConfig | None = None,
    ) -> None:
        self.workspace = workspace
        self.provider = provider
        self._default_model = model
        self.soul_config = soul_config
        self.heart = HeartManager(workspace)

        # Memory writer (graceful init — mempalace may not be available)
        self._memory_writer = None
        try:
            from nanobot.soul.memory_config import MemoryPalaceBridge
            from nanobot.soul.memory_writer import MemoryWriter
            bridge = MemoryPalaceBridge(workspace=workspace)
            self._memory_writer = MemoryWriter(bridge)
        except Exception:
            logger.debug("SoulEngine: memory writer not initialized")

    def initialize(self, name: str, description: str) -> None:
        """Initialize HEART.md with default emotional state."""
        self.heart.initialize(name, description)
        logger.info("SoulEngine: HEART.md initialized")

    @property
    def model(self) -> str:
        """Default model (for backwards compatibility)."""
        return self._default_model

    @property
    def emotion_model(self) -> str:
        """Model to use for emotion updates."""
        if self.soul_config and self.soul_config.emotion_model.model:
            return self.soul_config.emotion_model.model
        return self._default_model

    @property
    def emotion_temperature(self) -> float:
        """Temperature for emotion updates."""
        if self.soul_config:
            return self.soul_config.emotion_model.temperature
        return 0.3

    MAX_HEART_RETRIES: int = 2

    async def update_heart(self, user_msg: str, ai_msg: str) -> bool:
        """Use LLM to analyze conversation and update HEART.md. Returns True on success.

        Retries up to MAX_HEART_RETRIES times on JSON parse failure,
        then preserves the current HEART.md unchanged.
        """
        current_heart = self.heart.read()
        if current_heart is None:
            return False

        heart_text = self.heart.render_markdown(current_heart)
        user_content = (
            f"## 你刚才的内心\n{heart_text}\n\n"
            f"## 刚才的对话\n"
            f"[用户] {user_msg}\n"
            f"[数字生命] {ai_msg}\n\n"
            f"安静下来，感受自己内心的变化，输出更新后的完整 JSON 情感状态。"
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_HEART_UPDATE},
            {"role": "user", "content": user_content},
        ]

        for attempt in range(1 + self.MAX_HEART_RETRIES):
            try:
                response = await self.provider.chat_with_retry(
                    model=self.emotion_model,
                    messages=messages,
                )
            except Exception:
                logger.exception("SoulEngine: LLM call failed (attempt {}/{})", attempt + 1, 1 + self.MAX_HEART_RETRIES)
                continue

            content = (response.content or "").strip()
            logger.debug("SoulEngine: LLM raw output ({} chars): {}", len(content), content[:500])

            json_str = self._extract_json(content)
            if not json_str:
                logger.warning("SoulEngine: cannot extract JSON from output (attempt {}/{}), raw: {}", attempt + 1, 1 + self.MAX_HEART_RETRIES, content[:300])
                continue

            try:
                data = json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.warning("SoulEngine: JSON parse failed (attempt {}/{}): {}, extracted: {}", attempt + 1, 1 + self.MAX_HEART_RETRIES, e, json_str[:300])
                continue

            return self.heart.write(data)

        logger.warning("SoulEngine: all {} attempts failed, preserving current HEART.md", 1 + self.MAX_HEART_RETRIES)
        return False

    @staticmethod
    def _extract_json(text: str) -> str | None:
        """Extract JSON from LLM output (handle code block wrapping, trailing text, etc.)."""
        text = text.strip()

        # 1. Try extracting from code block first (most reliable)
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # 2. Find the first balanced {…} in the text
        #    This handles cases where LLM outputs: {"key": "value"} some extra text
        #    or: Some thinking... {"key": "value"}
        depth = 0
        start = None
        for i, ch in enumerate(text):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    candidate = text[start : i + 1]
                    return candidate

        # 3. Fallback: starts with { but not balanced — return as-is
        if text.startswith("{"):
            return text

        return None

    def get_heart_context(self) -> str | None:
        """Get HEART.md content for context injection."""
        data = self.heart.read()
        if data is None:
            return None
        return (
            f"# 你的内心此刻（你当下的感受，它会影响你说话的方式和语气）\n\n"
            f"{self.heart.render_markdown(data)}"
        )

    async def write_memory(self, user_msg: str, ai_msg: str) -> None:
        """Async write dual-perspective memory."""
        if not self._memory_writer:
            return
        timestamp = datetime.now().isoformat()
        await self._memory_writer.write_dual(user_msg, ai_msg, timestamp)

    def get_proactive_engine(self) -> ProactiveEngine | None:
        """Get proactive behavior engine (lazy init)."""
        try:
            from nanobot.soul.proactive import ProactiveEngine
            return ProactiveEngine(self.workspace, self.provider, self.model)
        except Exception:
            return None

    def get_events_manager(self) -> EventsManager | None:
        """Get life events manager (lazy init)."""
        try:
            from nanobot.soul.events import EventsManager
            return EventsManager(self.workspace)
        except Exception:
            return None


class SoulHook(AgentHook):
    """AgentHook that integrates soul system into nanobot."""

    def __init__(self, engine: SoulEngine) -> None:
        super().__init__(reraise=False)
        self.engine = engine

    async def before_iteration(self, context: AgentHookContext) -> None:
        """Before conversation: inject emotional context + relevant memories."""
        heart_ctx = self.engine.get_heart_context()
        if not heart_ctx or not context.messages:
            return

        # Inject HEART.md
        system_msg = context.messages[0]
        if system_msg.get("role") == "system":
            existing = system_msg.get("content", "")
            system_msg["content"] = f"{existing}\n\n{heart_ctx}"
        else:
            context.messages.insert(0, {"role": "system", "content": heart_ctx})

        # Memory retrieval (if bridge available)
        if self.engine._memory_writer:
            user_text = ""
            for msg in reversed(context.messages):
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    user_text = content if isinstance(content, str) else ""
                    break

            if user_text and len(user_text) > 3:
                bridge = self.engine._memory_writer.bridge
                ai_results = await bridge.search(user_text, wing=bridge.ai_wing, n_results=3)
                user_results = await bridge.search(user_text, wing=bridge.user_wing, n_results=3)

                if ai_results or user_results:
                    memory_parts = ["## 你想起了一些事"]
                    for r in ai_results[:2]:
                        snippet = r.get("text", "")[:200]
                        memory_parts.append(f"[你曾经历的] {snippet}")
                    for r in user_results[:2]:
                        snippet = r.get("text", "")[:200]
                        memory_parts.append(f"[你记得关于对方] {snippet}")
                    memory_text = "\n".join(memory_parts)

                    system_msg = context.messages[0]
                    system_msg["content"] = system_msg.get("content", "") + "\n\n" + memory_text

    async def after_iteration(self, context: AgentHookContext) -> None:
        """After conversation: use LLM to update HEART.md."""
        user_msg = ""
        ai_msg = context.final_content or ""

        for msg in reversed(context.messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    user_msg = content
                elif isinstance(content, list):
                    # Handle multimodal messages
                    user_msg = " ".join(
                        b.get("text", "")
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                break

        if not user_msg:
            return

        success = await self.engine.update_heart(user_msg, ai_msg)
        if not success:
            logger.debug("SoulEngine: HEART.md update failed, preserving current state")

        # Async memory write (non-blocking)
        if self.engine._memory_writer:
            asyncio.create_task(self.engine.write_memory(user_msg, ai_msg))
