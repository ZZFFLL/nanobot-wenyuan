"""Tests for monthly soul calibration generation."""

from nanobot.soul.logs import SoulLogWriter
from nanobot.soul.calibration import (
    MonthlyCalibrationBuilder,
    build_monthly_calibration_job,
)


def test_monthly_calibration_builder_returns_markdown():
    builder = MonthlyCalibrationBuilder()

    content = builder.render({"summary": "本月总体稳定"})

    assert "# 月校准报告" in content
    assert "本月总体稳定" in content


def test_build_monthly_calibration_job_uses_expected_schedule():
    job = build_monthly_calibration_job("Asia/Shanghai")

    assert job.name == "monthly_calibration"
    assert job.schedule.kind == "cron"
    assert job.schedule.expr == "0 4 1 * *"
    assert job.schedule.tz == "Asia/Shanghai"


def test_monthly_calibration_builder_includes_recent_weekly_summary(tmp_path):
    (tmp_path / "CORE_ANCHOR.md").write_text("# 核心锚点\n\n- 不无底线顺从\n", encoding="utf-8")
    SoulLogWriter(tmp_path).write_weekly(
        "2026-04-14",
        "# 周复盘\n\n## 本周摘要\n关系升温\n",
    )

    builder = MonthlyCalibrationBuilder()
    content = builder.build(tmp_path)

    assert "已读取核心锚点" in content
    assert "关系升温" in content
