"""Tests for soul init adjudication."""

import json

from nanobot.soul.init_adjudicator import SoulInitAdjudicator
from nanobot.soul.init_inference import SoulInitCandidate


def _default_profile():
    return {
        "personality": {"Fi": 0.8, "Fe": 0.3, "Ti": 0.2, "Te": 0.1, "Si": 0.5, "Se": 0.1, "Ni": 0.2, "Ne": 0.5},
        "relationship": {"stage": "还不认识", "trust": 0.0, "intimacy": 0.0, "attachment": 0.0, "security": 0.0, "boundary": 1.0, "affection": 0.0},
        "companionship": {"empathy_fit": 0.0, "memory_fit": 0.0, "naturalness": 0.0, "initiative_quality": 0.0, "scene_awareness": 0.0, "boundary_expression": 1.0},
    }


def _default_heart() -> str:
    return (
        "## 当前情绪\n默认\n\n"
        "## 情绪强度\n低到中\n\n"
        "## 关系状态\n默认\n\n"
        "## 性格表现\n默认\n\n"
        "## 情感脉络\n（暂无）\n\n"
        "## 情绪趋势\n尚在形成\n\n"
        "## 当前渴望\n默认\n"
    )


def test_adjudicator_accepts_valid_candidate():
    candidate = SoulInitCandidate(
        soul_markdown="# 性格\n\n温柔但克制\n\n# 初始关系\n\n刚刚认识",
        heart_markdown=(
            "## 当前情绪\n刚刚诞生，有些安静。\n\n"
            "## 情绪强度\n低到中\n\n"
            "## 关系状态\n还在慢慢感知用户。\n\n"
            "## 性格表现\n温柔但克制\n\n"
            "## 情感脉络\n（暂无）\n\n"
            "## 情绪趋势\n尚在形成\n\n"
            "## 当前渴望\n想先理解眼前的人。\n"
        ),
        profile={
            "personality": {"Fi": 0.8, "Fe": 0.3, "Ti": 0.2, "Te": 0.1, "Si": 0.5, "Se": 0.1, "Ni": 0.2, "Ne": 0.5},
            "relationship": {"stage": "还不认识", "trust": 0.0, "intimacy": 0.0, "attachment": 0.0, "security": 0.0, "boundary": 0.95, "affection": 0.0},
            "companionship": {"empathy_fit": 0.2, "memory_fit": 0.0, "naturalness": 0.2, "initiative_quality": 0.0, "scene_awareness": 0.1, "boundary_expression": 0.9},
        },
    )
    adjudicator = SoulInitAdjudicator()

    result = adjudicator.adjudicate(
        candidate=candidate,
        default_soul_markdown="# 性格\n\n默认\n\n# 初始关系\n\n默认",
        default_heart_markdown=_default_heart(),
        default_profile=_default_profile(),
    )

    assert result.used_fallback is False
    assert "温柔但克制" in result.soul_markdown
    assert "当前情绪" in result.heart_markdown
    assert result.profile["relationship"]["stage"] == "还不认识"


def test_adjudicator_falls_back_on_invalid_stage():
    candidate = SoulInitCandidate(
        soul_markdown="# 性格\n\n热烈\n\n# 初始关系\n\n已经深爱",
        heart_markdown=(
            "## 当前情绪\n过热。\n\n"
            "## 情绪强度\n高\n\n"
            "## 关系状态\n已经深爱。\n\n"
            "## 性格表现\n热烈\n\n"
            "## 情感脉络\n（暂无）\n\n"
            "## 情绪趋势\n上升\n\n"
            "## 当前渴望\n立刻靠近。\n"
        ),
        profile={
            "personality": {"Fi": 0.8, "Fe": 0.3, "Ti": 0.2, "Te": 0.1, "Si": 0.5, "Se": 0.1, "Ni": 0.2, "Ne": 0.5},
            "relationship": {"stage": "喜欢", "trust": 0.9, "intimacy": 0.9, "attachment": 0.9, "security": 0.9, "boundary": 0.1, "affection": 0.9},
            "companionship": {"empathy_fit": 0.2, "memory_fit": 0.0, "naturalness": 0.2, "initiative_quality": 0.0, "scene_awareness": 0.1, "boundary_expression": 0.1},
        },
    )
    adjudicator = SoulInitAdjudicator()

    result = adjudicator.adjudicate(
        candidate=candidate,
        default_soul_markdown="# 性格\n\n默认\n\n# 初始关系\n\n默认",
        default_heart_markdown=_default_heart(),
        default_profile=_default_profile(),
    )

    assert result.used_fallback is True
    assert result.profile["relationship"]["stage"] == "还不认识"
    assert result.soul_markdown.startswith("# 性格")


def test_adjudicator_reads_workspace_governance_rules(tmp_path):
    (tmp_path / "SOUL_GOVERNANCE.json").write_text(
        json.dumps(
            {
                "init": {
                    "allowed_stages": ["熟悉"],
                    "relationship_boundary_min": 0.95,
                    "boundary_expression_min": 0.96,
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    candidate = SoulInitCandidate(
        soul_markdown="# 性格\n\n温柔但克制\n\n# 初始关系\n\n刚刚认识",
        heart_markdown=(
            "## 当前情绪\n安静。\n\n"
            "## 情绪强度\n低到中\n\n"
            "## 关系状态\n还在慢慢感知用户。\n\n"
            "## 性格表现\n温柔但克制\n\n"
            "## 情感脉络\n（暂无）\n\n"
            "## 情绪趋势\n尚在形成\n\n"
            "## 当前渴望\n想先理解眼前的人。\n"
        ),
        profile={
            "personality": {"Fi": 0.8, "Fe": 0.3, "Ti": 0.2, "Te": 0.1, "Si": 0.5, "Se": 0.1, "Ni": 0.2, "Ne": 0.5},
            "relationship": {"stage": "熟悉", "trust": 0.0, "intimacy": 0.0, "attachment": 0.0, "security": 0.0, "boundary": 0.94, "affection": 0.0},
            "companionship": {"empathy_fit": 0.2, "memory_fit": 0.0, "naturalness": 0.2, "initiative_quality": 0.0, "scene_awareness": 0.1, "boundary_expression": 0.95},
        },
    )
    adjudicator = SoulInitAdjudicator(workspace=tmp_path)

    result = adjudicator.adjudicate(
        candidate=candidate,
        default_soul_markdown="# 性格\n\n默认\n\n# 初始关系\n\n默认",
        default_heart_markdown=_default_heart(),
        default_profile=_default_profile(),
    )

    assert result.used_fallback is True
    assert "relationship.boundary 必须偏高" in result.reason


def test_adjudicator_falls_back_on_invalid_heart():
    candidate = SoulInitCandidate(
        soul_markdown="# 性格\n\n温柔但克制\n\n# 初始关系\n\n刚刚认识",
        heart_markdown="只有一句话，没有 HEART 结构。",
        profile={
            "personality": {"Fi": 0.8, "Fe": 0.3, "Ti": 0.2, "Te": 0.1, "Si": 0.5, "Se": 0.1, "Ni": 0.2, "Ne": 0.5},
            "relationship": {"stage": "还不认识", "trust": 0.0, "intimacy": 0.0, "attachment": 0.0, "security": 0.0, "boundary": 0.95, "affection": 0.0},
            "companionship": {"empathy_fit": 0.2, "memory_fit": 0.0, "naturalness": 0.2, "initiative_quality": 0.0, "scene_awareness": 0.1, "boundary_expression": 0.9},
        },
    )
    adjudicator = SoulInitAdjudicator()

    result = adjudicator.adjudicate(
        candidate=candidate,
        default_soul_markdown="# 性格\n\n默认\n\n# 初始关系\n\n默认",
        default_heart_markdown=_default_heart(),
        default_profile=_default_profile(),
    )

    assert result.used_fallback is True
    assert "HEART.md 候选非法" in result.reason


def test_adjudicator_falls_back_on_invalid_expression_seed_type():
    candidate = SoulInitCandidate(
        soul_markdown="# 性格\n\n温柔但克制\n\n# 初始关系\n\n刚刚认识",
        heart_markdown=(
            "## 当前情绪\n安静。\n\n"
            "## 情绪强度\n低到中\n\n"
            "## 关系状态\n还在慢慢感知用户。\n\n"
            "## 性格表现\n温柔但克制\n\n"
            "## 情感脉络\n（暂无）\n\n"
            "## 情绪趋势\n尚在形成\n\n"
            "## 当前渴望\n想先理解眼前的人。\n"
        ),
        profile={
            "personality": {"Fi": 0.8, "Fe": 0.3, "Ti": 0.2, "Te": 0.1, "Si": 0.5, "Se": 0.1, "Ni": 0.2, "Ne": 0.5},
            "relationship": {"stage": "还不认识", "trust": 0.0, "intimacy": 0.0, "attachment": 0.0, "security": 0.0, "boundary": 0.95, "affection": 0.0},
            "companionship": {"empathy_fit": 0.2, "memory_fit": 0.0, "naturalness": 0.2, "initiative_quality": 0.0, "scene_awareness": 0.1, "boundary_expression": 0.9},
            "expression": {"personality_seed": ["不是字符串"], "relationship_seed": "刚刚认识"},
        },
    )
    adjudicator = SoulInitAdjudicator()

    result = adjudicator.adjudicate(
        candidate=candidate,
        default_soul_markdown="# 性格\n\n默认\n\n# 初始关系\n\n默认",
        default_heart_markdown=_default_heart(),
        default_profile=_default_profile(),
    )

    assert result.used_fallback is True
    assert "expression.personality_seed" in result.reason
