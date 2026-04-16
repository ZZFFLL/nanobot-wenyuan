"""Tests for partial soul init file selection helpers."""

import pytest

from nanobot.soul.init_files import normalize_only_files, read_existing_seed


def test_normalize_only_files_orders_and_deduplicates():
    result = normalize_only_files(["SOUL_PROFILE.md", "AGENTS.md", "SOUL_GOVERNANCE.json", "SOUL_PROFILE.md"])

    assert result == ["AGENTS.md", "SOUL_GOVERNANCE.json", "SOUL_PROFILE.md"]


def test_normalize_only_files_rejects_unknown_file():
    with pytest.raises(ValueError, match="不支持的初始化文件"):
        normalize_only_files(["BAD_FILE.md"])


def test_read_existing_seed_does_not_reuse_existing_soul_text(tmp_path):
    (tmp_path / "SOUL.md").write_text(
        "# 性格\n\n旧性格描述。\n\n# 初始关系\n\n旧关系描述。\n",
        encoding="utf-8",
    )

    seed = read_existing_seed(tmp_path)

    assert seed["personality"] == ""
    assert seed["relationship"] == ""
