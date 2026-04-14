"""Core anchor state management."""

from __future__ import annotations

from pathlib import Path


class AnchorManager:
    """Read the stable core anchor document from the workspace."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.anchor_file = workspace / "CORE_ANCHOR.md"

    def read_text(self) -> str:
        try:
            return self.anchor_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""
