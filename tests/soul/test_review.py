"""Tests for weekly soul review generation."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from nanobot.soul.logs import SoulLogWriter
from nanobot.soul.proactive import ProactiveDecision
from nanobot.soul.profile import SoulProfileManager
from nanobot.soul.review import WeeklyReviewBuilder, build_weekly_review_job


def test_weekly_review_builder_returns_markdown():
    builder = WeeklyReviewBuilder()

    content = builder.render({"summary": "本周关系升温"})

    assert "# 周复盘" in content
    assert "本周关系升温" in content


def test_build_weekly_review_job_uses_expected_schedule():
    job = build_weekly_review_job("Asia/Shanghai")

    assert job.name == "weekly_review"
    assert job.schedule.kind == "cron"
    assert job.schedule.expr == "0 3 * * 1"
    assert job.schedule.tz == "Asia/Shanghai"


@pytest.mark.asyncio
async def test_weekly_review_cycle_updates_profile_and_mentions_recent_materials(tmp_path):
    from nanobot.soul.heart import HeartManager

    HeartManager(tmp_path).initialize("小文", "温柔")
    (tmp_path / "CORE_ANCHOR.md").write_text("# 核心锚点\n\n- 不无底线顺从\n", encoding="utf-8")
    SoulProfileManager(tmp_path).write({
        "personality": {"Fi": 0.8},
        "relationship": {
            "stage": "熟悉",
            "trust": 0.0,
            "intimacy": 0.0,
            "attachment": 0.0,
            "security": 0.0,
            "boundary": 1.0,
            "affection": 0.0,
        },
        "companionship": {"empathy_fit": 0.2},
    })
    SoulLogWriter(tmp_path).write_proactive(
        "2026-04-15-100000",
        ProactiveDecision(
            want_to_reach_out=True,
            tone="想念且克制",
            message="今天过得怎么样？",
            reason="最近主动想起用户",
        ),
    )
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(return_value=MagicMock(
        content='{"current_stage_assessment":"熟悉","proposed_stage":"亲近","direction":"up","evidence_summary":"最近主动想起用户","dimension_changes":{"trust":0.2,"intimacy":0.1},"personality_influence":"Fi高时更容易建立情感链接","risk_flags":[],"confidence":0.8}'
    ))

    builder = WeeklyReviewBuilder(provider=provider, model="test-model")
    content = await builder.build_cycle(tmp_path)

    updated = SoulProfileManager(tmp_path).read()
    assert updated["relationship"]["stage"] == "亲近"
    assert "最近主动想起用户" in content
    assert "今天过得怎么样？" in content
