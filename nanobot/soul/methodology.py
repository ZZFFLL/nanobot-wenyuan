"""Methodology-level defaults and rendered guidance for the soul system."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from importlib.resources import files as pkg_files
from pathlib import Path


RELATIONSHIP_STAGES = (
    "还不认识",
    "熟悉",
    "亲近",
    "依恋",
    "深度依恋",
    "喜欢",
    "爱意",
)

RELATIONSHIP_DIMENSIONS = (
    "trust",
    "intimacy",
    "attachment",
    "security",
    "boundary",
    "affection",
)

DEFAULT_SOUL_PROFILE = {
    "personality": {},
    "relationship": {
        "stage": "还不认识",
        "trust": 0.0,
        "intimacy": 0.0,
        "attachment": 0.0,
        "security": 0.0,
        "boundary": 1.0,
        "affection": 0.0,
    },
    "companionship": {
        "empathy_fit": 0.0,
        "memory_fit": 0.0,
        "naturalness": 0.0,
        "initiative_quality": 0.0,
        "scene_awareness": 0.0,
        "boundary_expression": 1.0,
    },
}

_FALLBACK_SOUL_GOVERNANCE = {
    "init": {
        "allowed_stages": ["还不认识", "熟悉"],
        "relationship_boundary_min": 0.5,
        "boundary_expression_min": 0.5,
        "require_profile_projection_for_soul": True,
        "allow_soul_only_without_profile": False,
        "allow_existing_soul_seed_for_init": False,
    }
}


@dataclass(slots=True, frozen=True)
class InitGovernance:
    """Workspace-configurable governance for ``soul init``."""

    allowed_stages: tuple[str, ...]
    relationship_boundary_min: float
    boundary_expression_min: float
    require_profile_projection_for_soul: bool
    allow_soul_only_without_profile: bool
    allow_existing_soul_seed_for_init: bool


def build_default_profile() -> dict:
    """Return a deep-copied default soul profile."""

    return deepcopy(DEFAULT_SOUL_PROFILE)


def build_default_soul_governance() -> dict:
    """Return the packaged default soul governance config."""

    return deepcopy(_load_bundled_soul_governance())


def render_soul_governance_json() -> str:
    """Render the authoritative ``SOUL_GOVERNANCE.json`` content."""

    return json.dumps(build_default_soul_governance(), ensure_ascii=False, indent=2) + "\n"


def load_soul_governance(workspace: Path | None = None) -> dict:
    """Load soul governance from workspace override or bundled defaults."""

    governance = build_default_soul_governance()
    if workspace is None:
        return governance

    path = workspace / "SOUL_GOVERNANCE.json"
    if not path.exists():
        return governance

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return governance

    if not isinstance(payload, dict):
        return governance

    init_payload = payload.get("init")
    if isinstance(init_payload, dict):
        governance["init"].update(init_payload)
    return governance


def load_init_governance(workspace: Path | None = None) -> InitGovernance:
    """Load validated init governance from config."""

    payload = load_soul_governance(workspace).get("init", {})
    allowed_stages_raw = payload.get("allowed_stages", [])
    allowed_stages = tuple(
        stage for stage in allowed_stages_raw
        if isinstance(stage, str) and stage in RELATIONSHIP_STAGES
    )
    if not allowed_stages:
        allowed_stages = tuple(_FALLBACK_SOUL_GOVERNANCE["init"]["allowed_stages"])

    return InitGovernance(
        allowed_stages=allowed_stages,
        relationship_boundary_min=_coerce_ratio(
            payload.get("relationship_boundary_min"),
            default=float(_FALLBACK_SOUL_GOVERNANCE["init"]["relationship_boundary_min"]),
        ),
        boundary_expression_min=_coerce_ratio(
            payload.get("boundary_expression_min"),
            default=float(_FALLBACK_SOUL_GOVERNANCE["init"]["boundary_expression_min"]),
        ),
        require_profile_projection_for_soul=_coerce_bool(
            payload.get("require_profile_projection_for_soul"),
            default=bool(_FALLBACK_SOUL_GOVERNANCE["init"]["require_profile_projection_for_soul"]),
        ),
        allow_soul_only_without_profile=_coerce_bool(
            payload.get("allow_soul_only_without_profile"),
            default=bool(_FALLBACK_SOUL_GOVERNANCE["init"]["allow_soul_only_without_profile"]),
        ),
        allow_existing_soul_seed_for_init=_coerce_bool(
            payload.get("allow_existing_soul_seed_for_init"),
            default=bool(_FALLBACK_SOUL_GOVERNANCE["init"]["allow_existing_soul_seed_for_init"]),
        ),
    )


def render_soul_method_markdown() -> str:
    """Render the authoritative ``SOUL_METHOD.md`` content."""

    stages = " -> ".join(RELATIONSHIP_STAGES)
    dimensions = " / ".join(RELATIONSHIP_DIMENSIONS)
    return (
        "# SOUL 方法论\n\n"
        "## 人格演化\n"
        "- 主轴: 荣格八维\n"
        "- 原则: 人格慢变，不能被单轮对话直接重写\n\n"
        "## 关系演化\n"
        f"- 关系维度: {dimensions}\n"
        f"- 关系阶段: {stages}\n"
        "- 原则: 关系支持升级、降级、修复，但必须按周期治理，不做即时跳变\n\n"
        "## 情绪演化\n"
        "- 模型: 事件 -> 感受 -> 脉络 -> 沉淀\n"
        "- 原则: 情绪快变，但仍受方法论边界约束\n\n"
        "## 陪伴能力\n"
        "- 维度: empathy_fit / memory_fit / naturalness / initiative_quality / scene_awareness / boundary_expression\n"
        "- 原则: 可提升也可退化，不直接改写核心锚点\n\n"
        "## 治理节奏\n"
        "- 周复盘\n"
        "- 月校准\n"
        "- 人工干预\n"
    )


def _load_bundled_soul_governance() -> dict:
    try:
        template = pkg_files("nanobot") / "templates" / "SOUL_GOVERNANCE.json"
        payload = json.loads(template.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return deepcopy(_FALLBACK_SOUL_GOVERNANCE)


def _coerce_ratio(value: object, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def _coerce_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default
