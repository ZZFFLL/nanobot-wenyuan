"""Methodology-level defaults for the soul system."""

from __future__ import annotations

from copy import deepcopy


RELATIONSHIP_STAGES = (
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
        "stage": "熟悉",
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


def build_default_profile() -> dict:
    """Return a deep-copied default soul profile."""

    return deepcopy(DEFAULT_SOUL_PROFILE)
