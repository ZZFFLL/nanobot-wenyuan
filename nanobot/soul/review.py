"""Weekly soul review generation and scheduling."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from nanobot.cron.types import CronJob, CronPayload, CronSchedule
from nanobot.soul.adjudicator import SoulAdjudicator
from nanobot.soul.heart import HeartManager
from nanobot.soul.inference import RelationshipInference
from nanobot.soul.profile import SoulProfileManager
from nanobot.soul.proactive import _extract_section

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider


class WeeklyReviewBuilder:
    """Build a weekly markdown review from current soul state."""

    def __init__(
        self,
        provider: "LLMProvider | None" = None,
        model: str | None = None,
        adjudicator: SoulAdjudicator | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.adjudicator = adjudicator or SoulAdjudicator()

    def render(self, payload: dict) -> str:
        summary = payload.get("summary", "")
        emotion = payload.get("emotion", "")
        stage = payload.get("relationship_stage", "")
        proactive_excerpt = payload.get("proactive_excerpt", "")
        return (
            "# 周复盘\n\n"
            f"## 本周摘要\n{summary}\n\n"
            f"## 当前情绪切片\n{emotion or '（暂无）'}\n\n"
            f"## 当前关系阶段\n{stage or '（未知）'}\n\n"
            f"## 近期主动陪伴材料\n{proactive_excerpt or '（暂无）'}\n"
        )

    def build(self, workspace: Path) -> str:
        heart_text = HeartManager(workspace).read_text() or ""
        profile = SoulProfileManager(workspace).read()
        summary = "本周自动复盘已生成，等待后续更丰富的趋势材料接入。"
        emotion = _extract_section(heart_text, "当前情绪") if heart_text else ""
        stage = profile.get("relationship", {}).get("stage", "熟悉")
        proactive_excerpt = self._recent_log_excerpt(workspace, "proactive")
        return self.render({
            "summary": summary,
            "emotion": emotion,
            "relationship_stage": stage,
            "proactive_excerpt": proactive_excerpt,
        })

    async def build_cycle(self, workspace: Path) -> str:
        heart_text = HeartManager(workspace).read_text() or ""
        profile_mgr = SoulProfileManager(workspace)
        profile = profile_mgr.read()
        current_stage = profile.get("relationship", {}).get("stage", "熟悉")
        proactive_excerpt = self._recent_log_excerpt(workspace, "proactive")
        summary = "本周自动复盘已生成，等待后续更丰富的趋势材料接入。"
        if self.provider and self.model:
            candidate = await self._infer_relationship_cycle(
                current_stage=current_stage,
                heart_text=heart_text,
                proactive_excerpt=proactive_excerpt,
                profile=profile,
            )
            if candidate is not None:
                allowed, _ = self.adjudicator.check_stage_transition(
                    current_stage=current_stage,
                    proposed_stage=candidate.proposed_stage,
                    direction=candidate.direction,
                    confidence=candidate.confidence,
                )
                if allowed:
                    profile_mgr.update_relationship(
                        stage=candidate.proposed_stage,
                        dimension_deltas=candidate.dimension_changes,
                    )
                    profile = profile_mgr.read()
                    current_stage = profile.get("relationship", {}).get("stage", current_stage)
                    summary = candidate.evidence_summary or summary
        emotion = _extract_section(heart_text, "当前情绪") if heart_text else ""
        return self.render({
            "summary": summary,
            "emotion": emotion,
            "relationship_stage": current_stage,
            "proactive_excerpt": proactive_excerpt,
        })

    async def _infer_relationship_cycle(
        self,
        *,
        current_stage: str,
        heart_text: str,
        proactive_excerpt: str,
        profile: dict,
    ) -> RelationshipInference | None:
        response = await self.provider.chat_with_retry(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是关系演化评估器。根据当前内心状态、近期主动陪伴材料，"
                        "输出严格 JSON："
                        '{"current_stage_assessment":"","proposed_stage":"","direction":"up/down/stable","evidence_summary":"","dimension_changes":{},"personality_influence":"","risk_flags":[],"confidence":0.0}'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"## 当前关系阶段\n{current_stage}\n\n"
                        f"## 当前结构化画像\n{json.dumps(profile, ensure_ascii=False, indent=2)}\n\n"
                        f"## 当前 HEART\n{heart_text}\n\n"
                        f"## 近期主动陪伴材料\n{proactive_excerpt or '（暂无）'}"
                    ),
                },
            ],
        )
        content = (response.content or "").strip()
        if not content:
            return None
        data = self._parse_json_payload(content)
        return RelationshipInference(**data)

    @staticmethod
    def _parse_json_payload(text: str) -> dict:
        """Parse JSON content with tolerance for fenced blocks or wrapper text."""

        candidate = text.strip()
        if not candidate.startswith("{"):
            match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", candidate, re.DOTALL)
            if match:
                candidate = match.group(1).strip()

        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start >= 0 and end > start:
                return json.loads(candidate[start : end + 1])
            raise

    @staticmethod
    def _recent_log_excerpt(workspace: Path, kind: str, limit: int = 3) -> str:
        log_dir = workspace / "soul_logs" / kind
        if not log_dir.exists():
            return ""
        files = sorted(log_dir.glob("*.md"), reverse=True)[:limit]
        snippets = []
        for path in files:
            text = path.read_text(encoding="utf-8").strip()
            if text:
                snippets.append(text[:400])
        return "\n\n".join(snippets)


def build_weekly_review_job(timezone: str) -> CronJob:
    """Build the weekly review system job definition."""

    return CronJob(
        id="weekly_review",
        name="weekly_review",
        schedule=CronSchedule(kind="cron", expr="0 3 * * 1", tz=timezone),
        payload=CronPayload(kind="system_event"),
    )
