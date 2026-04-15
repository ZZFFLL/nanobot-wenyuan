"""Soul-specific guards for writable agent tools."""

from __future__ import annotations

from pathlib import Path

from nanobot.agent.tools.filesystem import EditFileTool, WriteFileTool

PROTECTED_SOUL_FILES = frozenset({"CORE_ANCHOR.md"})


def is_protected_soul_file(path: Path) -> bool:
    """Return True when the target path is a protected soul file."""

    return path.name in PROTECTED_SOUL_FILES


def protected_soul_file_error(path: Path) -> str:
    """Build a stable error message for protected soul files."""

    return (
        f"Error: {path.name} 属于受保护的核心锚点文件，"
        "不能通过 Agent 工具直接修改。"
    )


class SoulProtectedWriteFileTool(WriteFileTool):
    """Write tool variant that blocks protected soul files."""

    async def execute(self, path: str | None = None, content: str | None = None, **kwargs) -> str:
        try:
            if path:
                resolved = self._resolve(path)
                if is_protected_soul_file(resolved):
                    return protected_soul_file_error(resolved)
        except PermissionError as e:
            return f"Error: {e}"
        return await super().execute(path=path, content=content, **kwargs)


class SoulProtectedEditFileTool(EditFileTool):
    """Edit tool variant that blocks protected soul files."""

    async def execute(
        self,
        path: str | None = None,
        old_text: str | None = None,
        new_text: str | None = None,
        replace_all: bool = False,
        **kwargs,
    ) -> str:
        try:
            if path:
                resolved = self._resolve(path)
                if is_protected_soul_file(resolved):
                    return protected_soul_file_error(resolved)
        except PermissionError as e:
            return f"Error: {e}"
        return await super().execute(
            path=path,
            old_text=old_text,
            new_text=new_text,
            replace_all=replace_all,
            **kwargs,
        )
