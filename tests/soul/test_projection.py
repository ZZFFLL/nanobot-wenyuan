"""Tests for LLM-backed SOUL projection from structured profile."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.soul.profile import SoulProfileManager


def _profile(stage: str = "亲近") -> dict:
    return {
        "personality": {
            "Fi": 0.8,
            "Fe": 0.3,
            "Ti": 0.2,
            "Te": 0.1,
            "Si": 0.5,
            "Se": 0.1,
            "Ni": 0.2,
            "Ne": 0.5,
        },
        "relationship": {
            "stage": stage,
            "trust": 0.6,
            "intimacy": 0.4,
            "attachment": 0.2,
            "security": 0.5,
            "boundary": 0.8,
            "affection": 0.2,
        },
        "companionship": {
            "empathy_fit": 0.2,
            "memory_fit": 0.0,
            "naturalness": 0.2,
            "initiative_quality": 0.0,
            "scene_awareness": 0.1,
            "boundary_expression": 0.9,
        },
    }


def test_project_initial_soul_markdown_ignores_non_profile_text():
    from nanobot.soul.projection import project_initial_soul_markdown

    profile = _profile(stage="亲近")

    content = project_initial_soul_markdown(profile)

    assert "候选文本" not in content
    assert "候选关系" not in content
    assert "payload 性格" not in content
    assert "payload 关系" not in content
    assert "更在意内心真实与情感一致性" in content
    assert "更稳定的信任" in content


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("personality_seed", {"bad": "value"}),
        ("personality_seed", ["bad"]),
        ("personality_seed", False),
        ("relationship_seed", {"bad": "value"}),
        ("relationship_seed", ["bad"]),
        ("relationship_seed", True),
    ],
)
def test_project_initial_soul_markdown_rejects_invalid_expression_seed_types(field, value):
    from nanobot.soul.projection import project_initial_soul_markdown

    profile = _profile(stage="熟悉")
    profile["expression"] = {field: value}

    with pytest.raises(ValueError, match=rf"expression\.{field} 必须是字符串"):
        project_initial_soul_markdown(profile)


@pytest.mark.asyncio
async def test_project_soul_from_profile_uses_llm_and_writes_markdown(tmp_path):
    from nanobot.soul.projection import project_soul_from_profile

    (tmp_path / "SOUL.md").write_text(
        "# 性格\n\n温柔，慢热，但有自己的边界。\n\n# 初始关系\n\n还在慢慢观察用户。\n",
        encoding="utf-8",
    )
    (tmp_path / "CORE_ANCHOR.md").write_text("# 核心锚点\n\n- 不无底线顺从\n", encoding="utf-8")
    (tmp_path / "SOUL_METHOD.md").write_text("# SOUL 方法论\n\n- 主轴: 荣格八维\n", encoding="utf-8")
    SoulProfileManager(tmp_path).write(_profile())

    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(
        return_value=SimpleNamespace(
            content=(
                "# 性格\n\n"
                "她依旧温柔、慢热，也会先确认自己的感受，再决定要不要更靠近。\n\n"
                "# 初始关系\n\n"
                "她对用户已经有了更稳定的信任，会谨慎而自然地靠近，但不会因此放下自己的边界。\n"
            )
        )
    )

    content = await project_soul_from_profile(
        tmp_path,
        provider=provider,
        model="test-model",
    )

    assert "更稳定的信任" in content
    assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == content

    prompt = provider.chat_with_retry.await_args.kwargs["messages"][1]["content"]
    assert "## 当前结构化 SOUL_PROFILE" in prompt
    assert '"stage": "亲近"' in prompt
    assert "## 当前 SOUL.md" in prompt
    assert "## SOUL 方法论" in prompt

    trace_files = list((tmp_path / "soul_logs" / "projection").glob("*-投影追踪.jsonl"))
    audit_files = list((tmp_path / "soul_logs" / "projection").glob("*-投影审计.json"))
    assert len(trace_files) == 1
    assert len(audit_files) == 1
    assert '"stage": "write"' in trace_files[0].read_text(encoding="utf-8")
    audit_text = audit_files[0].read_text(encoding="utf-8")
    assert '"final_status": "accepted"' in audit_text
    assert '"result"' in audit_text


@pytest.mark.asyncio
async def test_project_soul_from_profile_rejects_structured_output_and_keeps_existing(tmp_path):
    from nanobot.soul.projection import SoulProjectionError, project_soul_from_profile

    original = "# 性格\n\n原始画像。\n\n# 初始关系\n\n原始关系。\n"
    (tmp_path / "SOUL.md").write_text(original, encoding="utf-8")
    (tmp_path / "SOUL_METHOD.md").write_text("# SOUL 方法论\n\n- 主轴: 荣格八维\n", encoding="utf-8")
    SoulProfileManager(tmp_path).write(_profile())

    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(
        return_value=SimpleNamespace(
            content=(
                "# 性格\n\n"
                "{\"trust\": 0.6, \"Fi\": 0.8}\n\n"
                "# 初始关系\n\n"
                "relationship.stage=亲近"
            )
        )
    )

    with pytest.raises(SoulProjectionError):
        await project_soul_from_profile(
            tmp_path,
            provider=provider,
            model="test-model",
            max_attempts=1,
        )

    assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == original
    trace_files = list((tmp_path / "soul_logs" / "projection").glob("*-投影追踪.jsonl"))
    audit_files = list((tmp_path / "soul_logs" / "projection").glob("*-投影审计.json"))
    assert len(trace_files) == 1
    assert len(audit_files) == 1
    assert "SOUL.md 投影候选非法" in trace_files[0].read_text(encoding="utf-8")
    assert '"final_status": "failed"' in audit_files[0].read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_project_soul_from_profile_accepts_partial_profile_by_filling_defaults(tmp_path):
    from nanobot.soul.projection import project_soul_from_profile

    SoulProfileManager(tmp_path).write({
        "personality": {"Fi": 0.8},
        "relationship": {
            "stage": "熟悉",
            "trust": 0.2,
            "intimacy": 0.1,
            "attachment": 0.0,
            "security": 0.1,
            "boundary": 0.9,
            "affection": 0.0,
        },
        "companionship": {"empathy_fit": 0.2},
    })
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(
        return_value=SimpleNamespace(
            content=(
                "# 性格\n\n"
                "她会先确认自己的感受，再决定靠近的程度。\n\n"
                "# 初始关系\n\n"
                "她对用户已有初步熟悉感，也会继续保留自己的分寸。\n"
            )
        )
    )

    content = await project_soul_from_profile(
        tmp_path,
        provider=provider,
        model="test-model",
    )

    assert "初步熟悉感" in content


@pytest.mark.asyncio
async def test_project_soul_from_profile_still_rejects_invalid_present_values(tmp_path):
    from nanobot.soul.projection import SoulProjectionError, project_soul_from_profile

    SoulProfileManager(tmp_path).write({
        "personality": {"Fi": 0.8},
        "relationship": {
            "stage": "熟悉",
            "trust": "bad",
            "intimacy": 0.1,
            "attachment": 0.0,
            "security": 0.1,
            "boundary": 0.9,
            "affection": 0.0,
        },
        "companionship": {"empathy_fit": 0.2},
    })
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock()

    with pytest.raises(SoulProjectionError, match=r"relationship\.trust 必须是 0\.0-1\.0 数值"):
        await project_soul_from_profile(
            tmp_path,
            provider=provider,
            model="test-model",
        )


@pytest.mark.asyncio
async def test_project_soul_from_profile_rejects_invalid_expression_seed_types(tmp_path):
    from nanobot.soul.projection import SoulProjectionError, project_soul_from_profile

    profile = _profile(stage="熟悉")
    profile["expression"] = {"personality_seed": {"bad": "value"}}
    SoulProfileManager(tmp_path).write(profile)
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(
        return_value=SimpleNamespace(
            content="# 性格\n\n不该被用到。\n\n# 初始关系\n\n不该被用到。\n"
        )
    )

    with pytest.raises(
        SoulProjectionError,
        match=r"SOUL_PROFILE\.md 内容非法，无法重建 SOUL\.md: expression\.personality_seed 必须是字符串",
    ):
        await project_soul_from_profile(
            tmp_path,
            provider=provider,
            model="test-model",
        )
    provider.chat_with_retry.assert_not_awaited()
