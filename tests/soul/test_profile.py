"""Tests for soul profile state management."""

from nanobot.soul.profile import SoulProfileManager


def test_profile_manager_roundtrip(tmp_path):
    manager = SoulProfileManager(tmp_path)
    profile = {
        "personality": {"Fi": 0.8, "Fe": 0.3},
        "relationship": {"stage": "亲近", "trust": 0.6},
        "companionship": {"empathy_fit": 0.5},
    }

    manager.write(profile)

    assert manager.read()["relationship"]["stage"] == "亲近"


def test_profile_manager_returns_default_profile_when_missing(tmp_path):
    manager = SoulProfileManager(tmp_path)

    profile = manager.read()

    assert profile["relationship"]["stage"] == "熟悉"
    assert "personality" in profile
    assert "companionship" in profile
