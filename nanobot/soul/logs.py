"""Unified log writing for soul review, calibration, and evolution traces."""

from __future__ import annotations

from pathlib import Path


class SoulLogWriter:
    """Write structured markdown logs under the workspace soul_logs directory."""

    def __init__(self, workspace: Path) -> None:
        self.base_dir = workspace / "soul_logs"

    def write_weekly(self, stamp: str, content: str) -> Path:
        return self._write("weekly", f"{stamp}-周复盘.md", content)

    def write_monthly(self, stamp: str, content: str) -> Path:
        return self._write("monthly", f"{stamp}-月校准报告.md", content)

    def write_proactive(self, stamp: str, decision) -> Path:
        content = decision.to_markdown() if hasattr(decision, "to_markdown") else str(decision)
        return self._write("proactive", f"{stamp}-主动陪伴.md", content)

    def write_proactive_event(self, stamp: str, *, event_type: str, detail: str) -> Path:
        content = (
            "# 主动陪伴事件\n\n"
            f"- 事件类型: {event_type}\n"
            f"- 详细信息: {detail}\n"
        )
        return self._write("proactive", f"{stamp}-主动事件.md", content)

    def _write(self, kind: str, filename: str, content: str) -> Path:
        target = self.base_dir / kind
        target.mkdir(parents=True, exist_ok=True)
        path = target / filename
        path.write_text(content, encoding="utf-8")
        return path
