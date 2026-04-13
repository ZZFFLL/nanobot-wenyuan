"""Soul-specific configuration loaded from ~/.nanobot/soul.json.

This provides a dedicated configuration file for soul system constraints
that should be configurable without modifying the main nanobot config.json.

File location: ~/.nanobot/soul.json (same directory as config.json)

Placing soul.json alongside config.json (not in the workspace) ensures
that agent tools (edit_file, write_file) cannot modify constraint settings.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Base(BaseModel):
    """Base model that accepts both camelCase and snake_case keys."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ProactiveConstraintConfig(Base):
    """Hard constraints for proactive behavior — safety rails that LLM cannot override."""

    enabled: bool = True
    cooldown_s: int = Field(default=3600, ge=0, description="Min seconds between two proactive messages")
    quiet_hours_start: int = Field(default=2, ge=0, le=23, description="Quiet hours start hour (24h, inclusive)")
    quiet_hours_end: int = Field(default=7, ge=0, le=23, description="Quiet hours end hour (24h, exclusive)")
    min_interval_s: int = Field(default=900, ge=60, description="Shortest heartbeat check interval (seconds)")
    max_interval_s: int = Field(default=7200, ge=60, description="Longest heartbeat check interval (seconds)")
    idle_threshold_s: int = Field(
        default=43200, ge=0,
        description="Seconds of no interaction before forced proactive check",
    )


class ProactiveLlmConfig(Base):
    """LLM-specific config for proactive decision making."""

    model: str = ""             # Empty = use proactive_model from SoulConfig
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=500, ge=50)


class SoulJsonConfig(Base):
    """Root model for soul.json workspace configuration."""

    proactive: ProactiveConstraintConfig = Field(default_factory=ProactiveConstraintConfig)
    proactive_llm: ProactiveLlmConfig = Field(default_factory=ProactiveLlmConfig)


def load_soul_json() -> SoulJsonConfig:
    """Load soul.json from the nanobot config directory (~/.nanobot/soul.json).

    The file is placed alongside config.json so that agent tools cannot modify it.
    Returns defaults if file not found or invalid.
    """
    soul_json_path = _resolve_soul_json_path()
    if not soul_json_path.exists():
        logger.debug("soul.json not found at {}, using defaults", soul_json_path)
        return SoulJsonConfig()

    try:
        with open(soul_json_path, encoding="utf-8") as f:
            data = json.load(f)
        config = SoulJsonConfig.model_validate(data)
        logger.info("soul.json loaded from {}", soul_json_path)
        return config
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("soul.json parse error: {}, using defaults", e)
        return SoulJsonConfig()
    except Exception:
        logger.exception("soul.json load failed, using defaults")
        return SoulJsonConfig()


def save_soul_json(config: SoulJsonConfig) -> None:
    """Save soul.json to the nanobot config directory (~/.nanobot/soul.json)."""
    soul_json_path = _resolve_soul_json_path()
    soul_json_path.parent.mkdir(parents=True, exist_ok=True)
    data = config.model_dump(mode="json", by_alias=True, exclude_defaults=True)
    with open(soul_json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("soul.json saved to {}", soul_json_path)


def _resolve_soul_json_path() -> Path:
    """Resolve soul.json path: same directory as config.json."""
    from nanobot.config.loader import get_config_path
    return get_config_path().parent / "soul.json"
