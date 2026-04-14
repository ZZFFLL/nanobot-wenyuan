"""Structured soul profile state management."""

from __future__ import annotations

import json
from pathlib import Path

from nanobot.soul.methodology import (
    RELATIONSHIP_DIMENSIONS,
    RELATIONSHIP_STAGES,
    build_default_profile,
)


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

    def update_relationship(
        self,
        *,
        stage: str,
        dimension_deltas: dict[str, float],
    ) -> dict:
        if stage not in RELATIONSHIP_STAGES:
            raise ValueError("未知关系阶段")

        profile = self.read()
        current_relationship = build_default_profile()["relationship"]
        current_relationship.update(profile.get("relationship", {}))
        current_relationship["stage"] = stage

        for name, delta in dimension_deltas.items():
            if name not in RELATIONSHIP_DIMENSIONS:
                continue
            current_value = float(current_relationship.get(name, 0.0))
            next_value = max(0.0, min(1.0, current_value + float(delta)))
            current_relationship[name] = next_value

        profile["relationship"] = current_relationship
        self.write(profile)
        return current_relationship

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
