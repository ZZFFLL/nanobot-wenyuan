"""Tests for cyclical relationship state updates."""

import pytest

from nanobot.soul.profile import SoulProfileManager


def test_profile_manager_updates_relationship_state_with_deltas(tmp_path):
    manager = SoulProfileManager(tmp_path)

    relationship = manager.update_relationship(
        stage="亲近",
        dimension_deltas={
            "trust": 0.6,
            "intimacy": 0.3,
            "boundary": -0.2,
        },
    )

    assert relationship["stage"] == "亲近"
    assert relationship["trust"] == 0.6
    assert relationship["intimacy"] == 0.3
    assert relationship["boundary"] == 0.8


def test_profile_manager_rejects_unknown_relationship_stage(tmp_path):
    manager = SoulProfileManager(tmp_path)

    with pytest.raises(ValueError, match="未知关系阶段"):
        manager.update_relationship(stage="恋人", dimension_deltas={})
