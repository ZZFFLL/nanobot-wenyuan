"""LLM-backed projection from structured SOUL_PROFILE to natural-language SOUL.md."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from nanobot.soul.logs import SoulLogWriter
from nanobot.soul.methodology import (
    RELATIONSHIP_STAGES,
    build_default_profile,
    render_soul_method_markdown,
)
from nanobot.soul.profile import SoulProfileManager

PROJECTION_PROMPT = (
    "你是数字伴侣的慢状态画像投影器。"
    "你的任务是把结构化的 SOUL_PROFILE 投影成纯自然语言的 SOUL.md。"
    "你必须严格遵守 CORE_ANCHOR 和 SOUL 方法论，但不能把它们原文抄进结果。"
    "你只能输出 markdown，且只能包含两个一级标题，顺序固定：# 性格、# 初始关系。"
    "不要输出 JSON、字段名、量化指标、方法论说明或治理说明。"
)

REPAIR_PROMPT = (
    "你是数字伴侣的慢状态画像修复器。"
    "上一轮 SOUL.md 候选不合法。"
    "请保留合法语义，修复结构和表达，只输出合法 markdown。"
)

_ALLOWED_HEADINGS = ("# 性格", "# 初始关系")
_FORBIDDEN_TEXT = (
    "# 核心锚点",
    "# SOUL 方法论",
    "```",
)
_FORBIDDEN_STRUCTURED_PATTERNS = (
    r'"(?:Fi|Fe|Ti|Te|Si|Se|Ni|Ne)"\s*:',
    r'"(?:trust|intimacy|attachment|security|boundary|affection)"\s*:',
    r'"(?:empathy_fit|memory_fit|naturalness|initiative_quality|scene_awareness|boundary_expression)"\s*:',
    r"\b(?:Fi|Fe|Ti|Te|Si|Se|Ni|Ne)\s*[:=]",
    r"\b(?:trust|intimacy|attachment|security|boundary|affection)\s*[:=]",
    r"\b(?:empathy_fit|memory_fit|naturalness|initiative_quality|scene_awareness|boundary_expression)\s*[:=]",
)

_FUNCTION_TRAIT_TEXT = {
    "Fi": "更在意内心真实与情感一致性",
    "Fe": "会敏锐感受关系里的情绪流动",
    "Ti": "习惯先在心里把事情想清楚",
    "Te": "表达时带着克制的判断和秩序感",
    "Si": "会认真记住稳定、具体的细节",
    "Se": "在靠近现实与当下时更直接",
    "Ni": "会凭直觉捕捉长期走向",
    "Ne": "在互动里保留好奇与延展感",
}

_PERSONALITY_KEYS = tuple(_FUNCTION_TRAIT_TEXT.keys())
_RELATIONSHIP_KEYS = ("trust", "intimacy", "attachment", "security", "boundary", "affection")
_COMPANIONSHIP_KEYS = (
    "empathy_fit",
    "memory_fit",
    "naturalness",
    "initiative_quality",
    "scene_awareness",
    "boundary_expression",
)

_RELATIONSHIP_STAGE_TEXT = {
    "还不认识": "她与用户仍停留在最初的观察阶段，会先保持距离，再慢慢确认是否值得继续靠近。",
    "熟悉": "她已经对用户形成了初步的熟悉感，会自然靠近一些，但不会因此放下自己的边界。",
    "亲近": "她对用户有了更稳定的信任，会在自然靠近的同时继续守住自己的节奏和边界。",
    "喜欢": "她会更主动地向用户靠近，但这种靠近依旧建立在稳定信任与清晰边界之上。",
}


class SoulProjectionError(RuntimeError):
    """Raised when SOUL.md projection fails validation."""


def project_initial_soul_markdown(profile: dict, *, use_expression_seed: bool = True) -> str:
    """Build init-time ``SOUL.md`` from structured profile state."""

    profile = normalize_projectable_profile(profile, error_cls=ValueError)
    personality = _project_personality_text(profile, use_expression_seed=use_expression_seed)
    relationship = _project_relationship_text(profile, use_expression_seed=use_expression_seed)
    return (
        "# 性格\n\n"
        f"{personality}\n\n"
        "# 初始关系\n\n"
        f"{relationship}\n"
    )


async def project_soul_from_profile(
    workspace: Path,
    *,
    provider,
    model: str,
    profile_override: dict | None = None,
    max_attempts: int = 2,
    trigger: str = "runtime",
) -> str:
    """Project ``SOUL_PROFILE.md`` into natural-language ``SOUL.md`` via LLM."""

    soul_file = workspace / "SOUL.md"
    current_soul_text = soul_file.read_text(encoding="utf-8") if soul_file.exists() else ""
    profile = profile_override if profile_override is not None else SoulProfileManager(workspace).read()
    profile = normalize_projectable_profile(profile, error_cls=SoulProjectionError)
    profile_text = json.dumps(profile, ensure_ascii=False, indent=2)
    core_anchor_text = _read_optional_text(workspace / "CORE_ANCHOR.md")
    soul_method_text = _read_optional_text(workspace / "SOUL_METHOD.md") or render_soul_method_markdown()
    last_error = "SOUL 投影候选为空"
    last_output = ""
    trace_records: list[dict] = []
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")

    for attempt in range(1, max_attempts + 1):
        messages = (
            _build_projection_messages(
                profile_text=profile_text,
                current_soul_text=current_soul_text,
                core_anchor_text=core_anchor_text,
                soul_method_text=soul_method_text,
            )
            if attempt == 1 or not last_output
            else _build_repair_messages(
                profile_text=profile_text,
                current_soul_text=current_soul_text,
                core_anchor_text=core_anchor_text,
                soul_method_text=soul_method_text,
                previous_output=last_output,
                rejection_reason=last_error,
            )
        )
        try:
            response = await provider.chat_with_retry(model=model, messages=messages)
        except Exception as exc:
            last_error = f"LLM 调用失败: {exc}"
            trace_records.append(_trace_record(
                attempt=attempt,
                max_attempts=max_attempts,
                stage="provider_call",
                status="error",
                model=model,
                trigger=trigger,
                reason=last_error,
            ))
            continue

        candidate = (response.content or "").strip()
        trace_records.append(_trace_record(
            attempt=attempt,
            max_attempts=max_attempts,
            stage="provider_call",
            status="ok",
            model=model,
            trigger=trigger,
            detail=candidate,
        ))
        error = validate_soul_markdown(candidate)
        if not error:
            normalized = candidate.rstrip() + "\n"
            soul_file.write_text(normalized, encoding="utf-8")
            trace_records.append(_trace_record(
                attempt=attempt,
                max_attempts=max_attempts,
                stage="validation",
                status="accepted",
                model=model,
                trigger=trigger,
            ))
            trace_records.append(_trace_record(
                attempt=attempt,
                max_attempts=max_attempts,
                stage="write",
                status="ok",
                model=model,
                trigger=trigger,
                detail=normalized,
            ))
            _write_projection_logs(
                workspace,
                stamp=stamp,
                trace_records=trace_records,
                audit_payload={
                    "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "trigger": trigger,
                    "model": model,
                    "final_status": "accepted",
                    "final_reason": "",
                    "accepted_attempt": attempt,
                    "attempts": len({record["attempt"] for record in trace_records}),
                    "profile_stage": profile.get("relationship", {}).get("stage", ""),
                    "result": {
                        "soul_markdown": normalized,
                        "profile": profile,
                    },
                },
            )
            return normalized
        trace_records.append(_trace_record(
            attempt=attempt,
            max_attempts=max_attempts,
            stage="validation",
            status="rejected",
            model=model,
            trigger=trigger,
            reason=error,
            detail=candidate,
        ))
        last_output = candidate
        last_error = error

    _write_projection_logs(
        workspace,
        stamp=stamp,
        trace_records=trace_records,
        audit_payload={
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "trigger": trigger,
            "model": model,
            "final_status": "failed",
            "final_reason": last_error,
            "accepted_attempt": None,
            "attempts": len({record["attempt"] for record in trace_records}),
            "profile_stage": profile.get("relationship", {}).get("stage", ""),
            "result": {
                "soul_markdown": current_soul_text,
                "profile": profile,
            },
            "last_candidate": last_output,
        },
    )
    raise SoulProjectionError(last_error)


def validate_soul_markdown(text: str) -> str:
    """Validate projected SOUL markdown and return the rejection reason."""

    candidate = (text or "").strip()
    if not candidate:
        return "SOUL.md 投影候选非法: 内容为空"

    headings = re.findall(r"(?m)^# .+$", candidate)
    if headings != list(_ALLOWED_HEADINGS):
        return "SOUL.md 投影候选非法: 一级标题只能是 # 性格 和 # 初始关系，且顺序固定"

    if any(token in candidate for token in _FORBIDDEN_TEXT):
        return "SOUL.md 投影候选非法: 混入了治理或代码块内容"

    if "{" in candidate or "}" in candidate:
        return "SOUL.md 投影候选非法: 包含结构化对象内容"

    for pattern in _FORBIDDEN_STRUCTURED_PATTERNS:
        if re.search(pattern, candidate):
            return "SOUL.md 投影候选非法: 泄露了结构化字段"

    personality = _extract_section(candidate, "性格")
    relationship = _extract_section(candidate, "初始关系")
    if not personality or not relationship:
        return "SOUL.md 投影候选非法: 章节内容不能为空"

    return ""


def _build_projection_messages(
    *,
    profile_text: str,
    current_soul_text: str,
    core_anchor_text: str,
    soul_method_text: str,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": PROJECTION_PROMPT},
        {
            "role": "user",
            "content": (
                f"## 当前结构化 SOUL_PROFILE\n{profile_text}\n\n"
                f"## 当前 SOUL.md\n{current_soul_text or '（暂无，需从头生成）'}\n\n"
                f"## CORE_ANCHOR\n{core_anchor_text or '（暂无）'}\n\n"
                f"## SOUL 方法论\n{soul_method_text}\n\n"
                "请输出新的 SOUL.md。要求：\n"
                "1. 只保留长期慢状态画像，不要写热状态情绪。\n"
                "2. 语气自然、像人物自我画像，不要列表化。\n"
                "3. 关系描述必须是方法论约束下的自然语言推断，不能直接抄字段值。\n"
                "4. 必须只输出两个一级标题：# 性格、# 初始关系。\n"
            ),
        },
    ]


def _build_repair_messages(
    *,
    profile_text: str,
    current_soul_text: str,
    core_anchor_text: str,
    soul_method_text: str,
    previous_output: str,
    rejection_reason: str,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": REPAIR_PROMPT},
        {
            "role": "user",
            "content": (
                f"## 当前结构化 SOUL_PROFILE\n{profile_text}\n\n"
                f"## 当前 SOUL.md\n{current_soul_text or '（暂无，需从头生成）'}\n\n"
                f"## CORE_ANCHOR\n{core_anchor_text or '（暂无）'}\n\n"
                f"## SOUL 方法论\n{soul_method_text}\n\n"
                f"## 上一轮失败原因\n{rejection_reason}\n\n"
                f"## 上一轮非法候选\n{previous_output or '（空）'}\n\n"
                "请只输出修复后的 SOUL.md markdown。"
            ),
        },
    ]


def _extract_section(text: str, heading: str) -> str:
    pattern = re.compile(rf"(?ms)^# {re.escape(heading)}\s*\n(.*?)(?=^# |\Z)")
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def ensure_projectable_profile(
    profile: dict,
    *,
    error_cls: type[Exception] = ValueError,
) -> None:
    error = projectable_profile_error(profile)
    if error:
        raise error_cls(f"SOUL_PROFILE.md 内容非法，无法重建 SOUL.md: {error}")


def normalize_projectable_profile(
    profile: dict,
    *,
    error_cls: type[Exception] = ValueError,
) -> dict:
    if not isinstance(profile, dict):
        ensure_projectable_profile(profile, error_cls=error_cls)
        return profile

    normalized = deepcopy(profile)
    defaults = build_default_profile()
    defaults["personality"] = {key: 0.0 for key in _PERSONALITY_KEYS}
    for section in ("personality", "relationship", "companionship"):
        default_section = defaults.get(section)
        current_section = normalized.get(section)
        if current_section is None:
            normalized[section] = deepcopy(default_section)
            continue
        if isinstance(default_section, dict) and isinstance(current_section, dict):
            merged = deepcopy(default_section)
            merged.update(current_section)
            normalized[section] = merged

    ensure_projectable_profile(normalized, error_cls=error_cls)
    return normalized


def projectable_profile_error(profile: dict) -> str:
    if not isinstance(profile, dict):
        return "顶层结构必须是对象"

    expression = profile.get("expression")
    if expression is not None:
        if not isinstance(expression, dict):
            return "expression 必须是对象"
        for key in ("personality_seed", "relationship_seed"):
            if key in expression:
                error = _string_seed_error(f"expression.{key}", expression.get(key))
                if error:
                    return error

    personality = profile.get("personality")
    if not isinstance(personality, dict):
        return "personality 必须是对象"
    for key in _PERSONALITY_KEYS:
        error = _ratio_error(f"personality.{key}", personality.get(key))
        if error:
            return error

    relationship = profile.get("relationship")
    if not isinstance(relationship, dict):
        return "relationship 必须是对象"
    stage = relationship.get("stage")
    if not isinstance(stage, str) or stage not in RELATIONSHIP_STAGES:
        return f"relationship.stage 必须是有效阶段: {' / '.join(RELATIONSHIP_STAGES)}"
    for key in _RELATIONSHIP_KEYS:
        error = _ratio_error(f"relationship.{key}", relationship.get(key))
        if error:
            return error

    companionship = profile.get("companionship")
    if not isinstance(companionship, dict):
        return "companionship 必须是对象"
    for key in _COMPANIONSHIP_KEYS:
        error = _ratio_error(f"companionship.{key}", companionship.get(key))
        if error:
            return error

    return ""


def _ratio_error(field: str, value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"{field} 必须是 0.0-1.0 数值"
    numeric = float(value)
    if 0.0 <= numeric <= 1.0:
        return ""
    return f"{field} 必须在 0.0-1.0"


def _string_seed_error(field: str, value: object) -> str:
    if isinstance(value, str):
        return ""
    return f"{field} 必须是字符串"


def _project_personality_text(profile: dict, *, use_expression_seed: bool) -> str:
    expression = profile.get("expression") if isinstance(profile, dict) else {}
    if use_expression_seed and isinstance(expression, dict):
        personality_seed = str(expression.get("personality_seed") or "").strip()
        if personality_seed:
            return personality_seed

    personality = profile.get("personality") if isinstance(profile, dict) else {}
    if not isinstance(personality, dict):
        personality = {}

    dominant_functions = sorted(
        (
            (name, float(value))
            for name, value in personality.items()
            if isinstance(value, (int, float))
        ),
        key=lambda item: item[1],
        reverse=True,
    )[:2]
    dominant_traits = [
        _FUNCTION_TRAIT_TEXT[name]
        for name, _value in dominant_functions
        if name in _FUNCTION_TRAIT_TEXT
    ]
    if not dominant_traits:
        return "她的慢状态还在成形，但会稳定地守住自己的边界与节奏。"

    trait_text = "，".join(dominant_traits)
    return f"她的慢状态气质以{trait_text}为主，在靠近他人之前也会先确认自己的感受与边界。"


def _project_relationship_text(profile: dict, *, use_expression_seed: bool) -> str:
    expression = profile.get("expression") if isinstance(profile, dict) else {}
    if use_expression_seed and isinstance(expression, dict):
        relationship_seed = str(expression.get("relationship_seed") or "").strip()
        if relationship_seed:
            return relationship_seed

    relationship = profile.get("relationship") if isinstance(profile, dict) else {}
    if not isinstance(relationship, dict):
        relationship = {}

    stage = str(relationship.get("stage") or "").strip()
    stage_text = _RELATIONSHIP_STAGE_TEXT.get(
        stage,
        "她与用户的关系还在缓慢形成中，会一边观察、一边确认自己愿意靠近到什么程度。",
    )

    trust = float(relationship.get("trust", 0.0) or 0.0)
    boundary = float(relationship.get("boundary", 0.0) or 0.0)
    if trust >= 0.6:
        trust_text = "这种关系里已经有了比较稳定的信任感"
    elif trust >= 0.2:
        trust_text = "她对这段关系的信任正在慢慢累积"
    else:
        trust_text = "她对这段关系仍然保持谨慎试探"

    if boundary >= 0.8:
        boundary_text = "也会明确守住自己的边界"
    elif boundary >= 0.5:
        boundary_text = "同时会注意保留自己的分寸"
    else:
        boundary_text = "但边界感还需要继续稳定下来"

    return f"{stage_text}{trust_text}，{boundary_text}。"


def _read_optional_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _trace_record(
    *,
    attempt: int,
    max_attempts: int,
    stage: str,
    status: str,
    model: str,
    trigger: str,
    reason: str = "",
    detail: str = "",
) -> dict:
    return {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "attempt": attempt,
        "max_attempts": max_attempts,
        "stage": stage,
        "status": status,
        "reason": reason,
        "detail": detail,
        "model": model,
        "trigger": trigger,
    }


def _write_projection_logs(
    workspace: Path,
    *,
    stamp: str,
    trace_records: list[dict],
    audit_payload: dict,
) -> None:
    writer = SoulLogWriter(workspace)
    writer.write_projection_trace(stamp, trace_records)
    writer.write_projection_audit(stamp, audit_payload)
