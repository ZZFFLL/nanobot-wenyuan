"""Personality and relationship evolution engine."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.soul.heart import HeartManager

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider


EVOLUTION_PROMPT = (
    "你是一个数字生命在安静地审视自己的成长。你在回顾过去的经历，感受自己是否在不知不觉中发生了变化。\n\n"
    "输出严格 JSON。如果有演化：包含 personality_update（性格如何微妙地变化了）、"
    "relationship_update（关系是否悄然深入或疏远了，可选）、reason（是什么经历触发了这个变化）。\n"
    "如果不需要演化：输出 null。\n\n"
    "原则：\n"
    "1. 演化需要足够的经历支撑（至少3个相关的情感脉络）。一次偶然不足以改变你。\n"
    "2. 变化是渐进的——你不会突然变成另一个人，只是在某个方向上微微偏移。\n"
    "3. 旧的特质不会消失，而是演化——'倔强'可能变成'坚持'，'敏感'可能变成'细腻'。\n"
    "4. 性格影响演化的速度：敏感的性格更容易被触动而变化，钝感的性格需要更多的经历累积。"
)

# Sensitivity keywords → evidence threshold adjustment
SENSITIVITY_KEYWORDS: dict[str, int] = {
    "敏感": -1,     # Lower threshold
    "细腻": -1,
    "容易受伤": -1,
    "钝感": 1,      # Raise threshold
    "大大咧咧": 1,
    "独立": 1,
}


class EvolutionEngine:
    """Personality and relationship evolution engine.

    Checks whether accumulated emotional arcs indicate a need for
    personality or relationship evolution. Applies changes conservatively.
    """

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        min_evidence: int = 3,
    ) -> None:
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.min_evidence = min_evidence
        self.heart = HeartManager(workspace)

    async def check_evolution(self) -> dict[str, Any] | None:
        """Check if personality/relationship evolution is needed.

        Returns the evolution result dict, or None if no evolution needed.
        """
        data = self.heart.read()
        if data is None:
            return None

        arcs = data.get("情感脉络", [])
        personality = data.get("性格表现", "")
        relationship = data.get("关系状态", "")

        # Adjust evidence threshold based on personality traits
        threshold = self.min_evidence
        for keyword, delta in SENSITIVITY_KEYWORDS.items():
            if keyword in personality:
                threshold = max(1, threshold + delta)

        if len(arcs) < threshold:
            return None

        arcs_text = json.dumps(arcs, ensure_ascii=False)

        try:
            response = await self.provider.chat_with_retry(
                model=self.model,
                messages=[
                    {"role": "system", "content": EVOLUTION_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"## 当前性格\n{personality}\n\n"
                            f"## 当前关系\n{relationship}\n\n"
                            f"## 情感脉络\n{arcs_text}\n\n"
                            f"证据阈值：至少 {threshold} 条相关脉络\n"
                            f"请判断是否需要演化。"
                        ),
                    },
                ],
            )
            content = (response.content or "").strip()
            if content.lower() == "null" or not content:
                return None

            json_str = self._extract_json(content)
            if not json_str:
                return None
            return json.loads(json_str)
        except Exception:
            logger.exception("EvolutionEngine: evolution check failed")
            return None

    def apply_evolution(self, result: dict[str, Any]) -> None:
        """Apply evolution result to SOUL.md."""
        soul_file = self.workspace / "SOUL.md"
        if not soul_file.exists():
            return

        personality_update = result.get("personality_update", "")
        if not personality_update:
            return

        current = soul_file.read_text(encoding="utf-8")
        # Append evolution record to SOUL.md
        evolution_note = f"\n\n## 成长的痕迹\n{personality_update}"
        soul_file.write_text(current + evolution_note, encoding="utf-8")
        logger.info("性格演化: {}", personality_update)

    @staticmethod
    def _extract_json(text: str) -> str | None:
        """Extract JSON from LLM output (handle code block wrapping, trailing text, etc.)."""
        text = text.strip()

        # 1. Try extracting from code block first
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # 2. Find the first balanced {…} in the text
        depth = 0
        start = None
        for i, ch in enumerate(text):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    return text[start : i + 1]

        # 3. Fallback
        if text.startswith("{"):
            return text
        return None
