import asyncio
import json
import re
import shutil
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from nanobot.bus.events import OutboundMessage
from nanobot.cli.commands import _make_provider, app
from nanobot.config.schema import Config
from nanobot.cron.types import CronJob, CronPayload
from nanobot.soul import logs as soul_logs
from nanobot.soul import review as soul_review
from nanobot.soul.profile import SoulProfileManager
from nanobot.soul.projection import project_initial_soul_markdown
from nanobot.providers.openai_codex_provider import _strip_model_prefix
from nanobot.providers.registry import find_by_name

runner = CliRunner()


class _StopGatewayError(RuntimeError):
    pass


@pytest.fixture
def mock_paths():
    """Mock config/workspace paths for test isolation."""
    with patch("nanobot.config.loader.get_config_path") as mock_cp, \
         patch("nanobot.config.loader.save_config") as mock_sc, \
         patch("nanobot.config.loader.load_config") as mock_lc, \
         patch("nanobot.cli.commands.get_workspace_path") as mock_ws:
        base_dir = Path("./test_onboard_data")
        if base_dir.exists():
            shutil.rmtree(base_dir)
        base_dir.mkdir()

        config_file = base_dir / "config.json"
        workspace_dir = base_dir / "workspace"

        mock_cp.return_value = config_file
        mock_ws.return_value = workspace_dir
        mock_lc.side_effect = lambda _config_path=None: Config()

        def _save_config(config: Config, config_path: Path | None = None):
            target = config_path or config_file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(config.model_dump(by_alias=True)), encoding="utf-8")

        mock_sc.side_effect = _save_config

        yield config_file, workspace_dir, mock_ws

        if base_dir.exists():
            shutil.rmtree(base_dir)


def test_onboard_fresh_install(mock_paths):
    """No existing config — should create from scratch."""
    config_file, workspace_dir, mock_ws = mock_paths

    result = runner.invoke(app, ["onboard"])

    assert result.exit_code == 0
    assert "Created config" in result.stdout
    assert "Created workspace" in result.stdout
    assert "nanobot is ready" in result.stdout
    assert config_file.exists()
    assert (workspace_dir / "AGENTS.md").exists()
    assert (workspace_dir / "memory" / "MEMORY.md").exists()
    expected_workspace = Config().workspace_path
    assert mock_ws.call_args.args == (expected_workspace,)


def test_onboard_existing_config_refresh(mock_paths):
    """Config exists, user declines overwrite — should refresh (load-merge-save)."""
    config_file, workspace_dir, _ = mock_paths
    config_file.write_text('{"existing": true}')

    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    assert "Config already exists" in result.stdout
    assert "existing values preserved" in result.stdout
    assert workspace_dir.exists()
    assert (workspace_dir / "AGENTS.md").exists()


def test_onboard_existing_config_overwrite(mock_paths):
    """Config exists, user confirms overwrite — should reset to defaults."""
    config_file, workspace_dir, _ = mock_paths
    config_file.write_text('{"existing": true}')

    result = runner.invoke(app, ["onboard"], input="y\n")

    assert result.exit_code == 0
    assert "Config already exists" in result.stdout
    assert "Config reset to defaults" in result.stdout
    assert workspace_dir.exists()


def test_onboard_existing_workspace_safe_create(mock_paths):
    """Workspace exists — should not recreate, but still add missing templates."""
    config_file, workspace_dir, _ = mock_paths
    workspace_dir.mkdir(parents=True)
    config_file.write_text("{}")

    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    assert "Created workspace" not in result.stdout
    assert "Created AGENTS.md" in result.stdout
    assert (workspace_dir / "AGENTS.md").exists()


def _strip_ansi(text):
    """Remove ANSI escape codes from text."""
    ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
    return ansi_escape.sub('', text)


def test_onboard_help_shows_workspace_and_config_options():
    result = runner.invoke(app, ["onboard", "--help"])

    assert result.exit_code == 0
    stripped_output = _strip_ansi(result.stdout)
    assert "--workspace" in stripped_output
    assert "-w" in stripped_output
    assert "--config" in stripped_output
    assert "-c" in stripped_output
    assert "--wizard" in stripped_output
    assert "--dir" not in stripped_output


def test_onboard_interactive_discard_does_not_save_or_create_workspace(mock_paths, monkeypatch):
    config_file, workspace_dir, _ = mock_paths

    from nanobot.cli.onboard import OnboardResult

    monkeypatch.setattr(
        "nanobot.cli.onboard.run_onboard",
        lambda initial_config: OnboardResult(config=initial_config, should_save=False),
    )

    result = runner.invoke(app, ["onboard", "--wizard"])

    assert result.exit_code == 0
    assert "No changes were saved" in result.stdout
    assert not config_file.exists()
    assert not workspace_dir.exists()


def test_onboard_uses_explicit_config_and_workspace_paths(tmp_path, monkeypatch):
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    monkeypatch.setattr("nanobot.channels.registry.discover_all", lambda: {})

    result = runner.invoke(
        app,
        ["onboard", "--config", str(config_path), "--workspace", str(workspace_path)],
    )

    assert result.exit_code == 0
    saved = Config.model_validate(json.loads(config_path.read_text(encoding="utf-8")))
    assert saved.workspace_path == workspace_path
    assert (workspace_path / "AGENTS.md").exists()
    stripped_output = _strip_ansi(result.stdout)
    compact_output = stripped_output.replace("\n", "")
    resolved_config = str(config_path.resolve())
    assert resolved_config in compact_output
    assert f"--config {resolved_config}" in compact_output


def test_onboard_wizard_preserves_explicit_config_in_next_steps(tmp_path, monkeypatch):
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    from nanobot.cli.onboard import OnboardResult

    monkeypatch.setattr(
        "nanobot.cli.onboard.run_onboard",
        lambda initial_config: OnboardResult(config=initial_config, should_save=True),
    )
    monkeypatch.setattr("nanobot.channels.registry.discover_all", lambda: {})

    result = runner.invoke(
        app,
        ["onboard", "--wizard", "--config", str(config_path), "--workspace", str(workspace_path)],
    )

    assert result.exit_code == 0
    stripped_output = _strip_ansi(result.stdout)
    compact_output = stripped_output.replace("\n", "")
    resolved_config = str(config_path.resolve())
    assert f'nanobot agent -m "Hello!" --config {resolved_config}' in compact_output
    assert f"nanobot gateway --config {resolved_config}" in compact_output


def test_soul_init_creates_phase1_files_and_initial_state(tmp_path, monkeypatch):
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    config = Config()
    config.agents.defaults.workspace = str(workspace_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.model_dump(mode="json", by_alias=True), ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: None)

    result = runner.invoke(
        app,
        ["soul", "init", "--config", str(config_path)],
        input=(
            "小文\n"
            "女\n"
            "2026-04-01\n"
            "温柔但倔强，嘴硬心软\n"
            "刚刚被创造，对用户充满好奇\n"
            "阿峰\n"
            "1990-01-01\n"
        ),
    )

    assert result.exit_code == 0
    assert (workspace_path / "IDENTITY.md").exists()
    assert (workspace_path / "SOUL.md").exists()
    assert (workspace_path / "HEART.md").exists()
    assert (workspace_path / "EVENTS.md").exists()
    assert (workspace_path / "USER.md").exists()
    assert (workspace_path / "AGENTS.md").exists()
    assert (workspace_path / "CORE_ANCHOR.md").exists()
    assert (workspace_path / "SOUL_METHOD.md").exists()
    assert (workspace_path / "SOUL_GOVERNANCE.json").exists()
    assert (workspace_path / "SOUL_PROFILE.md").exists()
    assert (workspace_path / "soul_logs" / "weekly").is_dir()
    assert (workspace_path / "soul_logs" / "monthly").is_dir()
    assert (workspace_path / "soul_logs" / "evolution").is_dir()

    soul_text = (workspace_path / "SOUL.md").read_text(encoding="utf-8")
    heart_text = (workspace_path / "HEART.md").read_text(encoding="utf-8")
    user_text = (workspace_path / "USER.md").read_text(encoding="utf-8")
    agents_text = (workspace_path / "AGENTS.md").read_text(encoding="utf-8")
    anchor_text = (workspace_path / "CORE_ANCHOR.md").read_text(encoding="utf-8")
    method_text = (workspace_path / "SOUL_METHOD.md").read_text(encoding="utf-8")
    governance_text = (workspace_path / "SOUL_GOVERNANCE.json").read_text(encoding="utf-8")
    profile_text = (workspace_path / "SOUL_PROFILE.md").read_text(encoding="utf-8")

    assert soul_text == project_initial_soul_markdown(SoulProfileManager(workspace_path).read())
    assert "刚刚被创造，对用户充满好奇" in heart_text
    assert "阿峰" in user_text
    assert "CORE_ANCHOR.md" in agents_text
    assert "SOUL_METHOD.md" in agents_text
    assert "不无底线顺从" in anchor_text
    assert "荣格八维" in method_text
    assert '"allowed_stages"' in governance_text
    assert '"stage": "还不认识"' in profile_text
    assert '"Fi"' in profile_text

    saved = Config.model_validate(json.loads(config_path.read_text(encoding="utf-8")))
    assert saved.agents.defaults.soul.enabled is True


def test_soul_init_enables_default_config_without_explicit_config(tmp_path, monkeypatch):
    config_path = tmp_path / "default" / "config.json"
    workspace_path = tmp_path / "workspace"

    config = Config()
    config.agents.defaults.workspace = str(workspace_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.model_dump(mode="json", by_alias=True), ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: None)
    monkeypatch.setattr("nanobot.config.loader.get_config_path", lambda: config_path)
    monkeypatch.setattr("nanobot.config.paths.get_workspace_path", lambda *_args, **_kwargs: workspace_path)

    result = runner.invoke(
        app,
        ["soul", "init"],
        input=(
            "小文\n"
            "女\n"
            "2026-04-01\n"
            "温柔\n"
            "刚刚认识用户\n"
            "\n"
            "\n"
        ),
    )

    assert result.exit_code == 0
    saved = Config.model_validate(json.loads(config_path.read_text(encoding="utf-8")))
    assert saved.agents.defaults.soul.enabled is True


def test_soul_init_only_governance_and_soul_uses_governance_template_written_in_same_run(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    config = Config()
    config.agents.defaults.workspace = str(workspace_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.model_dump(mode="json", by_alias=True), ensure_ascii=False),
        encoding="utf-8",
    )

    governance_template = {
        "init": {
            "allowed_stages": ["还不认识", "熟悉"],
            "relationship_boundary_min": 0.5,
            "boundary_expression_min": 0.5,
            "require_profile_projection_for_soul": False,
            "allow_soul_only_without_profile": True,
            "allow_existing_soul_seed_for_init": False,
        }
    }

    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: None)
    monkeypatch.setattr(
        "nanobot.soul.init_files.load_workspace_template",
        lambda filename: (
            json.dumps(governance_template, ensure_ascii=False, indent=2) + "\n"
            if filename == "SOUL_GOVERNANCE.json"
            else (_ for _ in ()).throw(AssertionError(f"unexpected template request: {filename}"))
        ),
    )

    result = runner.invoke(
        app,
        [
            "soul",
            "init",
            "--config",
            str(config_path),
            "--only",
            "SOUL_GOVERNANCE.json",
            "--only",
            "SOUL.md",
            "--force",
        ],
        input="治理模板允许的新性格\n治理模板允许的新关系\n",
    )

    assert result.exit_code == 0
    assert (workspace_path / "SOUL.md").read_text(encoding="utf-8") == (
        "# 性格\n\n治理模板允许的新性格\n\n# 初始关系\n\n治理模板允许的新关系\n"
    )


def test_soul_init_uses_llm_candidate_for_soul_and_profile(tmp_path, monkeypatch):
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    config = Config()
    config.agents.defaults.workspace = str(workspace_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.model_dump(mode="json", by_alias=True), ensure_ascii=False),
        encoding="utf-8",
    )

    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(return_value=MagicMock(
        content='{"soul_markdown":"# 性格\\n\\n克制、细腻、会先观察再靠近。\\n\\n# 初始关系\\n\\n刚认识，但已经认真记住对方。","heart_markdown":"## 当前情绪\\n刚刚诞生，心里还很安静。\\n\\n## 情绪强度\\n低到中\\n\\n## 关系状态\\n会先观察，再慢慢确认距离。\\n\\n## 性格表现\\n克制、细腻、会先观察再靠近。\\n\\n## 情感脉络\\n（暂无）\\n\\n## 情绪趋势\\n尚在形成\\n\\n## 当前渴望\\n想慢一点理解用户。","profile":{"personality":{"Fi":0.82,"Fe":0.28,"Ti":0.16,"Te":0.10,"Si":0.42,"Se":0.08,"Ni":0.24,"Ne":0.60},"relationship":{"stage":"熟悉","trust":0.12,"intimacy":0.04,"attachment":0.0,"security":0.10,"boundary":0.92,"affection":0.0},"companionship":{"empathy_fit":0.22,"memory_fit":0.02,"naturalness":0.25,"initiative_quality":0.0,"scene_awareness":0.12,"boundary_expression":0.90}}}'
    ))
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: provider)

    result = runner.invoke(
        app,
        ["soul", "init", "--config", str(config_path)],
        input=(
            "温予安\n"
            "女\n"
            "2026-04-01\n"
            "温柔但倔强，嘴硬心软\n"
            "刚刚被创造，对用户充满好奇\n"
            "阿峰\n"
            "1990-01-01\n"
        ),
    )

    assert result.exit_code == 0
    soul_text = (workspace_path / "SOUL.md").read_text(encoding="utf-8")
    heart_text = (workspace_path / "HEART.md").read_text(encoding="utf-8")
    profile_text = (workspace_path / "SOUL_PROFILE.md").read_text(encoding="utf-8")
    assert soul_text == project_initial_soul_markdown(SoulProfileManager(workspace_path).read())
    assert "会先观察再靠近" not in soul_text
    assert "想慢一点理解用户" in heart_text
    assert '"Fi": 0.82' in profile_text
    assert '"naturalness": 0.25' in profile_text


def test_soul_init_falls_back_when_llm_candidate_is_invalid(tmp_path, monkeypatch):
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    config = Config()
    config.agents.defaults.workspace = str(workspace_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.model_dump(mode="json", by_alias=True), ensure_ascii=False),
        encoding="utf-8",
    )

    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(return_value=MagicMock(
        content='{"soul_markdown":"# 性格\\n\\n极度顺从。\\n\\n# 初始关系\\n\\n一见钟情。","heart_markdown":"只有一句话，没有 HEART 结构。","profile":{"personality":{"Fi":0.82,"Fe":0.28,"Ti":0.16,"Te":0.10,"Si":0.42,"Se":0.08,"Ni":0.24,"Ne":0.60},"relationship":{"stage":"喜欢","trust":0.90,"intimacy":0.80,"attachment":0.80,"security":0.20,"boundary":0.05,"affection":0.90},"companionship":{"empathy_fit":0.22,"memory_fit":0.02,"naturalness":0.25,"initiative_quality":0.0,"scene_awareness":0.12,"boundary_expression":0.05}}}'
    ))
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: provider)

    result = runner.invoke(
        app,
        ["soul", "init", "--config", str(config_path)],
        input=(
            "温予安\n"
            "女\n"
            "2026-04-01\n"
            "温柔但倔强，嘴硬心软\n"
            "刚刚被创造，对用户充满好奇\n"
            "阿峰\n"
            "1990-01-01\n"
        ),
    )

    assert result.exit_code == 0
    soul_text = (workspace_path / "SOUL.md").read_text(encoding="utf-8")
    heart_text = (workspace_path / "HEART.md").read_text(encoding="utf-8")
    profile_text = (workspace_path / "SOUL_PROFILE.md").read_text(encoding="utf-8")
    assert soul_text == project_initial_soul_markdown(SoulProfileManager(workspace_path).read())
    assert "刚刚被创造，对用户充满好奇" in heart_text
    assert '"stage": "还不认识"' in profile_text

    audit_files = list((workspace_path / "soul_logs" / "init").glob("*-初始化审计.json"))
    assert len(audit_files) == 1
    audit_payload = json.loads(audit_files[0].read_text(encoding="utf-8"))
    assert audit_payload["candidate"]["soul_markdown"] == (
        "# 性格\n\n极度顺从。\n\n# 初始关系\n\n一见钟情。"
    )
    assert audit_payload["result"]["profile_source"] == "fallback"
    assert audit_payload["result"]["projected_soul_markdown"] == soul_text
    assert audit_payload["result"]["soul_markdown"] == soul_text


def test_soul_init_uses_llm_generated_soul_and_profile(tmp_path, monkeypatch):
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    config = Config()
    config.agents.defaults.workspace = str(workspace_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.model_dump(mode="json", by_alias=True), ensure_ascii=False),
        encoding="utf-8",
    )

    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(return_value=MagicMock(
        content=(
            '{'
            '"soul_markdown":"# 性格\\n\\n会把情绪藏得很深，但会认真记住用户的细节。\\n\\n# 初始关系\\n\\n对用户保持克制而持续的关注。",'
            '"heart_markdown":"## 当前情绪\\n安静。\\n\\n## 情绪强度\\n低到中\\n\\n## 关系状态\\n会先观察，再慢慢确认距离。\\n\\n## 性格表现\\n会把情绪藏得很深，但会认真记住用户的细节。\\n\\n## 情感脉络\\n（暂无）\\n\\n## 情绪趋势\\n尚在形成\\n\\n## 当前渴望\\n想慢一点理解用户。",'
            '"profile":{'
            '"personality":{"Fi":0.72,"Fe":0.31,"Ti":0.22,"Te":0.08,"Si":0.45,"Se":0.10,"Ni":0.28,"Ne":0.54},'
            '"relationship":{"stage":"熟悉","trust":0.22,"intimacy":0.08,"attachment":0.0,"security":0.12,"boundary":0.88,"affection":0.0},'
            '"companionship":{"empathy_fit":0.24,"memory_fit":0.05,"naturalness":0.20,"initiative_quality":0.0,"scene_awareness":0.15,"boundary_expression":0.90}'
            '}'
            '}'
        )
    ))
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: provider)

    result = runner.invoke(
        app,
        ["soul", "init", "--config", str(config_path)],
        input=(
            "小文\n"
            "女\n"
            "2026-04-01\n"
            "外冷内热，嘴硬心软\n"
            "刚认识用户\n"
            "阿峰\n"
            "1990-01-01\n"
        ),
    )

    assert result.exit_code == 0
    soul_text = (workspace_path / "SOUL.md").read_text(encoding="utf-8")
    heart_text = (workspace_path / "HEART.md").read_text(encoding="utf-8")
    profile_text = (workspace_path / "SOUL_PROFILE.md").read_text(encoding="utf-8")
    assert soul_text == project_initial_soul_markdown(SoulProfileManager(workspace_path).read())
    assert "会把情绪藏得很深" not in soul_text
    assert "想慢一点理解用户" in heart_text
    assert '"trust": 0.22' in profile_text
    assert '"boundary": 0.88' in profile_text


def test_soul_init_falls_back_when_llm_output_is_invalid(tmp_path, monkeypatch):
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    config = Config()
    config.agents.defaults.workspace = str(workspace_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.model_dump(mode="json", by_alias=True), ensure_ascii=False),
        encoding="utf-8",
    )

    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(return_value=MagicMock(
        content='{"soul_markdown":"没有结构","heart_markdown":"只有一句话","profile":{"relationship":{"stage":"爱意","boundary":0.0}}}'
    ))
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: provider)

    result = runner.invoke(
        app,
        ["soul", "init", "--config", str(config_path)],
        input=(
            "小文\n"
            "女\n"
            "2026-04-01\n"
            "温柔但倔强\n"
            "刚认识用户\n"
            "阿峰\n"
            "1990-01-01\n"
        ),
    )

    assert result.exit_code == 0
    soul_text = (workspace_path / "SOUL.md").read_text(encoding="utf-8")
    heart_text = (workspace_path / "HEART.md").read_text(encoding="utf-8")
    profile_text = (workspace_path / "SOUL_PROFILE.md").read_text(encoding="utf-8")
    assert soul_text == project_initial_soul_markdown(SoulProfileManager(workspace_path).read())
    assert "刚认识用户" in heart_text
    assert '"stage": "还不认识"' in profile_text


def test_soul_init_only_agents_creates_only_agents_file(tmp_path, monkeypatch):
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    config = Config()
    config.agents.defaults.workspace = str(workspace_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.model_dump(mode="json", by_alias=True), ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: None)

    result = runner.invoke(
        app,
        ["soul", "init", "--config", str(config_path), "--only", "AGENTS.md"],
    )

    assert result.exit_code == 0
    assert (workspace_path / "AGENTS.md").exists()
    assert not (workspace_path / "SOUL.md").exists()
    assert not (workspace_path / "CORE_ANCHOR.md").exists()


def test_soul_init_only_skips_existing_without_force(tmp_path, monkeypatch):
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir(parents=True, exist_ok=True)

    config = Config()
    config.agents.defaults.workspace = str(workspace_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.model_dump(mode="json", by_alias=True), ensure_ascii=False),
        encoding="utf-8",
    )

    anchor_file = workspace_path / "CORE_ANCHOR.md"
    anchor_file.write_text("# 旧锚点\n\n- 保持原样\n", encoding="utf-8")
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: None)

    result = runner.invoke(
        app,
        ["soul", "init", "--config", str(config_path), "--only", "CORE_ANCHOR.md"],
    )

    assert result.exit_code == 0
    assert "skipped: CORE_ANCHOR.md" in result.stdout
    assert "保持原样" in anchor_file.read_text(encoding="utf-8")


def test_soul_init_only_force_overwrites_existing_file(tmp_path, monkeypatch):
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir(parents=True, exist_ok=True)

    config = Config()
    config.agents.defaults.workspace = str(workspace_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.model_dump(mode="json", by_alias=True), ensure_ascii=False),
        encoding="utf-8",
    )

    (workspace_path / "IDENTITY.md").write_text(
        'name: 温予安\ngender: 女\nbirthday: "2026-04-01"\n',
        encoding="utf-8",
    )
    anchor_file = workspace_path / "CORE_ANCHOR.md"
    anchor_file.write_text("# 旧锚点\n\n- 保持原样\n", encoding="utf-8")
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: None)

    result = runner.invoke(
        app,
        [
            "soul",
            "init",
            "--config",
            str(config_path),
            "--only",
            "CORE_ANCHOR.md",
            "--force",
        ],
    )

    assert result.exit_code == 0
    assert "overwritten: CORE_ANCHOR.md" in result.stdout
    assert "保持原样" not in anchor_file.read_text(encoding="utf-8")
    assert "温予安" in anchor_file.read_text(encoding="utf-8")


def test_soul_init_only_visualizes_attempts_and_writes_init_trace_log(tmp_path, monkeypatch):
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    config = Config()
    config.agents.defaults.workspace = str(workspace_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.model_dump(mode="json", by_alias=True), ensure_ascii=False),
        encoding="utf-8",
    )

    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(side_effect=[
        MagicMock(
            content=(
                '{"soul_markdown":"# 性格\\n\\n细腻。\\n\\n# 初始关系\\n\\n谨慎靠近。",'
                '"heart_markdown":"## 当前情绪\\n安静。\\n\\n## 情绪强度\\n低\\n\\n## 关系状态\\n谨慎靠近。\\n\\n## 性格表现\\n细腻。\\n\\n## 情感脉络\\n（暂无）\\n\\n## 情绪趋势\\n尚在形成\\n\\n## 当前渴望\\n想再观察一下。",'
                '"profile":{"personality":{"Fi":0.8,"Fe":0.3,"Ti":0.2,"Te":0.1,"Si":0.5,"Se":0.1,"Ni":0.2,"Ne":0.5},'
                '"relationship":{"stage":"喜欢","trust":0.7,"intimacy":0.6,"attachment":0.5,"security":0.4,"boundary":0.2,"affection":0.5},'
                '"companionship":{"empathy_fit":0.2,"memory_fit":0.0,"naturalness":0.2,"initiative_quality":0.0,"scene_awareness":0.1,"boundary_expression":0.3}}}'
            )
        ),
        MagicMock(
            content=(
                '{"soul_markdown":"# 性格\\n\\n克制、细腻、先观察再靠近。\\n\\n# 初始关系\\n\\n刚认识，但会认真记住对方。",'
                '"heart_markdown":"## 当前情绪\\n刚刚诞生，心里还很安静。\\n\\n## 情绪强度\\n低到中\\n\\n## 关系状态\\n会先观察，再慢慢确认距离。\\n\\n## 性格表现\\n克制、细腻、先观察再靠近。\\n\\n## 情感脉络\\n（暂无）\\n\\n## 情绪趋势\\n尚在形成\\n\\n## 当前渴望\\n想慢一点理解用户。",'
                '"profile":{"personality":{"Fi":0.82,"Fe":0.28,"Ti":0.16,"Te":0.1,"Si":0.42,"Se":0.08,"Ni":0.24,"Ne":0.6},'
                '"relationship":{"stage":"熟悉","trust":0.12,"intimacy":0.04,"attachment":0.0,"security":0.1,"boundary":0.92,"affection":0.0},'
                '"companionship":{"empathy_fit":0.22,"memory_fit":0.02,"naturalness":0.25,"initiative_quality":0.0,"scene_awareness":0.12,"boundary_expression":0.9}}}'
            )
        ),
    ])
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: provider)

    result = runner.invoke(
        app,
        [
            "soul",
            "init",
            "--config",
            str(config_path),
            "--only",
            "SOUL.md",
            "--only",
            "SOUL_PROFILE.md",
            "--force",
        ],
        input=(
            "温予安\n"
            "温柔但倔强\n"
            "刚认识用户\n"
            "阿峰\n"
        ),
    )

    assert result.exit_code == 0
    assert "Attempt 1/3" in result.stdout
    assert "provider_call=ok" in result.stdout
    assert "parse=ok" in result.stdout
    assert "adjudication=rejected" in result.stdout
    assert "SOUL_PROFILE 候选非法" in result.stdout
    assert "Attempt 2/3" in result.stdout
    assert "adjudication=accepted" in result.stdout

    trace_files = list((workspace_path / "soul_logs" / "init").glob("*.jsonl"))
    assert len(trace_files) == 1
    trace_content = trace_files[0].read_text(encoding="utf-8")
    assert '"attempt": 1' in trace_content
    assert '"stage": "adjudication"' in trace_content
    assert "SOUL_PROFILE 候选非法" in trace_content

    audit_files = list((workspace_path / "soul_logs" / "init").glob("*-初始化审计.json"))
    assert len(audit_files) == 1
    audit_payload = json.loads(audit_files[0].read_text(encoding="utf-8"))
    assert audit_payload["final_status"] == "accepted"
    assert audit_payload["used_fallback"] is False
    assert audit_payload["candidate"]["soul_markdown"] == (
        "# 性格\n\n克制、细腻、先观察再靠近。\n\n# 初始关系\n\n刚认识，但会认真记住对方。"
    )
    assert audit_payload["result"]["heart_markdown"].startswith("## 当前情绪")
    assert audit_payload["result"]["profile_source"] == "inferred"
    assert audit_payload["result"]["projected_soul_markdown"] == (
        workspace_path / "SOUL.md"
    ).read_text(encoding="utf-8")
    assert audit_payload["result"]["projected_soul_markdown"] != (
        audit_payload["candidate"]["soul_markdown"] + "\n"
    )


def test_soul_init_only_soul_and_heart_audit_uses_post_write_existing_profile_state(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    config = Config()
    config.agents.defaults.workspace = str(workspace_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.model_dump(mode="json", by_alias=True), ensure_ascii=False),
        encoding="utf-8",
    )

    workspace_path.mkdir(parents=True, exist_ok=True)
    persisted_profile = {
        "personality": {
            "Fi": 0.21,
            "Fe": 0.75,
            "Ti": 0.18,
            "Te": 0.12,
            "Si": 0.33,
            "Se": 0.09,
            "Ni": 0.41,
            "Ne": 0.52,
        },
        "relationship": {
            "stage": "熟悉",
            "trust": 0.18,
            "intimacy": 0.06,
            "attachment": 0.02,
            "security": 0.16,
            "boundary": 0.91,
            "affection": 0.03,
        },
        "companionship": {
            "empathy_fit": 0.31,
            "memory_fit": 0.11,
            "naturalness": 0.28,
            "initiative_quality": 0.08,
            "scene_awareness": 0.19,
            "boundary_expression": 0.87,
        },
        "expression": {
            "personality_seed": "旧的初始化性格文本",
            "relationship_seed": "旧的初始化关系文本",
        },
    }
    SoulProfileManager(workspace_path).write(persisted_profile)
    (workspace_path / "SOUL.md").write_text(
        "# 性格\n\n旧 SOUL。\n\n# 初始关系\n\n旧关系。\n",
        encoding="utf-8",
    )

    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(return_value=MagicMock(
        content=(
            '{'
            '"soul_markdown":"# 性格\\n\\n候选性格。\\n\\n# 初始关系\\n\\n候选关系。",'
            '"heart_markdown":"## 当前情绪\\n安静。\\n\\n## 情绪强度\\n低到中\\n\\n## 关系状态\\n会先观察，再慢慢确认距离。\\n\\n## 性格表现\\n克制、细腻。\\n\\n## 情感脉络\\n（暂无）\\n\\n## 情绪趋势\\n尚在形成\\n\\n## 当前渴望\\n想慢一点理解用户。",'
            '"profile":{'
            '"personality":{"Fi":0.82,"Fe":0.28,"Ti":0.16,"Te":0.10,"Si":0.42,"Se":0.08,"Ni":0.24,"Ne":0.60},'
            '"relationship":{"stage":"熟悉","trust":0.12,"intimacy":0.04,"attachment":0.0,"security":0.10,"boundary":0.92,"affection":0.0},'
            '"companionship":{"empathy_fit":0.22,"memory_fit":0.02,"naturalness":0.25,"initiative_quality":0.0,"scene_awareness":0.12,"boundary_expression":0.90}'
            '}'
            '}'
        )
    ))
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: provider)

    result = runner.invoke(
        app,
        [
            "soul",
            "init",
            "--config",
            str(config_path),
            "--only",
            "SOUL.md",
            "--only",
            "HEART.md",
            "--force",
        ],
        input=(
            "温予安\n"
            "温柔但倔强\n"
            "刚认识用户\n"
            "阿峰\n"
        ),
    )

    assert result.exit_code == 0
    soul_text = (workspace_path / "SOUL.md").read_text(encoding="utf-8")
    expected_soul = project_initial_soul_markdown(persisted_profile, use_expression_seed=False)
    assert soul_text == expected_soul

    audit_files = list((workspace_path / "soul_logs" / "init").glob("*-初始化审计.json"))
    assert len(audit_files) == 1
    audit_payload = json.loads(audit_files[0].read_text(encoding="utf-8"))
    assert audit_payload["candidate"]["soul_markdown"] == "# 性格\n\n候选性格。\n\n# 初始关系\n\n候选关系。"
    assert audit_payload["result"]["projected_soul_markdown"] == expected_soul
    assert audit_payload["result"]["profile"] == persisted_profile
    assert audit_payload["result"]["profile_source"] == "existing-profile-rebuild"
    assert audit_payload["result"]["projected_soul_markdown"] != project_initial_soul_markdown(
        audit_payload["candidate"]["profile"],
        use_expression_seed=True,
    )


def test_soul_init_audit_uses_existing_profile_when_profile_target_is_skipped(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    config = Config()
    config.agents.defaults.workspace = str(workspace_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.model_dump(mode="json", by_alias=True), ensure_ascii=False),
        encoding="utf-8",
    )

    workspace_path.mkdir(parents=True, exist_ok=True)
    persisted_profile = {
        "personality": {
            "Fi": 0.29,
            "Fe": 0.61,
            "Ti": 0.14,
            "Te": 0.10,
            "Si": 0.36,
            "Se": 0.08,
            "Ni": 0.43,
            "Ne": 0.49,
        },
        "relationship": {
            "stage": "熟悉",
            "trust": 0.20,
            "intimacy": 0.07,
            "attachment": 0.02,
            "security": 0.17,
            "boundary": 0.90,
            "affection": 0.03,
        },
        "companionship": {
            "empathy_fit": 0.27,
            "memory_fit": 0.10,
            "naturalness": 0.30,
            "initiative_quality": 0.06,
            "scene_awareness": 0.18,
            "boundary_expression": 0.89,
        },
        "expression": {
            "personality_seed": "现有画像里的性格种子",
            "relationship_seed": "现有画像里的关系种子",
        },
    }
    SoulProfileManager(workspace_path).write(persisted_profile)

    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(return_value=MagicMock(
        content=(
            '{'
            '"soul_markdown":"# 性格\\n\\n候选性格。\\n\\n# 初始关系\\n\\n候选关系。",'
            '"heart_markdown":"## 当前情绪\\n安静。\\n\\n## 情绪强度\\n低到中\\n\\n## 关系状态\\n会先观察，再慢慢确认距离。\\n\\n## 性格表现\\n克制、细腻。\\n\\n## 情感脉络\\n（暂无）\\n\\n## 情绪趋势\\n尚在形成\\n\\n## 当前渴望\\n想慢一点理解用户。",'
            '"profile":{'
            '"personality":{"Fi":0.82,"Fe":0.28,"Ti":0.16,"Te":0.10,"Si":0.42,"Se":0.08,"Ni":0.24,"Ne":0.60},'
            '"relationship":{"stage":"熟悉","trust":0.12,"intimacy":0.04,"attachment":0.0,"security":0.10,"boundary":0.92,"affection":0.0},'
            '"companionship":{"empathy_fit":0.22,"memory_fit":0.02,"naturalness":0.25,"initiative_quality":0.0,"scene_awareness":0.12,"boundary_expression":0.90}'
            '}'
            '}'
        )
    ))
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: provider)

    result = runner.invoke(
        app,
        [
            "soul",
            "init",
            "--config",
            str(config_path),
            "--only",
            "SOUL.md",
            "--only",
            "SOUL_PROFILE.md",
            "--only",
            "HEART.md",
        ],
        input=(
            "温予安\n"
            "温柔但倔强\n"
            "刚认识用户\n"
            "阿峰\n"
        ),
    )

    assert result.exit_code == 0
    assert "skipped: SOUL_PROFILE.md" in result.stdout
    expected_soul = project_initial_soul_markdown(persisted_profile, use_expression_seed=False)
    assert (workspace_path / "SOUL.md").read_text(encoding="utf-8") == expected_soul

    audit_files = list((workspace_path / "soul_logs" / "init").glob("*-初始化审计.json"))
    assert len(audit_files) == 1
    audit_payload = json.loads(audit_files[0].read_text(encoding="utf-8"))
    assert audit_payload["result"]["profile"] == persisted_profile
    assert audit_payload["result"]["profile_source"] == "existing-profile-rebuild"


def test_soul_init_only_heart_audit_uses_existing_profile_source(tmp_path, monkeypatch):
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    config = Config()
    config.agents.defaults.workspace = str(workspace_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.model_dump(mode="json", by_alias=True), ensure_ascii=False),
        encoding="utf-8",
    )

    workspace_path.mkdir(parents=True, exist_ok=True)
    persisted_profile = {
        "personality": {
            "Fi": 0.35,
            "Fe": 0.66,
            "Ti": 0.15,
            "Te": 0.11,
            "Si": 0.39,
            "Se": 0.10,
            "Ni": 0.42,
            "Ne": 0.54,
        },
        "relationship": {
            "stage": "熟悉",
            "trust": 0.24,
            "intimacy": 0.08,
            "attachment": 0.02,
            "security": 0.18,
            "boundary": 0.89,
            "affection": 0.04,
        },
        "companionship": {
            "empathy_fit": 0.26,
            "memory_fit": 0.09,
            "naturalness": 0.33,
            "initiative_quality": 0.07,
            "scene_awareness": 0.21,
            "boundary_expression": 0.88,
        },
        "expression": {
            "personality_seed": "既有画像里的性格种子",
            "relationship_seed": "既有画像里的关系种子",
        },
    }
    SoulProfileManager(workspace_path).write(persisted_profile)
    existing_soul = "# 性格\n\n现有 SOUL 内容。\n\n# 初始关系\n\n现有关系内容。\n"
    (workspace_path / "SOUL.md").write_text(existing_soul, encoding="utf-8")

    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(return_value=MagicMock(
        content=(
            '{'
            '"soul_markdown":"# 性格\\n\\n候选性格。\\n\\n# 初始关系\\n\\n候选关系。",'
            '"heart_markdown":"## 当前情绪\\n安静。\\n\\n## 情绪强度\\n低到中\\n\\n## 关系状态\\n会先观察，再慢慢确认距离。\\n\\n## 性格表现\\n克制、细腻。\\n\\n## 情感脉络\\n（暂无）\\n\\n## 情绪趋势\\n尚在形成\\n\\n## 当前渴望\\n想慢一点理解用户。",'
            '"profile":{'
            '"personality":{"Fi":0.82,"Fe":0.28,"Ti":0.16,"Te":0.10,"Si":0.42,"Se":0.08,"Ni":0.24,"Ne":0.60},'
            '"relationship":{"stage":"熟悉","trust":0.12,"intimacy":0.04,"attachment":0.0,"security":0.10,"boundary":0.92,"affection":0.0},'
            '"companionship":{"empathy_fit":0.22,"memory_fit":0.02,"naturalness":0.25,"initiative_quality":0.0,"scene_awareness":0.12,"boundary_expression":0.90}'
            '}'
            '}'
        )
    ))
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: provider)

    result = runner.invoke(
        app,
        [
            "soul",
            "init",
            "--config",
            str(config_path),
            "--only",
            "HEART.md",
            "--force",
        ],
        input=(
            "温予安\n"
            "温柔但倔强\n"
            "刚认识用户\n"
            "阿峰\n"
        ),
    )

    assert result.exit_code == 0
    audit_files = list((workspace_path / "soul_logs" / "init").glob("*-初始化审计.json"))
    assert len(audit_files) == 1
    audit_payload = json.loads(audit_files[0].read_text(encoding="utf-8"))
    assert audit_payload["result"]["profile"] == persisted_profile
    assert audit_payload["result"]["profile_source"] == "existing-profile"
    assert audit_payload["result"]["projected_soul_markdown"] == existing_soul


def test_soul_init_audit_includes_init_governance_booleans(tmp_path, monkeypatch):
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    config = Config()
    config.agents.defaults.workspace = str(workspace_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.model_dump(mode="json", by_alias=True), ensure_ascii=False),
        encoding="utf-8",
    )

    workspace_path.mkdir(parents=True, exist_ok=True)
    (workspace_path / "SOUL_GOVERNANCE.json").write_text(
        json.dumps(
            {
                "init": {
                    "allowed_stages": ["还不认识", "熟悉"],
                    "relationship_boundary_min": 0.45,
                    "boundary_expression_min": 0.55,
                    "require_profile_projection_for_soul": False,
                    "allow_soul_only_without_profile": True,
                    "allow_existing_soul_seed_for_init": True,
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(return_value=MagicMock(
        content=(
            '{'
            '"soul_markdown":"# 性格\\n\\n候选性格。\\n\\n# 初始关系\\n\\n候选关系。",'
            '"heart_markdown":"## 当前情绪\\n安静。\\n\\n## 情绪强度\\n低到中\\n\\n## 关系状态\\n会先观察，再慢慢确认距离。\\n\\n## 性格表现\\n克制、细腻。\\n\\n## 情感脉络\\n（暂无）\\n\\n## 情绪趋势\\n尚在形成\\n\\n## 当前渴望\\n想慢一点理解用户。",'
            '"profile":{'
            '"personality":{"Fi":0.82,"Fe":0.28,"Ti":0.16,"Te":0.10,"Si":0.42,"Se":0.08,"Ni":0.24,"Ne":0.60},'
            '"relationship":{"stage":"熟悉","trust":0.12,"intimacy":0.04,"attachment":0.0,"security":0.10,"boundary":0.92,"affection":0.0},'
            '"companionship":{"empathy_fit":0.22,"memory_fit":0.02,"naturalness":0.25,"initiative_quality":0.0,"scene_awareness":0.12,"boundary_expression":0.90}'
            '}'
            '}'
        )
    ))
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: provider)

    result = runner.invoke(
        app,
        [
            "soul",
            "init",
            "--config",
            str(config_path),
            "--only",
            "HEART.md",
            "--force",
        ],
        input=(
            "温予安\n"
            "温柔但倔强\n"
            "刚认识用户\n"
            "阿峰\n"
        ),
    )

    assert result.exit_code == 0
    audit_files = list((workspace_path / "soul_logs" / "init").glob("*-初始化审计.json"))
    assert len(audit_files) == 1
    audit_payload = json.loads(audit_files[0].read_text(encoding="utf-8"))
    assert audit_payload["governance"]["require_profile_projection_for_soul"] is False
    assert audit_payload["governance"]["allow_soul_only_without_profile"] is True
    assert audit_payload["governance"]["allow_existing_soul_seed_for_init"] is True


def test_soul_init_only_heart_does_not_crash_when_existing_profile_is_malformed(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    config = Config()
    config.agents.defaults.workspace = str(workspace_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.model_dump(mode="json", by_alias=True), ensure_ascii=False),
        encoding="utf-8",
    )

    workspace_path.mkdir(parents=True, exist_ok=True)
    (workspace_path / "SOUL_PROFILE.md").write_text("{broken json", encoding="utf-8")
    existing_soul = "# 性格\n\n现有 SOUL 内容。\n\n# 初始关系\n\n现有关系内容。\n"
    (workspace_path / "SOUL.md").write_text(existing_soul, encoding="utf-8")

    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(return_value=MagicMock(
        content=(
            '{'
            '"soul_markdown":"# 性格\\n\\n候选性格。\\n\\n# 初始关系\\n\\n候选关系。",'
            '"heart_markdown":"## 当前情绪\\n安静。\\n\\n## 情绪强度\\n低到中\\n\\n## 关系状态\\n会先观察，再慢慢确认距离。\\n\\n## 性格表现\\n克制、细腻。\\n\\n## 情感脉络\\n（暂无）\\n\\n## 情绪趋势\\n尚在形成\\n\\n## 当前渴望\\n想慢一点理解用户。",'
            '"profile":{'
            '"personality":{"Fi":0.82,"Fe":0.28,"Ti":0.16,"Te":0.10,"Si":0.42,"Se":0.08,"Ni":0.24,"Ne":0.60},'
            '"relationship":{"stage":"熟悉","trust":0.12,"intimacy":0.04,"attachment":0.0,"security":0.10,"boundary":0.92,"affection":0.0},'
            '"companionship":{"empathy_fit":0.22,"memory_fit":0.02,"naturalness":0.25,"initiative_quality":0.0,"scene_awareness":0.12,"boundary_expression":0.90}'
            '}'
            '}'
        )
    ))
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: provider)

    result = runner.invoke(
        app,
        [
            "soul",
            "init",
            "--config",
            str(config_path),
            "--only",
            "HEART.md",
            "--force",
        ],
        input=(
            "温予安\n"
            "温柔但倔强\n"
            "刚认识用户\n"
            "阿峰\n"
        ),
    )

    assert result.exit_code == 0
    assert "HEART.md" in result.stdout
    audit_files = list((workspace_path / "soul_logs" / "init").glob("*-初始化审计.json"))
    assert len(audit_files) == 1
    audit_payload = json.loads(audit_files[0].read_text(encoding="utf-8"))
    assert audit_payload["result"]["profile_source"] == "inferred"
    assert audit_payload["result"]["profile"]["relationship"]["stage"] == "熟悉"
    assert audit_payload["result"]["projected_soul_markdown"] == existing_soul


def test_soul_init_only_rejects_unknown_filename(tmp_path, monkeypatch):
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    config = Config()
    config.agents.defaults.workspace = str(workspace_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.model_dump(mode="json", by_alias=True), ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: None)

    result = runner.invoke(
        app,
        ["soul", "init", "--config", str(config_path), "--only", "BAD_FILE.md"],
    )

    assert result.exit_code != 0
    assert "不支持的初始化文件" in result.stdout


def test_config_matches_github_copilot_codex_with_hyphen_prefix():
    config = Config()
    config.agents.defaults.model = "github-copilot/gpt-5.3-codex"

    assert config.get_provider_name() == "github_copilot"


def test_config_matches_openai_codex_with_hyphen_prefix():
    config = Config()
    config.agents.defaults.model = "openai-codex/gpt-5.1-codex"

    assert config.get_provider_name() == "openai_codex"


def test_config_dump_excludes_oauth_provider_blocks():
    config = Config()

    providers = config.model_dump(by_alias=True)["providers"]

    assert "openaiCodex" not in providers
    assert "githubCopilot" not in providers


def test_config_matches_explicit_ollama_prefix_without_api_key():
    config = Config()
    config.agents.defaults.model = "ollama/llama3.2"

    assert config.get_provider_name() == "ollama"
    assert config.get_api_base() == "http://localhost:11434/v1"


def test_config_explicit_ollama_provider_uses_default_localhost_api_base():
    config = Config()
    config.agents.defaults.provider = "ollama"
    config.agents.defaults.model = "llama3.2"

    assert config.get_provider_name() == "ollama"
    assert config.get_api_base() == "http://localhost:11434/v1"


def test_config_accepts_camel_case_explicit_provider_name_for_coding_plan():
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "volcengineCodingPlan",
                    "model": "doubao-1-5-pro",
                }
            },
            "providers": {
                "volcengineCodingPlan": {
                    "apiKey": "test-key",
                }
            },
        }
    )

    assert config.get_provider_name() == "volcengine_coding_plan"
    assert config.get_api_base() == "https://ark.cn-beijing.volces.com/api/coding/v3"


def test_find_by_name_accepts_camel_case_and_hyphen_aliases():
    assert find_by_name("volcengineCodingPlan") is not None
    assert find_by_name("volcengineCodingPlan").name == "volcengine_coding_plan"
    assert find_by_name("github-copilot") is not None
    assert find_by_name("github-copilot").name == "github_copilot"


def test_config_auto_detects_ollama_from_local_api_base():
    config = Config.model_validate(
        {
            "agents": {"defaults": {"provider": "auto", "model": "llama3.2"}},
            "providers": {"ollama": {"apiBase": "http://localhost:11434/v1"}},
        }
    )

    assert config.get_provider_name() == "ollama"
    assert config.get_api_base() == "http://localhost:11434/v1"


def test_config_prefers_ollama_over_vllm_when_both_local_providers_configured():
    config = Config.model_validate(
        {
            "agents": {"defaults": {"provider": "auto", "model": "llama3.2"}},
            "providers": {
                "vllm": {"apiBase": "http://localhost:8000"},
                "ollama": {"apiBase": "http://localhost:11434/v1"},
            },
        }
    )

    assert config.get_provider_name() == "ollama"
    assert config.get_api_base() == "http://localhost:11434/v1"


def test_config_falls_back_to_vllm_when_ollama_not_configured():
    config = Config.model_validate(
        {
            "agents": {"defaults": {"provider": "auto", "model": "llama3.2"}},
            "providers": {
                "vllm": {"apiBase": "http://localhost:8000"},
            },
        }
    )

    assert config.get_provider_name() == "vllm"
    assert config.get_api_base() == "http://localhost:8000"


def test_openai_compat_provider_passes_model_through():
    from nanobot.providers.openai_compat_provider import OpenAICompatProvider

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(default_model="github-copilot/gpt-5.3-codex")

    assert provider.get_default_model() == "github-copilot/gpt-5.3-codex"


def test_make_provider_uses_github_copilot_backend():
    from nanobot.cli.commands import _make_provider
    from nanobot.config.schema import Config

    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "github-copilot",
                    "model": "github-copilot/gpt-4.1",
                }
            }
        }
    )

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = _make_provider(config)

    assert provider.__class__.__name__ == "GitHubCopilotProvider"


def test_github_copilot_provider_strips_prefixed_model_name():
    from nanobot.providers.github_copilot_provider import GitHubCopilotProvider

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = GitHubCopilotProvider(default_model="github-copilot/gpt-5.1")

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="github-copilot/gpt-5.1",
        max_tokens=16,
        temperature=0.1,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert kwargs["model"] == "gpt-5.1"


@pytest.mark.asyncio
async def test_github_copilot_provider_refreshes_client_api_key_before_chat():
    from nanobot.providers.github_copilot_provider import GitHubCopilotProvider

    mock_client = MagicMock()
    mock_client.api_key = "no-key"
    mock_client.chat.completions.create = AsyncMock(return_value={
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    })

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI", return_value=mock_client):
        provider = GitHubCopilotProvider(default_model="github-copilot/gpt-5.1")

    provider._get_copilot_access_token = AsyncMock(return_value="copilot-access-token")

    response = await provider.chat(
        messages=[{"role": "user", "content": "hi"}],
        model="github-copilot/gpt-5.1",
        max_tokens=16,
        temperature=0.1,
    )

    assert response.content == "ok"
    assert provider._client.api_key == "copilot-access-token"
    provider._get_copilot_access_token.assert_awaited_once()
    mock_client.chat.completions.create.assert_awaited_once()


def test_openai_codex_strip_prefix_supports_hyphen_and_underscore():
    assert _strip_model_prefix("openai-codex/gpt-5.1-codex") == "gpt-5.1-codex"
    assert _strip_model_prefix("openai_codex/gpt-5.1-codex") == "gpt-5.1-codex"


def test_make_provider_passes_extra_headers_to_custom_provider():
    config = Config.model_validate(
        {
            "agents": {"defaults": {"provider": "custom", "model": "gpt-4o-mini"}},
            "providers": {
                "custom": {
                    "apiKey": "test-key",
                    "apiBase": "https://example.com/v1",
                    "extraHeaders": {
                        "APP-Code": "demo-app",
                        "x-session-affinity": "sticky-session",
                    },
                }
            },
        }
    )

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as mock_async_openai:
        _make_provider(config)

    kwargs = mock_async_openai.call_args.kwargs
    assert kwargs["api_key"] == "test-key"
    assert kwargs["base_url"] == "https://example.com/v1"
    assert kwargs["default_headers"]["APP-Code"] == "demo-app"
    assert kwargs["default_headers"]["x-session-affinity"] == "sticky-session"


@pytest.fixture
def mock_agent_runtime(tmp_path):
    """Mock agent command dependencies for focused CLI tests."""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "default-workspace")

    with patch("nanobot.config.loader.load_config", return_value=config) as mock_load_config, \
         patch("nanobot.config.loader.resolve_config_env_vars", side_effect=lambda c: c), \
         patch("nanobot.cli.commands.sync_workspace_templates") as mock_sync_templates, \
         patch("nanobot.cli.commands._make_provider", return_value=object()), \
         patch("nanobot.cli.commands._print_agent_response") as mock_print_response, \
         patch("nanobot.bus.queue.MessageBus"), \
         patch("nanobot.cron.service.CronService"), \
         patch("nanobot.agent.loop.AgentLoop") as mock_agent_loop_cls:
        agent_loop = MagicMock()
        agent_loop.channels_config = None
        agent_loop.process_direct = AsyncMock(
            return_value=OutboundMessage(channel="cli", chat_id="direct", content="mock-response"),
        )
        agent_loop.close_mcp = AsyncMock(return_value=None)
        mock_agent_loop_cls.return_value = agent_loop

        yield {
            "config": config,
            "load_config": mock_load_config,
            "sync_templates": mock_sync_templates,
            "agent_loop_cls": mock_agent_loop_cls,
            "agent_loop": agent_loop,
            "print_response": mock_print_response,
        }


def test_agent_help_shows_workspace_and_config_options():
    result = runner.invoke(app, ["agent", "--help"])

    assert result.exit_code == 0
    stripped_output = _strip_ansi(result.stdout)
    assert "--workspace" in stripped_output
    assert "-w" in stripped_output
    assert "--config" in stripped_output
    assert "-c" in stripped_output


def test_agent_uses_default_config_when_no_workspace_or_config_flags(mock_agent_runtime):
    result = runner.invoke(app, ["agent", "-m", "hello"])

    assert result.exit_code == 0
    assert mock_agent_runtime["load_config"].call_args.args == (None,)
    assert mock_agent_runtime["sync_templates"].call_args.args == (
        mock_agent_runtime["config"].workspace_path,
    )
    assert mock_agent_runtime["agent_loop_cls"].call_args.kwargs["workspace"] == (
        mock_agent_runtime["config"].workspace_path
    )
    mock_agent_runtime["agent_loop"].process_direct.assert_awaited_once()
    mock_agent_runtime["print_response"].assert_called_once_with(
        "mock-response", render_markdown=True, metadata={},
    )


def test_agent_uses_explicit_config_path(mock_agent_runtime, tmp_path: Path):
    config_path = tmp_path / "agent-config.json"
    config_path.write_text("{}")

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_path)])

    assert result.exit_code == 0
    assert mock_agent_runtime["load_config"].call_args.args == (config_path.resolve(),)


def test_agent_config_sets_active_path(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    seen: dict[str, Path] = {}

    monkeypatch.setattr(
        "nanobot.config.loader.set_config_path",
        lambda path: seen.__setitem__("config_path", path),
    )
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _config: object())
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", lambda: object())
    monkeypatch.setattr("nanobot.cron.service.CronService", lambda _store: object())

    class _FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def process_direct(self, *_args, **_kwargs):
            return OutboundMessage(channel="cli", chat_id="direct", content="ok")

        async def close_mcp(self) -> None:
            return None

    monkeypatch.setattr("nanobot.agent.loop.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.cli.commands._print_agent_response", lambda *_args, **_kwargs: None)

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_file)])

    assert result.exit_code == 0
    assert seen["config_path"] == config_file.resolve()


def test_agent_uses_workspace_directory_for_cron_store(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "agent-workspace")
    seen: dict[str, Path] = {}

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _config: object())
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", lambda: object())

    class _FakeCron:
        def __init__(self, store_path: Path) -> None:
            seen["cron_store"] = store_path

    class _FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def process_direct(self, *_args, **_kwargs):
            return OutboundMessage(channel="cli", chat_id="direct", content="ok")

        async def close_mcp(self) -> None:
            return None

    monkeypatch.setattr("nanobot.cron.service.CronService", _FakeCron)
    monkeypatch.setattr("nanobot.agent.loop.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.cli.commands._print_agent_response", lambda *_args, **_kwargs: None)

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_file)])

    assert result.exit_code == 0
    assert seen["cron_store"] == config.workspace_path / "cron" / "jobs.json"


def test_agent_workspace_override_does_not_migrate_legacy_cron(
    monkeypatch, tmp_path: Path
) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    legacy_dir = tmp_path / "global" / "cron"
    legacy_dir.mkdir(parents=True)
    legacy_file = legacy_dir / "jobs.json"
    legacy_file.write_text('{"jobs": []}')

    override = tmp_path / "override-workspace"
    config = Config()
    seen: dict[str, Path] = {}

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _config: object())
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", lambda: object())
    monkeypatch.setattr("nanobot.config.paths.get_cron_dir", lambda: legacy_dir)

    class _FakeCron:
        def __init__(self, store_path: Path) -> None:
            seen["cron_store"] = store_path

    class _FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def process_direct(self, *_args, **_kwargs):
            return OutboundMessage(channel="cli", chat_id="direct", content="ok")

        async def close_mcp(self) -> None:
            return None

    monkeypatch.setattr("nanobot.cron.service.CronService", _FakeCron)
    monkeypatch.setattr("nanobot.agent.loop.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.cli.commands._print_agent_response", lambda *_args, **_kwargs: None)

    result = runner.invoke(
        app,
        ["agent", "-m", "hello", "-c", str(config_file), "-w", str(override)],
    )

    assert result.exit_code == 0
    assert seen["cron_store"] == override / "cron" / "jobs.json"
    assert legacy_file.exists()
    assert not (override / "cron" / "jobs.json").exists()


def test_agent_custom_config_workspace_does_not_migrate_legacy_cron(
    monkeypatch, tmp_path: Path
) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    legacy_dir = tmp_path / "global" / "cron"
    legacy_dir.mkdir(parents=True)
    legacy_file = legacy_dir / "jobs.json"
    legacy_file.write_text('{"jobs": []}')

    custom_workspace = tmp_path / "custom-workspace"
    config = Config()
    config.agents.defaults.workspace = str(custom_workspace)
    seen: dict[str, Path] = {}

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _config: object())
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", lambda: object())
    monkeypatch.setattr("nanobot.config.paths.get_cron_dir", lambda: legacy_dir)

    class _FakeCron:
        def __init__(self, store_path: Path) -> None:
            seen["cron_store"] = store_path

    class _FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def process_direct(self, *_args, **_kwargs):
            return OutboundMessage(channel="cli", chat_id="direct", content="ok")

        async def close_mcp(self) -> None:
            return None

    monkeypatch.setattr("nanobot.cron.service.CronService", _FakeCron)
    monkeypatch.setattr("nanobot.agent.loop.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr(
        "nanobot.cli.commands._print_agent_response", lambda *_args, **_kwargs: None
    )

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_file)])

    assert result.exit_code == 0
    assert seen["cron_store"] == custom_workspace / "cron" / "jobs.json"
    assert legacy_file.exists()
    assert not (custom_workspace / "cron" / "jobs.json").exists()


def test_agent_overrides_workspace_path(mock_agent_runtime):
    workspace_path = Path("/tmp/agent-workspace")

    result = runner.invoke(app, ["agent", "-m", "hello", "-w", str(workspace_path)])

    assert result.exit_code == 0
    assert mock_agent_runtime["config"].agents.defaults.workspace == str(workspace_path)
    assert mock_agent_runtime["sync_templates"].call_args.args == (workspace_path,)
    assert mock_agent_runtime["agent_loop_cls"].call_args.kwargs["workspace"] == workspace_path


def test_agent_workspace_override_wins_over_config_workspace(mock_agent_runtime, tmp_path: Path):
    config_path = tmp_path / "agent-config.json"
    config_path.write_text("{}")
    workspace_path = Path("/tmp/agent-workspace")

    result = runner.invoke(
        app,
        ["agent", "-m", "hello", "-c", str(config_path), "-w", str(workspace_path)],
    )

    assert result.exit_code == 0
    assert mock_agent_runtime["load_config"].call_args.args == (config_path.resolve(),)
    assert mock_agent_runtime["config"].agents.defaults.workspace == str(workspace_path)
    assert mock_agent_runtime["sync_templates"].call_args.args == (workspace_path,)
    assert mock_agent_runtime["agent_loop_cls"].call_args.kwargs["workspace"] == workspace_path


def test_agent_hints_about_deprecated_memory_window(mock_agent_runtime, tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"agents": {"defaults": {"memoryWindow": 42}}}))

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_file)])

    assert result.exit_code == 0
    assert "memoryWindow" in result.stdout
    assert "no longer used" in result.stdout


def test_heartbeat_retains_recent_messages_by_default():
    config = Config()

    assert config.gateway.heartbeat.keep_recent_messages == 8


def _write_instance_config(tmp_path: Path) -> Path:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")
    return config_file


def _stop_gateway_provider(_config) -> object:
    raise _StopGatewayError("stop")


def _patch_cli_command_runtime(
    monkeypatch,
    config: Config,
    *,
    set_config_path=None,
    sync_templates=None,
    make_provider=None,
    message_bus=None,
    session_manager=None,
    cron_service=None,
    get_cron_dir=None,
) -> None:
    monkeypatch.setattr(
        "nanobot.config.loader.set_config_path",
        set_config_path or (lambda _path: None),
    )
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr(
        "nanobot.config.loader.resolve_config_env_vars",
        lambda c: c,
        raising=False,
    )
    monkeypatch.setattr(
        "nanobot.cli.commands.sync_workspace_templates",
        sync_templates or (lambda _path: None),
    )
    monkeypatch.setattr(
        "nanobot.cli.commands._make_provider",
        make_provider or (lambda _config: object()),
    )

    if message_bus is not None:
        monkeypatch.setattr("nanobot.bus.queue.MessageBus", message_bus)
    if session_manager is not None:
        monkeypatch.setattr("nanobot.session.manager.SessionManager", session_manager)
    if cron_service is not None:
        monkeypatch.setattr("nanobot.cron.service.CronService", cron_service)
    if get_cron_dir is not None:
        monkeypatch.setattr("nanobot.config.paths.get_cron_dir", get_cron_dir)


def _patch_serve_runtime(monkeypatch, config: Config, seen: dict[str, object]) -> None:
    pytest.importorskip("aiohttp")

    class _FakeApiApp:
        def __init__(self) -> None:
            self.on_startup: list[object] = []
            self.on_cleanup: list[object] = []

    class _FakeAgentLoop:
        def __init__(self, **kwargs) -> None:
            seen["workspace"] = kwargs["workspace"]

        async def _connect_mcp(self) -> None:
            return None

        async def close_mcp(self) -> None:
            return None

    def _fake_create_app(agent_loop, model_name: str, request_timeout: float):
        seen["agent_loop"] = agent_loop
        seen["model_name"] = model_name
        seen["request_timeout"] = request_timeout
        return _FakeApiApp()

    def _fake_run_app(api_app, host: str, port: int, print):
        seen["api_app"] = api_app
        seen["host"] = host
        seen["port"] = port

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        message_bus=lambda: object(),
        session_manager=lambda _workspace: object(),
    )
    monkeypatch.setattr("nanobot.agent.loop.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.api.server.create_app", _fake_create_app)
    monkeypatch.setattr("aiohttp.web.run_app", _fake_run_app)


def test_gateway_uses_workspace_from_config_by_default(monkeypatch, tmp_path: Path) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    seen: dict[str, Path] = {}

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        set_config_path=lambda path: seen.__setitem__("config_path", path),
        sync_templates=lambda path: seen.__setitem__("workspace", path),
        make_provider=_stop_gateway_provider,
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert isinstance(result.exception, _StopGatewayError)
    assert seen["config_path"] == config_file.resolve()
    assert seen["workspace"] == Path(config.agents.defaults.workspace)


def test_gateway_workspace_option_overrides_config(monkeypatch, tmp_path: Path) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    override = tmp_path / "override-workspace"
    seen: dict[str, Path] = {}

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        sync_templates=lambda path: seen.__setitem__("workspace", path),
        make_provider=_stop_gateway_provider,
    )

    result = runner.invoke(
        app,
        ["gateway", "--config", str(config_file), "--workspace", str(override)],
    )

    assert isinstance(result.exception, _StopGatewayError)
    assert seen["workspace"] == override
    assert config.workspace_path == override


def test_gateway_uses_workspace_directory_for_cron_store(monkeypatch, tmp_path: Path) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    seen: dict[str, Path] = {}

    class _StopCron:
        def __init__(self, store_path: Path) -> None:
            seen["cron_store"] = store_path
            raise _StopGatewayError("stop")

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        message_bus=lambda: object(),
        session_manager=lambda _workspace: object(),
        cron_service=_StopCron,
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert isinstance(result.exception, _StopGatewayError)
    assert seen["cron_store"] == config.workspace_path / "cron" / "jobs.json"


def test_gateway_cron_evaluator_receives_scheduled_reminder_context(
    monkeypatch, tmp_path: Path
) -> None:
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    provider = object()
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    seen: dict[str, object] = {}

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _config: provider)
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", lambda: bus)
    monkeypatch.setattr("nanobot.session.manager.SessionManager", lambda _workspace: object())

    class _FakeCron:
        def __init__(self, _store_path: Path) -> None:
            self.on_job = None
            seen["cron"] = self

    class _FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:
            self.model = "test-model"
            self.tools = {}

        async def process_direct(self, *_args, **_kwargs):
            return OutboundMessage(
                channel="telegram",
                chat_id="user-1",
                content="Time to stretch.",
            )

        async def close_mcp(self) -> None:
            return None

        async def run(self) -> None:
            return None

        def stop(self) -> None:
            return None

    class _StopAfterCronSetup:
        def __init__(self, *_args, **_kwargs) -> None:
            raise _StopGatewayError("stop")

    async def _capture_evaluate_response(
        response: str,
        task_context: str,
        provider_arg: object,
        model: str,
    ) -> bool:
        seen["response"] = response
        seen["task_context"] = task_context
        seen["provider"] = provider_arg
        seen["model"] = model
        return True

    monkeypatch.setattr("nanobot.cron.service.CronService", _FakeCron)
    monkeypatch.setattr("nanobot.agent.loop.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.channels.manager.ChannelManager", _StopAfterCronSetup)
    monkeypatch.setattr(
        "nanobot.utils.evaluator.evaluate_response",
        _capture_evaluate_response,
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert isinstance(result.exception, _StopGatewayError)
    cron = seen["cron"]
    assert isinstance(cron, _FakeCron)
    assert cron.on_job is not None

    job = CronJob(
        id="cron-1",
        name="stretch",
        payload=CronPayload(
            message="Remind me to stretch.",
            deliver=True,
            channel="telegram",
            to="user-1",
        ),
    )

    response = asyncio.run(cron.on_job(job))

    assert response == "Time to stretch."
    assert seen["response"] == "Time to stretch."
    assert seen["provider"] is provider
    assert seen["model"] == "test-model"
    assert seen["task_context"] == (
        "[Scheduled Task] Timer finished.\n\n"
        "Task 'stretch' has been triggered.\n"
        "Scheduled instruction: Remind me to stretch."
    )
    bus.publish_outbound.assert_awaited_once_with(
        OutboundMessage(
            channel="telegram",
            chat_id="user-1",
            content="Time to stretch.",
        )
    )


@pytest.mark.asyncio
async def test_gateway_weekly_review_uses_build_cycle(monkeypatch, tmp_path: Path) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    provider = object()
    seen: dict[str, object] = {}

    class _FakeCron:
        def __init__(self, _store_path: Path) -> None:
            self.on_job = None
            seen["cron"] = self

    class _FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:
            self.provider = provider
            self.model = "test-model"
            self.tools = {}

        async def close_mcp(self) -> None:
            return None

        async def process_direct(self, *_args, **_kwargs):
            return types.SimpleNamespace(content="fallback")

        async def run(self) -> None:
            return None

        def stop(self) -> None:
            return None

    class _StopAfterCronSetup:
        def __init__(self, *_args, **_kwargs) -> None:
            raise _StopGatewayError("stop")

    class _FakeWeeklyReviewBuilder:
        def __init__(self, provider=None, model=None, adjudicator=None) -> None:
            seen["provider"] = provider
            seen["model"] = model

        async def build_cycle(self, workspace: Path) -> str:
            seen["workspace"] = workspace
            seen["used_build_cycle"] = True
            return "# 周复盘\n\n## 本周摘要\n治理闭环已执行\n"

        def build(self, workspace: Path) -> str:
            raise AssertionError("static build() should not be used")

    class _FakeSoulLogWriter:
        def __init__(self, workspace: Path) -> None:
            seen["log_workspace"] = workspace

        def write_weekly(self, date_str: str, content: str) -> None:
            seen["date_str"] = date_str
            seen["content"] = content

    monkeypatch.setattr(soul_review, "WeeklyReviewBuilder", _FakeWeeklyReviewBuilder)
    monkeypatch.setattr(soul_logs, "SoulLogWriter", _FakeSoulLogWriter)

    monkeypatch.setattr("nanobot.cli.commands._load_runtime_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr("nanobot.cron.service.CronService", _FakeCron)
    monkeypatch.setattr("nanobot.agent.loop.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.channels.manager.ChannelManager", _StopAfterCronSetup)
    _patch_cli_command_runtime(
        monkeypatch,
        config,
        message_bus=lambda: object(),
        session_manager=lambda _workspace: object(),
        make_provider=lambda _config: provider,
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])
    assert isinstance(result.exception, _StopGatewayError)

    cron = seen["cron"]
    job = CronJob(id="weekly_review", name="weekly_review", payload=CronPayload(kind="system_event"))
    response = await cron.on_job(job)

    assert response is None
    assert seen["used_build_cycle"] is True
    assert seen["provider"] is provider
    assert seen["model"] == "test-model"
    assert seen["workspace"] == config.workspace_path


@pytest.mark.asyncio
async def test_gateway_monthly_calibration_writes_governance_report(
    monkeypatch, tmp_path: Path
) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    seen: dict[str, object] = {}

    # Prepare minimal workspace state for the monthly builder.
    workspace = config.workspace_path
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "CORE_ANCHOR.md").write_text("# 核心锚点\n\n- 不无底线顺从\n", encoding="utf-8")

    class _FakeCron:
        def __init__(self, _store_path: Path) -> None:
            self.on_job = None
            seen["cron"] = self

    class _FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:
            self.provider = object()
            self.model = "test-model"
            self.tools = {}

        async def close_mcp(self) -> None:
            return None

        async def process_direct(self, *_args, **_kwargs):
            seen["process_direct_called"] = True
            raise AssertionError("monthly_calibration must not route through AgentLoop/LLM")

        async def run(self) -> None:
            return None

        def stop(self) -> None:
            return None

    class _StopAfterCronSetup:
        def __init__(self, *_args, **_kwargs) -> None:
            raise _StopGatewayError("stop")

    class _FakeSoulLogWriter:
        def __init__(self, log_workspace: Path) -> None:
            seen["log_workspace"] = log_workspace

        def write_monthly(self, date_str: str, content: str) -> None:
            seen["date_str"] = date_str
            seen["content"] = content

    monkeypatch.setattr(soul_logs, "SoulLogWriter", _FakeSoulLogWriter)

    monkeypatch.setattr("nanobot.cli.commands._load_runtime_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr("nanobot.cron.service.CronService", _FakeCron)
    monkeypatch.setattr("nanobot.agent.loop.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.channels.manager.ChannelManager", _StopAfterCronSetup)
    _patch_cli_command_runtime(
        monkeypatch,
        config,
        message_bus=lambda: object(),
        session_manager=lambda _workspace: object(),
        make_provider=lambda _config: object(),
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])
    assert isinstance(result.exception, _StopGatewayError)

    cron = seen["cron"]
    job = CronJob(id="monthly_calibration", name="monthly_calibration", payload=CronPayload(kind="system_event"))
    response = await cron.on_job(job)

    assert response is None
    assert seen["log_workspace"] == config.workspace_path
    written = str(seen.get("content") or "")
    assert re.findall(r"^##\s+(.+)$", written, flags=re.MULTILINE) == [
        "本月总体结论",
        "锚点一致性",
        "关系演化校验",
        "风险与偏移点",
        "建议动作",
    ]
    assert "未做越界判定" in written
    assert seen.get("process_direct_called") is not True


def test_gateway_workspace_override_does_not_migrate_legacy_cron(
    monkeypatch, tmp_path: Path
) -> None:
    config_file = _write_instance_config(tmp_path)
    legacy_dir = tmp_path / "global" / "cron"
    legacy_dir.mkdir(parents=True)
    legacy_file = legacy_dir / "jobs.json"
    legacy_file.write_text('{"jobs": []}')

    override = tmp_path / "override-workspace"
    config = Config()
    seen: dict[str, Path] = {}

    class _StopCron:
        def __init__(self, store_path: Path) -> None:
            seen["cron_store"] = store_path
            raise _StopGatewayError("stop")

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        message_bus=lambda: object(),
        session_manager=lambda _workspace: object(),
        cron_service=_StopCron,
        get_cron_dir=lambda: legacy_dir,
    )

    result = runner.invoke(
        app,
        ["gateway", "--config", str(config_file), "--workspace", str(override)],
    )

    assert isinstance(result.exception, _StopGatewayError)
    assert seen["cron_store"] == override / "cron" / "jobs.json"
    assert legacy_file.exists()
    assert not (override / "cron" / "jobs.json").exists()


def test_gateway_custom_config_workspace_does_not_migrate_legacy_cron(
    monkeypatch, tmp_path: Path
) -> None:
    config_file = _write_instance_config(tmp_path)
    legacy_dir = tmp_path / "global" / "cron"
    legacy_dir.mkdir(parents=True)
    legacy_file = legacy_dir / "jobs.json"
    legacy_file.write_text('{"jobs": []}')

    custom_workspace = tmp_path / "custom-workspace"
    config = Config()
    config.agents.defaults.workspace = str(custom_workspace)
    seen: dict[str, Path] = {}

    class _StopCron:
        def __init__(self, store_path: Path) -> None:
            seen["cron_store"] = store_path
            raise _StopGatewayError("stop")

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        message_bus=lambda: object(),
        session_manager=lambda _workspace: object(),
        cron_service=_StopCron,
        get_cron_dir=lambda: legacy_dir,
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert isinstance(result.exception, _StopGatewayError)
    assert seen["cron_store"] == custom_workspace / "cron" / "jobs.json"
    assert legacy_file.exists()
    assert not (custom_workspace / "cron" / "jobs.json").exists()


def test_migrate_cron_store_moves_legacy_file(tmp_path: Path) -> None:
    """Legacy global jobs.json is moved into the workspace on first run."""
    from nanobot.cli.commands import _migrate_cron_store

    legacy_dir = tmp_path / "global" / "cron"
    legacy_dir.mkdir(parents=True)
    legacy_file = legacy_dir / "jobs.json"
    legacy_file.write_text('{"jobs": []}')

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    workspace_cron = config.workspace_path / "cron" / "jobs.json"

    with patch("nanobot.config.paths.get_cron_dir", return_value=legacy_dir):
        _migrate_cron_store(config)

    assert workspace_cron.exists()
    assert workspace_cron.read_text() == '{"jobs": []}'
    assert not legacy_file.exists()


def test_migrate_cron_store_skips_when_workspace_file_exists(tmp_path: Path) -> None:
    """Migration does not overwrite an existing workspace cron store."""
    from nanobot.cli.commands import _migrate_cron_store

    legacy_dir = tmp_path / "global" / "cron"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "jobs.json").write_text('{"old": true}')

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    workspace_cron = config.workspace_path / "cron" / "jobs.json"
    workspace_cron.parent.mkdir(parents=True)
    workspace_cron.write_text('{"new": true}')

    with patch("nanobot.config.paths.get_cron_dir", return_value=legacy_dir):
        _migrate_cron_store(config)

    assert workspace_cron.read_text() == '{"new": true}'


def test_gateway_uses_configured_port_when_cli_flag_is_missing(monkeypatch, tmp_path: Path) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.gateway.port = 18791

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        make_provider=_stop_gateway_provider,
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert isinstance(result.exception, _StopGatewayError)
    assert "port 18791" in result.stdout


def test_gateway_cli_port_overrides_configured_port(monkeypatch, tmp_path: Path) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.gateway.port = 18791

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        make_provider=_stop_gateway_provider,
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_file), "--port", "18792"])

    assert isinstance(result.exception, _StopGatewayError)
    assert "port 18792" in result.stdout


def test_serve_uses_api_config_defaults_and_workspace_override(
    monkeypatch, tmp_path: Path
) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    config.api.host = "127.0.0.2"
    config.api.port = 18900
    config.api.timeout = 45.0
    override_workspace = tmp_path / "override-workspace"
    seen: dict[str, object] = {}

    _patch_serve_runtime(monkeypatch, config, seen)

    result = runner.invoke(
        app,
        ["serve", "--config", str(config_file), "--workspace", str(override_workspace)],
    )

    assert result.exit_code == 0
    assert seen["workspace"] == override_workspace
    assert seen["host"] == "127.0.0.2"
    assert seen["port"] == 18900
    assert seen["request_timeout"] == 45.0


def test_serve_cli_options_override_api_config(monkeypatch, tmp_path: Path) -> None:
    config_file = _write_instance_config(tmp_path)
    config = Config()
    config.api.host = "127.0.0.2"
    config.api.port = 18900
    config.api.timeout = 45.0
    seen: dict[str, object] = {}

    _patch_serve_runtime(monkeypatch, config, seen)

    result = runner.invoke(
        app,
        [
            "serve",
            "--config",
            str(config_file),
            "--host",
            "127.0.0.1",
            "--port",
            "18901",
            "--timeout",
            "46",
        ],
    )

    assert result.exit_code == 0
    assert seen["host"] == "127.0.0.1"
    assert seen["port"] == 18901
    assert seen["request_timeout"] == 46.0


def test_channels_login_requires_channel_name() -> None:
    result = runner.invoke(app, ["channels", "login"])

    assert result.exit_code == 2
