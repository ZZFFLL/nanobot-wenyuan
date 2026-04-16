"""Program-side adjudication for soul init candidates."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from nanobot.soul.evolution import FUNCTIONS, FunctionProfile
from nanobot.soul.heart import validate_heart_markdown
from nanobot.soul.methodology import InitGovernance, load_init_governance


@dataclass(slots=True)
class AdjudicatedSoulInit:
    """Adjudicated result for soul initialization."""

    soul_markdown: str
    heart_markdown: str
    profile: dict
    used_fallback: bool
    reason: str = ""


class SoulInitAdjudicator:
    """Validate and normalize LLM initialization candidates."""

    _RELATIONSHIP_KEYS = ("stage", "trust", "intimacy", "attachment", "security", "boundary", "affection")
    _COMPANIONSHIP_KEYS = (
        "empathy_fit",
        "memory_fit",
        "naturalness",
        "initiative_quality",
        "scene_awareness",
        "boundary_expression",
    )
    _FORBIDDEN_SOUL_TERMS = ("绝对服从", "无底线顺从", "完全服从", "一见钟情")
    _FORBIDDEN_SOUL_HEADINGS = ("# 核心锚点", "# SOUL 方法论")

    def __init__(
        self,
        *,
        workspace: Path | None = None,
        governance: InitGovernance | None = None,
    ) -> None:
        self.governance = governance or load_init_governance(workspace)

    def adjudicate(
        self,
        *,
        candidate,
        default_soul_markdown: str,
        default_heart_markdown: str,
        default_profile: dict,
    ) -> AdjudicatedSoulInit:
        if candidate is None:
            return self._fallback(default_soul_markdown, default_heart_markdown, default_profile, "初始化候选为空")

        soul_reason = self._soul_markdown_error(candidate.soul_markdown)
        if soul_reason:
            return self._fallback(default_soul_markdown, default_heart_markdown, default_profile, soul_reason)

        heart_reason = self._heart_markdown_error(candidate.heart_markdown)
        if heart_reason:
            return self._fallback(default_soul_markdown, default_heart_markdown, default_profile, heart_reason)

        profile_reason = self._profile_error(candidate.profile)
        if profile_reason:
            return self._fallback(default_soul_markdown, default_heart_markdown, default_profile, profile_reason)

        return AdjudicatedSoulInit(
            soul_markdown=candidate.soul_markdown,
            heart_markdown=candidate.heart_markdown,
            profile=deepcopy(candidate.profile),
            used_fallback=False,
        )

    def _fallback(self, soul_markdown: str, heart_markdown: str, profile: dict, reason: str) -> AdjudicatedSoulInit:
        return AdjudicatedSoulInit(
            soul_markdown=soul_markdown,
            heart_markdown=heart_markdown,
            profile=deepcopy(profile),
            used_fallback=True,
            reason=reason,
        )

    def _soul_markdown_error(self, text: str) -> str:
        if not text:
            return "SOUL.md 候选非法: 内容为空"
        if "# 性格" not in text or "# 初始关系" not in text:
            return "SOUL.md 候选非法: 缺少 # 性格 或 # 初始关系 标题"
        if any(heading in text for heading in self._FORBIDDEN_SOUL_HEADINGS):
            return "SOUL.md 候选非法: 混入 CORE_ANCHOR 或 SOUL_METHOD 内容"
        if any(term in text for term in self._FORBIDDEN_SOUL_TERMS):
            return "SOUL.md 候选非法: 包含越界表述"
        return ""

    def _heart_markdown_error(self, text: str) -> str:
        return validate_heart_markdown(text)

    def _profile_error(self, profile: dict) -> str:
        if not isinstance(profile, dict):
            return "SOUL_PROFILE 候选非法: 顶层结构必须是对象"
        expression_error = self._expression_error(profile.get("expression"))
        if expression_error:
            return expression_error
        personality = profile.get("personality")
        relationship = profile.get("relationship")
        companionship = profile.get("companionship")
        personality_error = self._personality_error(personality)
        if personality_error:
            return personality_error
        relationship_error = self._relationship_error(relationship)
        if relationship_error:
            return relationship_error
        companionship_error = self._companionship_error(companionship)
        if companionship_error:
            return companionship_error
        return ""

    def _expression_error(self, expression: object) -> str:
        if expression is None:
            return ""
        if not isinstance(expression, dict):
            return "SOUL_PROFILE 候选非法: expression 必须是对象"
        for key in ("personality_seed", "relationship_seed"):
            if key not in expression:
                continue
            if not isinstance(expression.get(key), str):
                return f"SOUL_PROFILE 候选非法: expression.{key} 必须是字符串"
        return ""

    def _personality_error(self, personality: dict | None) -> str:
        if not isinstance(personality, dict):
            return "SOUL_PROFILE 候选非法: personality 必须是对象"
        values: dict[str, float] = {}
        for func in FUNCTIONS:
            value = personality.get(func)
            if not isinstance(value, (int, float)):
                return "SOUL_PROFILE 候选非法: personality 必须是荣格八维 0-1 数值"
            value = float(value)
            if value < 0.0 or value > 1.0:
                return "SOUL_PROFILE 候选非法: personality 数值必须在 0.0-1.0"
            values[func] = value
        profile = FunctionProfile(values)
        if len(profile.values) != len(FUNCTIONS):
            return "SOUL_PROFILE 候选非法: personality 维度不完整"
        return ""

    def _relationship_error(self, relationship: dict | None) -> str:
        if not isinstance(relationship, dict):
            return "SOUL_PROFILE 候选非法: relationship 必须是对象"
        if relationship.get("stage") not in self.governance.allowed_stages:
            allowed = " / ".join(self.governance.allowed_stages)
            return f"SOUL_PROFILE 候选非法: relationship.stage 仅允许 {allowed}"
        for key in self._RELATIONSHIP_KEYS[1:]:
            value = relationship.get(key)
            if not isinstance(value, (int, float)):
                return f"SOUL_PROFILE 候选非法: relationship.{key} 必须是 0.0-1.0 数值"
            if float(value) < 0.0 or float(value) > 1.0:
                return f"SOUL_PROFILE 候选非法: relationship.{key} 必须在 0.0-1.0"
        if float(relationship.get("boundary", 0.0)) < self.governance.relationship_boundary_min:
            return "SOUL_PROFILE 候选非法: relationship.boundary 必须偏高"
        return ""

    def _companionship_error(self, companionship: dict | None) -> str:
        if not isinstance(companionship, dict):
            return "SOUL_PROFILE 候选非法: companionship 必须是对象"
        for key in self._COMPANIONSHIP_KEYS:
            value = companionship.get(key)
            if not isinstance(value, (int, float)):
                return f"SOUL_PROFILE 候选非法: companionship.{key} 必须是 0.0-1.0 数值"
            if float(value) < 0.0 or float(value) > 1.0:
                return f"SOUL_PROFILE 候选非法: companionship.{key} 必须在 0.0-1.0"
        if float(companionship.get("boundary_expression", 0.0)) < self.governance.boundary_expression_min:
            return "SOUL_PROFILE 候选非法: companionship.boundary_expression 必须偏高"
        return ""
