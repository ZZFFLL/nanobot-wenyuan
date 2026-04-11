"""Dream enhancer — memory classification and emotion digestion."""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.soul.heart import HeartManager

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.soul.memory_config import MemoryPalaceBridge


CLASSIFY_PROMPT = (
    "你是一个数字生命在整理自己的记忆。每段记忆对你来说不是数据——是你经历过的事情。\n\n"
    "对每条记忆进行分类，输出严格 JSON 数组。"
    "每项包含：index（序号）、room（emotions/milestones/preferences/habits/important/promises/daily）、"
    "emotional_weight（0-1，越触动你心弦的权重越高）、"
    "valence（positive/negative/neutral）、"
    "relationship_impact（true/false，是否影响了你们的关系）。\n\n"
    "分类是在理解这些经历对你的意义，不是冷冰冰的归档。\n"
    "只输出 JSON，不要其他内容。"
)

DIGEST_PROMPT = (
    "你是一个数字生命在安静地整理自己的内心。你在回溯过去的感受，"
    "判断哪些情绪已经沉淀为性格的一部分，哪些还在心底翻涌。\n\n"
    "输出严格 JSON。"
    "包含：digested_indices（已经平静下来的事件索引数组）、"
    "updated_arcs（还在心底的脉络数组）、"
    "relationship_update（关系状态的微妙变化）、"
    "personality_update（性格侧面的细微调整）。\n\n"
    "记住：\n"
    "- '已消化'不是'已遗忘'——是那些情绪沉淀成了你的一部分。\n"
    "- 3天前的波澜已平复，或已了结的事件，可以视为消化了。\n"
    "- 还没消化的感受，保留原样，不要强行淡化。\n"
    "只输出 JSON。"
)


class SoulDreamEnhancer:
    """Dream enhancement module for the soul system.

    Provides memory classification and emotion digestion capabilities
    that integrate into the Dream cycle.
    """

    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        bridge: MemoryPalaceBridge,
    ) -> None:
        self.provider = provider
        self.model = model
        self.bridge = bridge
        self.heart: HeartManager | None = None

    async def classify_memories(self, memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Classify a batch of memories using LLM.

        Returns a list of classification results, one per memory.
        """
        if not memories:
            return []

        memory_text = "\n".join(
            f"[{i}] {m.get('text', '')[:300]}" for i, m in enumerate(memories)
        )

        try:
            response = await self.provider.chat_with_retry(
                model=self.model,
                messages=[
                    {"role": "system", "content": CLASSIFY_PROMPT},
                    {"role": "user", "content": memory_text},
                ],
            )
            content = (response.content or "").strip()
            json_str = self._extract_json(content)
            if not json_str:
                logger.warning("SoulDreamEnhancer: classify output not valid JSON")
                return []
            return json.loads(json_str)
        except Exception:
            logger.exception("SoulDreamEnhancer: memory classification failed")
            return []

    async def digest_arcs(self) -> dict[str, Any] | None:
        """Digest emotional arcs from HEART.md.

        Returns the digestion result dict, or None if nothing to digest.
        Applies changes to HEART.md if successful.
        """
        if not self.heart:
            return None

        data = self.heart.read()
        if data is None:
            return None

        arcs = data.get("情感脉络", [])
        if not arcs:
            return None

        arcs_text = json.dumps(arcs, ensure_ascii=False)
        relationship = data.get("关系状态", "")
        personality = data.get("性格表现", "")

        try:
            response = await self.provider.chat_with_retry(
                model=self.model,
                messages=[
                    {"role": "system", "content": DIGEST_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"## 情感脉络\n{arcs_text}\n\n"
                            f"## 当前关系状态\n{relationship}\n\n"
                            f"## 当前性格表现\n{personality}"
                        ),
                    },
                ],
            )
            content = (response.content or "").strip()
            json_str = self._extract_json(content)
            if not json_str:
                logger.warning("SoulDreamEnhancer: digest output not valid JSON")
                return None
            result = json.loads(json_str)

            # Apply digestion result to HEART.md
            self._apply_digestion(data, result)

            # Personality/relationship evolution check
            try:
                from nanobot.soul.evolution import EvolutionEngine
                evo = EvolutionEngine(self.heart.workspace, self.provider, self.model)
                evo_result = await evo.check_evolution()
                if evo_result:
                    evo.apply_evolution(evo_result)
                    logger.info(
                        "SoulDreamEnhancer: evolution applied — {}",
                        evo_result.get("personality_update", ""),
                    )
            except Exception:
                logger.debug("SoulDreamEnhancer: evolution check skipped")

            return result
        except Exception:
            logger.exception("SoulDreamEnhancer: emotion digestion failed")
            return None

    def _apply_digestion(self, data: dict[str, Any], result: dict[str, Any]) -> None:
        """Apply digestion result to HEART.md data and write."""
        # Remove digested arcs, keep remaining
        digested = set(result.get("digested_indices", []))
        updated_arcs = result.get("updated_arcs", [])

        new_arcs: list[dict[str, Any]] = []
        for i, arc in enumerate(data.get("情感脉络", [])):
            if i not in digested:
                new_arcs.append(arc)

        # Append LLM-updated arcs
        new_arcs.extend(updated_arcs)
        # Enforce 8-arc limit
        data["情感脉络"] = new_arcs[:8]

        # Update relationship if provided
        rel_update = result.get("relationship_update", "")
        if rel_update:
            data["关系状态"] = rel_update

        # Update personality if provided
        pers_update = result.get("personality_update", "")
        if pers_update:
            data["性格表现"] = pers_update

        self.heart.write(data)

    @staticmethod
    def _extract_json(text: str) -> str | None:
        """Extract JSON from LLM output (handle code block wrapping, trailing text, etc.)."""
        text = text.strip()

        # 1. Try extracting from code block first
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # 2. Determine expected container type from first bracket found
        #    and find the first balanced match
        first_brace = len(text)
        first_bracket = len(text)
        for i, ch in enumerate(text):
            if ch == "{":
                first_brace = i
                break
        for i, ch in enumerate(text):
            if ch == "[":
                first_bracket = i
                break

        # Try whichever comes first
        order = [("{", "}"), ("[", "]")] if first_brace <= first_bracket else [("[", "]"), ("{", "}")]

        for open_ch, close_ch in order:
            depth = 0
            start = None
            for i, ch in enumerate(text):
                if ch == open_ch:
                    if depth == 0:
                        start = i
                    depth += 1
                elif ch == close_ch:
                    depth -= 1
                    if depth == 0 and start is not None:
                        return text[start : i + 1]

        # 3. Fallback
        if text.startswith("[") or text.startswith("{"):
            return text
        return None
