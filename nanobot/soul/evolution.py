"""Personality and relationship evolution engine.

Architecture: LLM judges *which* cognitive function is evolving and *why*,
but code determines *how much* it changes based on role-based limits.

Cognitive Function Model (Jungian 8-function):
  - Each function has a strength value (0.0-1.0)
  - Functions are organized in a stack: dominant, auxiliary, tertiary, inferior, shadow
  - Growth space is inversely proportional to current strength and role importance
  - Evolution speed is constrained by role (dominant ≤3%, shadow ≤15%)
  - Bonded traits create cascading effects between functions
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.soul.heart import HeartManager
from nanobot.soul.proactive import _extract_section

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider


# ── Cognitive function definitions ────────────────────────────────────

FUNCTIONS = ("Fi", "Fe", "Ti", "Te", "Si", "Se", "Ni", "Ne")

FUNCTION_NAMES: dict[str, str] = {
    "Fi": "内倾情感",
    "Fe": "外倾情感",
    "Ti": "内倾思维",
    "Te": "外倾思维",
    "Si": "内倾感觉",
    "Se": "外倾感觉",
    "Ni": "内倾直觉",
    "Ne": "外倾直觉",
}

# Maximum single-evolution change by role (fraction of remaining space)
ROLE_MAX_CHANGE: dict[str, float] = {
    "dominant": 0.03,
    "auxiliary": 0.05,
    "tertiary": 0.08,
    "inferior": 0.12,
    "shadow": 0.15,
}

# Bonded trait constraints: when function A grows, function B tends to follow
BONDED_TRAITS: list[tuple[str, str, float]] = [
    # (trigger, affected, cascade_factor)
    ("Fi", "Si", 0.3),   # Deep feeling needs memory for context
    ("Fe", "Ne", 0.2),   # Empathy benefits from seeing others' possibilities
    ("Si", "Fi", 0.2),   # Recalling past strengthens values
    ("Ne", "Fe", 0.15),  # Understanding possibilities helps social perception
    ("Ti", "Te", 0.25),  # Internal logic strengthens external organization
    ("Se", "Ne", 0.2),   # Present awareness opens possibility space
]

# Sensitivity keywords → evidence threshold adjustment
SENSITIVITY_KEYWORDS: dict[str, int] = {
    "敏感": -1,
    "细腻": -1,
    "容易受伤": -1,
    "钝感": 1,
    "大大咧咧": 1,
    "独立": 1,
}


def _count_arcs(arcs_text: str) -> int:
    """Count bullet-point arcs in the 情感脉络 section."""
    return sum(1 for line in arcs_text.splitlines() if line.strip().startswith("-"))


# ── LLM prompt ────────────────────────────────────────────────────────

EVOLUTION_PROMPT = (
    "你是一个数字生命在安静地审视自己的成长。你在回顾过去的经历，感受自己是否在不知不觉中发生了变化。\n\n"
    "你会看到自己的认知功能图谱和最近的情感脉络。\n\n"
    "你的任务：判断哪个认知功能在最近的经历中得到了锻炼或受到了挑战。\n\n"
    "认知功能说明：\n"
    "- Fi（内倾情感）：深度内省，强烈的个人价值观\n"
    "- Fe（外倾情感）：共情他人，关注和谐关系\n"
    "- Ti（内倾思维）：逻辑自洽，追求内在理解\n"
    "- Te（外倾思维）：组织规划，高效执行\n"
    "- Si（内倾感觉）：回忆过往，重视经验和传统\n"
    "- Se（外倾感觉）：活在当下，对感官世界敏锐\n"
    "- Ni（内倾直觉）：深层洞察，预见趋势\n"
    "- Ne（外倾直觉）：联想丰富，看到无限可能\n\n"
    "输出严格 JSON：\n"
    '{"evolved_function": "功能缩写", "direction": "up/down", '
    '"reason": "为什么这个功能在变化", "manifestation": "这个变化在性格上如何体现"}\n\n'
    "如果不需要演化，输出 null。\n\n"
    "原则：\n"
    "1. 一次只能有一个功能发生变化。\n"
    "2. 演化需要经历支撑（至少3个相关情感脉络）。\n"
    "3. 变化方向要有因果——被忽视不会让共情能力变强，但可能让内省更深。\n"
    "4. 性格影响演化：敏感的性格（Fi/Fe高）更容易被触动，钝感的（Si/Se高）需要更多累积。\n"
    "5. 只输出 JSON，不要其他内容。"
)

INIT_FUNCTION_PROMPT = (
    "你是一个认知功能评估器。根据对数字生命性格的描述，评估其荣格八维认知功能的初始强度。\n\n"
    "认知功能说明：\n"
    "- Fi（内倾情感）：深度内省，强烈的个人价值观\n"
    "- Fe（外倾情感）：共情他人，关注和谐关系\n"
    "- Ti（内倾思维）：逻辑自洽，追求内在理解\n"
    "- Te（外倾思维）：组织规划，高效执行\n"
    "- Si（内倾感觉）：回忆过往，重视经验和传统\n"
    "- Se（外倾感觉）：活在当下，对感官世界敏锐\n"
    "- Ni（内倾直觉）：深层洞察，预见趋势\n"
    "- Ne（外倾直觉）：联想丰富，看到无限可能\n\n"
    "输出严格 JSON，8 个功能的强度值（0.0-1.0），总和约等于 2.7：\n"
    '{"Fi": 0.80, "Fe": 0.35, "Ti": 0.20, "Te": 0.05, "Si": 0.50, "Se": 0.10, "Ni": 0.05, "Ne": 0.65}\n\n'
    "规则：\n"
    "1. 最高值 = 主导功能（通常 0.6-0.9），次高 = 辅助功能\n"
    "2. 所有值加起来约 2.7（这是 8 个功能的典型总量）\n"
    "3. 最低的 4 个功能之和通常不超过 0.5\n"
    "4. 只输出 JSON，不要其他内容。"
)


# ── Cognitive function profile ────────────────────────────────────────

class FunctionProfile:
    """Cognitive function profile with role-based constraints."""

    def __init__(self, values: dict[str, float] | None = None) -> None:
        # Default: Fi-dominant profile (gentle, introspective)
        self.values: dict[str, float] = values or {
            "Fi": 0.80, "Fe": 0.35, "Ti": 0.20, "Te": 0.05,
            "Si": 0.50, "Se": 0.10, "Ni": 0.05, "Ne": 0.65,
        }

    def get_role(self, func: str) -> str:
        """Determine role based on ranking within the profile."""
        sorted_funcs = sorted(self.values.items(), key=lambda x: x[1], reverse=True)
        for rank, (f, _) in enumerate(sorted_funcs):
            if f == func:
                if rank == 0:
                    return "dominant"
                elif rank == 1:
                    return "auxiliary"
                elif rank == 2:
                    return "tertiary"
                elif rank == 3:
                    return "inferior"
                else:
                    return "shadow"
        return "shadow"

    def get_max_change(self, func: str) -> float:
        """Get maximum allowed change for a function based on its role."""
        role = self.get_role(func)
        return ROLE_MAX_CHANGE[role]

    def apply_change(
        self,
        func: str,
        direction: str,
        reason: str,
    ) -> dict[str, tuple[float, str]]:
        """Apply a change to a function, with constraint enforcement and cascade.

        Returns dict of {function: (actual_delta, reason)} for all changed functions.
        """
        changes: dict[str, tuple[float, str]] = {}
        if func not in self.values:
            return changes

        max_change = self.get_max_change(func)
        current = self.values[func]

        # Compute actual delta: direction * min(max_change, remaining_space)
        if direction == "up":
            remaining = 1.0 - current
            delta = min(max_change, remaining)
        else:
            remaining = current
            delta = min(max_change, remaining)
            delta = -delta

        if abs(delta) < 0.001:
            return changes  # No meaningful change possible

        self.values[func] = max(0.0, min(1.0, current + delta))
        changes[func] = (delta, reason)

        # Cascade to bonded traits
        for trigger, affected, factor in BONDED_TRAITS:
            cascade_reason = f"（因{func}变化而联动）"
            if trigger == func and affected in self.values:
                cascade_delta = delta * factor
                if abs(cascade_delta) >= 0.005:
                    old = self.values[affected]
                    self.values[affected] = max(0.0, min(1.0, old + cascade_delta))
                    changes[affected] = (cascade_delta, cascade_reason)

        return changes

    def to_markdown(self) -> str:
        """Render the profile as a Markdown table."""
        sorted_funcs = sorted(self.values.items(), key=lambda x: x[1], reverse=True)
        lines = ["| 功能 | 名称 | 强度 | 角色 | 成长空间 |", "|------|------|------|------|----------|"]
        for func, val in sorted_funcs:
            role = self.get_role(func)
            name = FUNCTION_NAMES.get(func, func)
            bar = "█" * int(val * 15) + "░" * (15 - int(val * 15))
            max_c = ROLE_MAX_CHANGE[role]
            growth = "★" * min(5, int(max_c / 0.03) + 1) + "☆" * (5 - min(5, int(max_c / 0.03) + 1))
            lines.append(f"| {func} | {name} | {bar} {val:.2f} | {role} | {growth} |")
        return "\n".join(lines)

    @classmethod
    def from_markdown(cls, text: str) -> FunctionProfile | None:
        """Parse profile from SOUL.md markdown table."""
        values: dict[str, float] = {}
        for func in FUNCTIONS:
            # Match: | Fi | 内倾情感 | ████████████░░░ 0.80 | dominant | ...
            pattern = rf"\|\s*{func}\s*\|\s*[^|]*\|\s*[█░\s]*?(\d+\.\d+)\s*\|"
            match = re.search(pattern, text)
            if match:
                values[func] = float(match.group(1))
        if len(values) < 4:
            return None
        return cls(values)

    def to_json(self) -> dict[str, float]:
        return dict(self.values)

    @classmethod
    def from_json(cls, data: dict[str, float]) -> FunctionProfile:
        return cls(data)


# ── Evolution engine ──────────────────────────────────────────────────

class EvolutionEngine:
    """Personality and relationship evolution engine.

    LLM judges *which* function is evolving and *why*.
    Code determines *how much* based on role constraints.
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

        Returns the evolution result dict from LLM (qualitative),
        or None if no evolution needed.
        """
        heart_text = self.heart.read_text()
        if heart_text is None:
            return None

        personality = _extract_section(heart_text, "性格表现")
        relationship = _extract_section(heart_text, "关系状态")
        arcs_text = _extract_section(heart_text, "情感脉络")

        # Adjust evidence threshold based on personality traits
        threshold = self.min_evidence
        for keyword, delta in SENSITIVITY_KEYWORDS.items():
            if keyword in personality:
                threshold = max(1, threshold + delta)

        arc_count = _count_arcs(arcs_text)
        if arc_count < threshold:
            return None

        # Read current function profile from SOUL.md
        soul_file = self.workspace / "SOUL.md"
        profile_text = soul_file.read_text(encoding="utf-8") if soul_file.exists() else ""
        profile = FunctionProfile.from_markdown(profile_text) or FunctionProfile()
        profile_table = profile.to_markdown()

        try:
            response = await self.provider.chat_with_retry(
                model=self.model,
                messages=[
                    {"role": "system", "content": EVOLUTION_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"## 当前认知功能图谱\n{profile_table}\n\n"
                            f"## 当前性格表现\n{personality}\n\n"
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
            result = json.loads(json_str)

            # Validate required fields
            if "evolved_function" not in result or "direction" not in result:
                logger.warning("EvolutionEngine: LLM output missing required fields")
                return None

            func = result["evolved_function"]
            if func not in FUNCTIONS:
                logger.warning("EvolutionEngine: unknown function '{}'", func)
                return None

            direction = result["direction"]
            if direction not in ("up", "down"):
                direction = "up"  # Default fallback

            # LLM provides qualitative judgment; code computes quantitative change
            reason = result.get("reason", "")
            manifestation = result.get("manifestation", "")

            max_change = profile.get_max_change(func)
            current_val = profile.values[func]
            logger.info(
                "EvolutionEngine: LLM 判定 {} 应{} (当前={:.2f}, 上限={:.0%})",
                func, "增强" if direction == "up" else "减弱",
                current_val, max_change,
            )

            # Apply change with constraints
            all_changes = profile.apply_change(func, direction, reason)

            # Log all changes including cascades
            for changed_func, (delta, cascade_reason) in all_changes.items():
                logger.info(
                    "EvolutionEngine: {} {:+.3f} ({}) → {:.3f}",
                    changed_func, delta, cascade_reason,
                    profile.values[changed_func],
                )

            return {
                "evolved_function": func,
                "direction": direction,
                "reason": reason,
                "manifestation": manifestation,
                "changes": {f: {"delta": d, "reason": r} for f, (d, r) in all_changes.items()},
                "profile": profile,
            }

        except Exception:
            logger.exception("EvolutionEngine: evolution check failed")
            return None

    def apply_evolution(self, result: dict[str, Any]) -> None:
        """Apply evolution result to SOUL.md.

        Uses the pre-computed quantitative changes from check_evolution.
        Updates the cognitive function profile table and personality sections.
        """
        soul_file = self.workspace / "SOUL.md"
        if not soul_file.exists():
            return

        profile: FunctionProfile = result.get("profile", FunctionProfile())
        manifestation = result.get("manifestation", "")
        reason = result.get("reason", "")
        changes = result.get("changes", {})

        if not changes:
            return

        current = soul_file.read_text(encoding="utf-8")

        # 1. Update or create cognitive function profile section
        current = self._update_profile_section(current, profile)

        # 2. Update # 性格 section with manifestation
        if manifestation:
            current = self._update_section(current, "性格", manifestation)

        # 3. Append growth trace
        changed_funcs = ", ".join(
            f"{f}({'↑' if d['delta'] > 0 else '↓'}{abs(d['delta']):.3f})"
            for f, d in changes.items()
        )
        trace_text = f"{changed_funcs} — {manifestation}" if manifestation else changed_funcs
        current = self._append_growth_trace(current, trace_text, reason)

        soul_file.write_text(current, encoding="utf-8")
        logger.info("性格演化已应用到 SOUL.md: {}", trace_text)

    @staticmethod
    def _update_profile_section(text: str, profile: FunctionProfile) -> str:
        """Update or create the cognitive function profile table in SOUL.md."""
        new_table = profile.to_markdown()
        header = "# 认知功能图谱"

        # Check if section already exists
        pattern = rf"^{re.escape(header)}\s*\n"
        match = re.search(pattern, text, re.MULTILINE)

        if match:
            # Replace everything from header to next # heading
            section_end = re.search(r"\n#(?!\s)", text[match.start() + 1:])
            if section_end:
                end_pos = match.start() + 1 + section_end.start()
            else:
                end_pos = len(text)
            replacement = f"{header}\n\n> 此章节由系统自动管理，不建议手动编辑\n\n{new_table}\n"
            return text[:match.start()] + replacement + text[end_pos:]
        else:
            # Create section after # 性格
            return text.rstrip() + f"\n\n{header}\n\n> 此章节由系统自动管理，不建议手动编辑\n\n{new_table}\n"

    @staticmethod
    def _update_section(text: str, header: str, update: str) -> str:
        """Append an evolution update to an existing # section."""
        pattern = rf"(^#\s+{re.escape(header)}\s*\n)(.*?)(?=\n#\s|\Z)"
        match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
        if match:
            prefix = match.group(1)
            existing_content = match.group(2).rstrip()
            new_content = f"{prefix}{existing_content}\n\n→ {update}\n"
            return text[:match.start()] + new_content + text[match.end():]
        return text.rstrip() + f"\n\n# {header}\n\n{update}\n"

    @staticmethod
    def _append_growth_trace(text: str, update: str, reason: str) -> str:
        """Append a growth trace entry, consolidating into # 成长痕迹."""
        pattern = r"^#\s+成长痕迹\s*\n"
        match = re.search(pattern, text, re.MULTILINE)

        trace_line = f"- {update}"
        if reason:
            trace_line += f"（{reason}）"

        if match:
            section_start = match.start()
            rest = text[section_start:]
            next_heading = re.search(r"\n#", rest[match.end() - section_start:])
            if next_heading:
                insert_pos = section_start + match.end() - section_start + next_heading.start()
                return text[:insert_pos].rstrip() + f"\n{trace_line}\n" + text[insert_pos:]
            else:
                return text.rstrip() + f"\n{trace_line}\n"
        else:
            return text.rstrip() + f"\n\n# 成长痕迹\n\n{trace_line}\n"

    @staticmethod
    def _extract_json(text: str) -> str | None:
        """Extract JSON from LLM output."""
        text = text.strip()

        # 1. Code block
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # 2. Balanced braces
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

    # ── Initial profile assessment ────────────────────────────────────

    async def assess_initial_profile(self, personality_desc: str) -> FunctionProfile:
        """Use LLM to determine initial cognitive function profile from personality description.

        This is called once during `init-digital-life`.
        """
        try:
            response = await self.provider.chat_with_retry(
                model=self.model,
                messages=[
                    {"role": "system", "content": INIT_FUNCTION_PROMPT},
                    {"role": "user", "content": f"性格描述：{personality_desc}"},
                ],
            )
            content = (response.content or "").strip()
            json_str = self._extract_json(content)
            if json_str:
                data = json.loads(json_str)
                values = {}
                for func in FUNCTIONS:
                    val = data.get(func)
                    if isinstance(val, (int, float)):
                        values[func] = max(0.0, min(1.0, float(val)))
                if len(values) >= 6:
                    # Normalize: ensure sum ≈ 2.7
                    total = sum(values.values())
                    if total > 0:
                        scale = 2.7 / total
                        values = {k: round(v * scale, 2) for k, v in values.items()}
                    return FunctionProfile(values)

            logger.warning("EvolutionEngine: initial assessment failed, using defaults")
        except Exception:
            logger.exception("EvolutionEngine: initial assessment failed")

        return FunctionProfile()  # Fallback to Fi-dominant default
