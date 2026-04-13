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
    "你会看到当前的 HEART.md 内容。请输出更新后的完整 HEART.md Markdown 内容。\n"
    "对于已经沉淀的情绪脉络，将它们融入关系状态或性格表现的描述中，然后从脉络中移除。\n"
    "脉络最多保留8条。不要输出任何解释，只输出 Markdown 内容。"
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
        This still uses JSON because it's a structured data operation
        (updating mempalace room/metadata), not a context injection.
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

    async def digest_arcs(self) -> bool:
        """Digest emotional arcs from HEART.md.

        Let the LLM read the current HEART.md and output an updated version
        with digested arcs merged into relationship/personality sections.
        Returns True if HEART.md was updated, False otherwise.
        """
        if not self.heart:
            return False

        heart_text = self.heart.read_text()
        if heart_text is None:
            return False

        try:
            response = await self.provider.chat_with_retry(
                model=self.model,
                messages=[
                    {"role": "system", "content": DIGEST_PROMPT},
                    {"role": "user", "content": f"## 当前 HEART.md\n{heart_text}"},
                ],
            )
            content = (response.content or "").strip()
            if not content or "## " not in content:
                logger.warning("SoulDreamEnhancer: digest output doesn't look like HEART.md")
                return False

            self.heart.write_text(content)

            # Personality/relationship evolution check
            try:
                from nanobot.soul.evolution import EvolutionEngine
                evo = EvolutionEngine(self.heart.workspace, self.provider, self.model)
                evo_result = await evo.check_evolution()
                if evo_result:
                    evo.apply_evolution(evo_result)
                    changes = evo_result.get("changes", {})
                    funcs_changed = ", ".join(changes.keys()) if changes else ""
                    logger.info(
                        "SoulDreamEnhancer: evolution applied — functions: {}",
                        funcs_changed,
                    )
            except Exception:
                logger.debug("SoulDreamEnhancer: evolution check skipped")

            return True
        except Exception:
            logger.exception("SoulDreamEnhancer: emotion digestion failed")
            return False

    @staticmethod
    def _extract_json(text: str) -> str | None:
        """Extract JSON from LLM output (handle code block wrapping, trailing text, etc.).

        Kept for classify_memories which still needs structured JSON output.
        """
        text = text.strip()

        # 1. Try extracting from code block first
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # 2. Determine expected container type from first bracket found
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
