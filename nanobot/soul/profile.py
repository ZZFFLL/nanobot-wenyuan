"""Structured soul profile state management."""

from __future__ import annotations

import json
from pathlib import Path

from nanobot.soul.methodology import build_default_profile


class SoulProfileManager:
    """Persist and load the structured soul profile markdown document."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.profile_file = workspace / "SOUL_PROFILE.md"

    def read(self) -> dict:
        try:
            raw = self.profile_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return build_default_profile()

        text = self._strip_code_fence(raw)
        if not text:
            return build_default_profile()
        return json.loads(text)

    def write(self, profile: dict) -> None:
        text = "```json\n" + json.dumps(profile, ensure_ascii=False, indent=2) + "\n```"
        self.profile_file.write_text(text, encoding="utf-8")

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        stripped = text.strip()
        if not stripped.startswith("```"):
            return stripped

        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
