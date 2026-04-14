"""Tests for soul anchor state management."""

from nanobot.soul.anchor import AnchorManager


def test_anchor_manager_reads_core_anchor(tmp_path):
    anchor_file = tmp_path / "CORE_ANCHOR.md"
    anchor_file.write_text("# 核心锚点\n\n- 不无底线顺从\n", encoding="utf-8")

    manager = AnchorManager(tmp_path)

    assert "不无底线顺从" in manager.read_text()


def test_anchor_manager_returns_empty_when_missing(tmp_path):
    manager = AnchorManager(tmp_path)

    assert manager.read_text() == ""
