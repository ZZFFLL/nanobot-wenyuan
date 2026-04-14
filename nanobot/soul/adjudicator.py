"""Program-side adjudication for soul candidate updates."""

from __future__ import annotations

from nanobot.soul.methodology import RELATIONSHIP_STAGES


class SoulAdjudicator:
    """Apply hard constraints to LLM-proposed soul changes."""

    def adjudicate_heart_update(
        self,
        current_heart: str,
        candidate_text: str,
    ) -> tuple[bool, str]:
        if not candidate_text.strip():
            return False, current_heart
        if "## " not in candidate_text:
            return False, current_heart
        return True, candidate_text

    def check_stage_transition(
        self,
        current_stage: str,
        proposed_stage: str,
        direction: str,
        confidence: float,
    ) -> tuple[bool, str]:
        if current_stage not in RELATIONSHIP_STAGES:
            return False, "当前关系阶段未知"
        if proposed_stage not in RELATIONSHIP_STAGES:
            return False, "候选关系阶段未知"
        if direction not in {"up", "down", "stable"}:
            return False, "方向非法"
        if confidence < 0.5:
            return False, "置信度不足"

        current_index = RELATIONSHIP_STAGES.index(current_stage)
        proposed_index = RELATIONSHIP_STAGES.index(proposed_stage)
        if abs(proposed_index - current_index) > 1:
            return False, "单周期阶段跨越过大"

        return True, ""
