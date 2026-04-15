"""Monthly soul calibration generation and scheduling."""

from __future__ import annotations

from pathlib import Path

from nanobot.cron.types import CronJob, CronPayload, CronSchedule
from nanobot.soul.anchor import AnchorManager
from nanobot.soul.profile import SoulProfileManager


class MonthlyCalibrationBuilder:
    """Build a monthly calibration report from current soul state."""

    def render(self, payload: dict) -> str:
        summary = payload.get("summary", "")
        anchor_state = payload.get("anchor_state", "")
        stage = payload.get("relationship_stage", "")
        return (
            "# 月校准报告\n\n"
            f"## 本月总体结论\n{summary}\n\n"
            f"## 锚点一致性\n{anchor_state or '（暂无）'}\n\n"
            f"## 当前关系阶段\n{stage or '（未知）'}\n"
        )

    def build(self, workspace: Path) -> str:
        anchor_text = AnchorManager(workspace).read_text()
        profile = SoulProfileManager(workspace).read()
        stage = profile.get("relationship", {}).get("stage", "熟悉")
        summary = "本月自动校准已生成，后续将接入更完整的偏移与风险审视逻辑。"
        anchor_state = "已读取核心锚点" if anchor_text else "未发现核心锚点文件"
        weekly_excerpt = self._recent_weekly_excerpt(workspace)
        return self.render({
            "summary": summary + (f"\n\n近期周复盘摘要：\n{weekly_excerpt}" if weekly_excerpt else ""),
            "anchor_state": anchor_state,
            "relationship_stage": stage,
        })

    @staticmethod
    def _recent_weekly_excerpt(workspace: Path, limit: int = 3) -> str:
        log_dir = workspace / "soul_logs" / "weekly"
        if not log_dir.exists():
            return ""
        files = sorted(log_dir.glob("*.md"), reverse=True)[:limit]
        parts = []
        for path in files:
            text = path.read_text(encoding="utf-8").strip()
            if text:
                parts.append(text[:300])
        return "\n\n".join(parts)


def build_monthly_calibration_job(timezone: str) -> CronJob:
    """Build the monthly calibration system job definition."""

    return CronJob(
        id="monthly_calibration",
        name="monthly_calibration",
        schedule=CronSchedule(kind="cron", expr="0 4 1 * *", tz=timezone),
        payload=CronPayload(kind="system_event"),
    )
