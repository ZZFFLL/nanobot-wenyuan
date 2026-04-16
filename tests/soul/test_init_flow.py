"""Focused tests for SOUL init ordering and force-rebuild semantics."""

import json

from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.config.schema import Config
from nanobot.soul.profile import SoulProfileManager

runner = CliRunner()


def _profile(stage: str = "熟悉") -> dict:
    return {
        "personality": {
            "Fi": 0.82,
            "Fe": 0.28,
            "Ti": 0.16,
            "Te": 0.10,
            "Si": 0.42,
            "Se": 0.08,
            "Ni": 0.24,
            "Ne": 0.60,
        },
        "relationship": {
            "stage": stage,
            "trust": 0.12,
            "intimacy": 0.04,
            "attachment": 0.0,
            "security": 0.10,
            "boundary": 0.92,
            "affection": 0.0,
        },
        "companionship": {
            "empathy_fit": 0.22,
            "memory_fit": 0.02,
            "naturalness": 0.25,
            "initiative_quality": 0.0,
            "scene_awareness": 0.12,
            "boundary_expression": 0.90,
        },
    }


def _write_config(tmp_path):
    config = Config()
    workspace = tmp_path / "workspace"
    config.agents.defaults.workspace = str(workspace)
    config_path = tmp_path / "instance" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.model_dump(mode="json", by_alias=True), ensure_ascii=False),
        encoding="utf-8",
    )
    return config_path, workspace


def test_bootstrap_workspace_writes_profile_before_projected_soul(tmp_path, monkeypatch):
    from nanobot.soul.bootstrap import SoulInitPayload, bootstrap_workspace

    seen: list[str] = []
    original_write = SoulProfileManager.write

    def _track_profile_write(self, profile):
        seen.append("profile")
        return original_write(self, profile)

    def _project_from_profile(profile, **_kwargs):
        seen.append("project")
        assert (tmp_path / "SOUL_PROFILE.md").exists()
        assert profile["relationship"]["stage"] == "熟悉"
        assert _kwargs == {}
        return "# 性格\n\n投影后的性格。\n\n# 初始关系\n\n投影后的关系。\n"

    monkeypatch.setattr("nanobot.soul.bootstrap.SoulProfileManager.write", _track_profile_write)
    monkeypatch.setattr("nanobot.soul.bootstrap.project_initial_soul_markdown", _project_from_profile)

    bootstrap_workspace(
        tmp_path,
        SoulInitPayload(
            ai_name="温予安",
            gender="女",
            birthday="2026-04-01",
            personality="温柔但倔强",
            relationship="刚认识用户",
            user_name="阿峰",
            user_birthday="1990-01-01",
        ),
        profile_override=_profile(),
        soul_markdown_override="# 性格\n\n候选性格。\n\n# 初始关系\n\n候选关系。\n",
    )

    assert seen == ["profile", "project"]
    assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == (
        "# 性格\n\n投影后的性格。\n\n# 初始关系\n\n投影后的关系。\n"
    )


def test_bootstrap_workspace_persists_soul_only_from_profile(tmp_path):
    from nanobot.soul.bootstrap import SoulInitPayload, bootstrap_workspace
    from nanobot.soul.projection import project_initial_soul_markdown

    profile = _profile(stage="熟悉")
    bootstrap_workspace(
        tmp_path,
        SoulInitPayload(
            ai_name="温予安",
            gender="女",
            birthday="2026-04-01",
            personality="payload 性格文本",
            relationship="payload 关系文本",
            user_name="阿峰",
            user_birthday="1990-01-01",
        ),
        profile_override=profile,
        soul_markdown_override="# 性格\n\n候选性格。\n\n# 初始关系\n\n候选关系。\n",
    )

    assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == project_initial_soul_markdown(profile)


def test_soul_init_only_soul_force_fails_without_profile(tmp_path, monkeypatch):
    config_path, workspace = _write_config(tmp_path)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "SOUL.md").write_text(
        "# 性格\n\n旧性格。\n\n# 初始关系\n\n旧关系。\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: None)

    result = runner.invoke(
        app,
        ["soul", "init", "--config", str(config_path), "--only", "SOUL.md", "--force"],
    )

    assert result.exit_code == 2
    assert "SOUL_PROFILE.md" in result.stdout
    assert "不存在" in result.stdout


def test_write_selected_files_persists_soul_only_from_profile(tmp_path):
    from nanobot.soul.init_files import write_selected_files
    from nanobot.soul.bootstrap import SoulInitPayload
    from nanobot.soul.projection import project_initial_soul_markdown

    profile = _profile(stage="熟悉")
    write_selected_files(
        tmp_path,
        targets=["SOUL_PROFILE.md", "SOUL.md"],
        payload=SoulInitPayload(
            ai_name="温予安",
            gender="女",
            birthday="2026-04-01",
            personality="payload 性格文本",
            relationship="payload 关系文本",
            user_name="阿峰",
            user_birthday="1990-01-01",
        ),
        force=True,
        soul_markdown_override="# 性格\n\n候选性格。\n\n# 初始关系\n\n候选关系。\n",
        profile_override=profile,
    )

    assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == project_initial_soul_markdown(profile)


def test_soul_init_only_soul_force_rebuilds_from_existing_profile(tmp_path, monkeypatch):
    from nanobot.soul.projection import project_initial_soul_markdown

    config_path, workspace = _write_config(tmp_path)
    workspace.mkdir(parents=True, exist_ok=True)
    profile = _profile(stage="熟悉")
    SoulProfileManager(workspace).write(profile)
    (workspace / "SOUL.md").write_text(
        "# 性格\n\n旧性格。\n\n# 初始关系\n\n旧关系。\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: None)

    result = runner.invoke(
        app,
        ["soul", "init", "--config", str(config_path), "--only", "SOUL.md", "--force"],
    )

    assert result.exit_code == 0
    assert (workspace / "SOUL.md").read_text(encoding="utf-8") == project_initial_soul_markdown(profile)
