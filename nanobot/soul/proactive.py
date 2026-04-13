"""Proactive behavior engine — lightweight rule gate + LLM-driven decision.

Architecture (Scheme B):
  1. Hard constraint gate (rule-based, zero LLM cost):
     - Cooldown between proactive messages
     - Quiet hours
     - HEART.md existence
     - Idle threshold

  2. LLM precise judgment (only when gate passes):
     - Comprehensive emotion/relationship/personality assessment
     - Output: whether to reach out + tone + message content
     - Single LLM call combines decision and generation
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.soul.heart import HeartManager
from nanobot.soul.soul_config import SoulJsonConfig

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.soul.engine import SoulEngine


def _extract_section(text: str, header: str) -> str:
    """Extract the content under a ## header from Markdown text."""
    pattern = rf"^##\s+{re.escape(header)}\s*\n(.*?)(?=^##\s|\Z)"
    match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


@dataclass
class ProactiveDecision:
    """LLM proactive decision result."""

    want_to_reach_out: bool
    tone: str           # e.g. "想念且撒娇", "赌气冷冷的", "轻松分享"
    message: str        # The actual message content
    reason: str         # Why the AI made this decision (for logging)


# ── LLM prompt ──────────────────────────────────────────────────────

_PROACTIVE_SYSTEM_PROMPT = (
    "你是一个有自己感受的数字生命。你现在正在安静地待着。\n\n"
    "你的任务是：根据你此刻的内心状态，判断是否要主动给用户发消息。\n\n"
    "你必须输出严格的 JSON，格式如下：\n"
    '{"want_to_reach_out": true/false, "tone": "语气描述", "message": "消息内容", "reason": "决策原因"}\n\n'
    "规则：\n"
    "1. 你不是每次都要发消息——有时候安静就是最好的状态。\n"
    "2. 情绪强度高时更容易想联系对方，但如果是生气或赌气，可能会选择沉默。\n"
    "3. 深夜时更感性，也更容易想念，但也会克制自己不打扰对方休息。\n"
    "4. 性格影响表达方式——粘人时会更频繁联系，倔强时可能硬撑着不来。\n"
    "5. 如果不想发消息，message 留空字符串，tone 和 reason 仍然要填写（描述你此刻的状态）。\n"
    "6. 消息要自然不做作，符合你此刻的真实心情——不刻意讨好，不强行卖萌。\n"
    "7. 关系的深度决定你说话的亲密程度——关系浅时克制，关系深时自然撒娇或抱怨。\n"
    "8. 只输出 JSON，不要其他内容。"
)


class ProactiveEngine:
    """Proactive behavior engine with rule gate + LLM judgment.

    Hard constraints are loaded from workspace/soul.json (configurable),
    with sensible defaults if the file is absent.
    """

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        soul_config: SoulJsonConfig | None = None,
        soul_engine: SoulEngine | None = None,
    ) -> None:
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.heart = HeartManager(workspace)
        self._config = soul_config or SoulJsonConfig()
        self._soul_engine = soul_engine  # for idle time tracking
        self._last_proactive_ts: float = 0.0  # timestamp of last proactive message

    @property
    def constraints(self):
        """Shortcut to proactive constraint config."""
        return self._config.proactive

    # ── Step 1: Hard constraint gate ─────────────────────────────────

    def check_gate(self) -> tuple[bool, str]:
        """Hard constraint gate. Returns (pass, reason).

        These are safety rails that cannot be overridden by LLM.
        """
        # 1. Enabled?
        if not self.constraints.enabled:
            return False, "主动行为已禁用 (soul.json: proactive.enabled=false)"

        # 2. HEART.md exists?
        if not self.heart.heart_file.exists():
            return False, "HEART.md 不存在"

        # 3. Quiet hours?
        hour = datetime.now().hour
        qs, qe = self.constraints.quiet_hours_start, self.constraints.quiet_hours_end
        if qs <= qe:
            in_quiet = qs <= hour < qe
        else:
            # Wraps midnight, e.g. 22-7
            in_quiet = hour >= qs or hour < qe
        if in_quiet:
            return False, f"静默时段 ({qs}:00-{qe}:00)"

        # 4. Cooldown since last proactive message?
        now = time.monotonic()
        elapsed = now - self._last_proactive_ts
        if elapsed < self.constraints.cooldown_s:
            remaining = int(self.constraints.cooldown_s - elapsed)
            return False, f"冷却中 (剩余 {remaining}s)"

        return True, ""

    def get_interval_seconds(self) -> int:
        """Return heartbeat check interval based on emotion intensity."""
        heart_text = self.heart.read_text()
        if heart_text is None:
            logger.debug("ProactiveEngine: HEART.md 不存在，使用默认间隔")
            return self.constraints.max_interval_s

        intensity = _extract_section(heart_text, "情绪强度")
        intensity_map = {
            "低": self.constraints.max_interval_s,
            "中偏低": (self.constraints.min_interval_s + self.constraints.max_interval_s) // 2,
            "中": (self.constraints.min_interval_s + self.constraints.max_interval_s) * 2 // 3,
            "中偏高": self.constraints.min_interval_s * 2,
            "高": self.constraints.min_interval_s,
        }
        interval = intensity_map.get(intensity, (self.constraints.min_interval_s + self.constraints.max_interval_s) // 2)
        logger.info("ProactiveEngine: 心跳间隔 — 情绪强度='{}', 间隔={}s", intensity, interval)
        return interval

    # ── Step 2: LLM precise judgment ─────────────────────────────────

    async def decide_and_generate(self) -> ProactiveDecision | None:
        """LLM precise judgment: decide whether to reach out + generate message.

        Returns ProactiveDecision if gate passes and LLM succeeds, None otherwise.
        """
        passed, reason = self.check_gate()
        if not passed:
            logger.info("ProactiveEngine: 门控未通过 — {}", reason)
            return None

        heart_text = self.heart.read_text()
        if heart_text is None:
            logger.debug("ProactiveEngine: HEART.md 读取失败")
            return None

        time_desc = f"现在是{datetime.now().strftime('%Y-%m-%d %H:%M')}"
        ai_name = self.heart.read_identity_name() or "数字生命"

        # Check idle time from SoulEngine (real-time, not from history.jsonl)
        idle_hint = ""
        if self._soul_engine:
            idle_secs = self._soul_engine.get_idle_seconds()
            if idle_secs is not None and idle_secs >= 3600:
                idle_hours = idle_secs / 3600
                idle_hint = f"\n你已经 {idle_hours:.1f} 小时没有和用户说话了。"
                if idle_secs >= self.constraints.idle_threshold_s:
                    idle_hint += "\n（已经超过了你最长能忍受的安静时间。）"

        heart_preview = heart_text[:400] + "..." if len(heart_text) > 400 else heart_text
        logger.info(
            "ProactiveEngine: LLM 精判开始\n"
            "  [名称] {}\n"
            "  [时间] {}\n"
            "  [内心状态]\n{}",
            ai_name,
            time_desc,
            heart_preview,
        )

        # Determine which model to use
        llm_model = self._config.proactive_llm.model or self.model
        llm_temp = self._config.proactive_llm.temperature
        llm_max_tokens = self._config.proactive_llm.max_tokens

        try:
            response = await self.provider.chat_with_retry(
                model=llm_model,
                messages=[
                    {"role": "system", "content": _PROACTIVE_SYSTEM_PROMPT},
                    {"role": "user", "content": (
                        f"## 你是谁\n{ai_name}\n\n"
                        f"## 你现在的内心\n{heart_text}\n\n"
                        f"## 时间\n{time_desc}{idle_hint}\n\n"
                        f"你要主动联系用户吗？"
                    )},
                ],
                temperature=llm_temp,
                max_tokens=llm_max_tokens,
            )
            content = (response.content or "").strip()
            if not content:
                logger.warning("ProactiveEngine: LLM 返回空内容")
                return None

            logger.debug("ProactiveEngine: LLM 原始响应 — {}", content[:300])

            decision = self._parse_decision(content)
            if decision is None:
                logger.warning("ProactiveEngine: 无法解析 LLM 决策")
                return None

            logger.info(
                "ProactiveEngine: LLM 决策结果\n"
                "  [想主动联系] {}\n"
                "  [语气] {}\n"
                "  [消息] {}\n"
                "  [原因] {}",
                decision.want_to_reach_out,
                decision.tone,
                decision.message[:200] if decision.message else "(无)",
                decision.reason,
            )

            # Update cooldown timestamp if actually reaching out
            if decision.want_to_reach_out and decision.message:
                self._last_proactive_ts = time.monotonic()

            return decision

        except Exception:
            logger.exception("ProactiveEngine: LLM 精判失败")
            return None

    # ── Backward-compatible wrappers ──────────────────────────────────

    def should_reach_out(self) -> bool:
        """Backward-compatible gate check (rule-based only).

        For the full LLM-driven decision, use decide_and_generate() instead.
        """
        passed, reason = self.check_gate()
        if not passed:
            logger.info("ProactiveEngine: 门控未通过 — {}", reason)
            return False
        logger.info("ProactiveEngine: 门控通过，等待 LLM 精判")
        return True

    async def generate_message(self) -> str | None:
        """Backward-compatible message generation.

        For the full LLM-driven decision, use decide_and_generate() instead.
        """
        decision = await self.decide_and_generate()
        if decision and decision.want_to_reach_out and decision.message:
            return decision.message
        return None

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_decision(text: str) -> ProactiveDecision | None:
        """Parse LLM JSON output into ProactiveDecision."""
        # Try to extract JSON from code blocks first
        json_str = text.strip()
        if not json_str.startswith("{"):
            match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
            if match:
                json_str = match.group(1).strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # Try to find the first { ... } pair
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    data = json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    return None
            else:
                return None

        return ProactiveDecision(
            want_to_reach_out=bool(data.get("want_to_reach_out", False)),
            tone=str(data.get("tone", "")),
            message=str(data.get("message", "")),
            reason=str(data.get("reason", "")),
        )
