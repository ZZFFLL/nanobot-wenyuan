"""Unified log writing for soul review, calibration, and evolution traces."""

from __future__ import annotations

from pathlib import Path

from nanobot.soul.proactive import ProactiveDecision


class SoulLogWriter:
    """Write structured markdown logs under the workspace soul_logs directory."""

    def __init__(self, workspace: Path) -> None:
        self.base_dir = workspace / "soul_logs"

    def write_weekly(self, stamp: str, content: str) -> Path:
        target = self.base_dir / "weekly"
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{stamp}-周复盘.md"
        path.write_text(content, encoding="utf-8")
        return path

    def write_proactive(self, stamp: str, decision: ProactiveDecision) -> Path:
        target = self.base_dir / "proactive"
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{stamp}-主动陪伴.md"
        path.write_text(decision.to_markdown(), encoding="utf-8")
        return path
