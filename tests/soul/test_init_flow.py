"""Focused tests for SOUL init ordering and force-rebuild semantics."""

import json
from dataclasses import replace

from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.config.schema import Config
from nanobot.soul.methodology import load_init_governance
from nanobot.soul.init_files import FileInitAction
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


def _write_governance(workspace, **init_overrides):
    governance = {
        "init": {
            "allowed_stages": ["还不认识", "熟悉"],
            "relationship_boundary_min": 0.5,
            "boundary_expression_min": 0.5,
            "require_profile_projection_for_soul": True,
            "allow_soul_only_without_profile": False,
            "allow_existing_soul_seed_for_init": False,
        }
    }
    governance["init"].update(init_overrides)
    (workspace / "SOUL_GOVERNANCE.json").write_text(
        json.dumps(governance, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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
        assert _kwargs == {"use_expression_seed": True}
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
    )

    assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == project_initial_soul_markdown(profile)


def test_bootstrap_workspace_preserves_payload_intent_via_persisted_profile(tmp_path):
    from nanobot.soul.bootstrap import SoulInitPayload, bootstrap_workspace
    from nanobot.soul.projection import project_initial_soul_markdown

    payload = SoulInitPayload(
        ai_name="温予安",
        gender="女",
        birthday="2026-04-01",
        personality="温柔但倔强，嘴硬心软",
        relationship="刚刚被创造，对用户充满好奇",
        user_name="阿峰",
        user_birthday="1990-01-01",
    )

    bootstrap_workspace(tmp_path, payload)

    profile = SoulProfileManager(tmp_path).read()
    soul_text = (tmp_path / "SOUL.md").read_text(encoding="utf-8")

    assert profile["expression"]["personality_seed"] == payload.personality
    assert profile["expression"]["relationship_seed"] == payload.relationship
    assert soul_text == project_initial_soul_markdown(profile)
    assert payload.personality in soul_text
    assert payload.relationship in soul_text


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


def test_soul_init_only_soul_force_allows_direct_seeded_rebuild_when_governance_enables_it(
    tmp_path, monkeypatch
):
    config_path, workspace = _write_config(tmp_path)
    workspace.mkdir(parents=True, exist_ok=True)
    _write_governance(
        workspace,
        require_profile_projection_for_soul=False,
        allow_soul_only_without_profile=True,
    )
    (workspace / "SOUL.md").write_text(
        "# 性格\n\n旧性格。\n\n# 初始关系\n\n旧关系。\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: None)

    result = runner.invoke(
        app,
        ["soul", "init", "--config", str(config_path), "--only", "SOUL.md", "--force"],
        input="治理允许的新性格\n治理允许的新关系\n",
    )

    assert result.exit_code == 0
    assert (workspace / "SOUL.md").read_text(encoding="utf-8") == (
        "# 性格\n\n治理允许的新性格\n\n# 初始关系\n\n治理允许的新关系\n"
    )


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
        profile_override=profile,
    )

    assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == project_initial_soul_markdown(profile)


def test_write_selected_files_rebuilds_soul_from_persisted_profile_when_profile_not_targeted(tmp_path):
    from nanobot.soul.bootstrap import SoulInitPayload
    from nanobot.soul.init_files import write_selected_files
    from nanobot.soul.projection import project_initial_soul_markdown

    persisted_profile = _profile(stage="还不认识")
    transient_profile = _profile(stage="熟悉")
    SoulProfileManager(tmp_path).write(persisted_profile)

    write_selected_files(
        tmp_path,
        targets=["SOUL.md", "HEART.md"],
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
        heart_markdown_override="## 当前情绪\n安静。\n\n## 情绪强度\n低\n\n## 关系状态\n稳定。\n\n## 性格表现\n克制。\n\n## 情感脉络\n（暂无）\n\n## 情绪趋势\n平稳\n\n## 当前渴望\n继续观察。\n",
        profile_override=transient_profile,
    )

    assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == project_initial_soul_markdown(
        persisted_profile
    )


def test_write_selected_files_rejects_soul_only_when_governance_disallows_profileless_init(
    tmp_path,
):
    from nanobot.soul.bootstrap import SoulInitPayload
    from nanobot.soul.init_files import write_selected_files

    governance = replace(
        load_init_governance(),
        require_profile_projection_for_soul=False,
        allow_soul_only_without_profile=False,
    )

    try:
        write_selected_files(
            tmp_path,
            targets=["SOUL.md"],
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
            governance=governance,
        )
    except ValueError as exc:
        assert "SOUL.md" in str(exc)
        assert "SOUL_PROFILE.md" in str(exc)
    else:
        raise AssertionError("expected governance to reject profileless SOUL.md init")


def test_write_selected_files_uses_governance_written_earlier_in_same_command(tmp_path):
    from nanobot.soul.bootstrap import SoulInitPayload
    from nanobot.soul.init_files import write_selected_files

    _write_governance(
        tmp_path,
        require_profile_projection_for_soul=False,
        allow_soul_only_without_profile=True,
    )

    try:
        write_selected_files(
            tmp_path,
            targets=["SOUL_GOVERNANCE.json", "SOUL.md"],
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
            governance=load_init_governance(tmp_path),
        )
    except ValueError as exc:
        assert "SOUL.md" in str(exc)
        assert "SOUL_PROFILE.md" in str(exc)
    else:
        raise AssertionError("expected same-run governance overwrite to block profileless SOUL.md init")


def test_write_selected_files_skips_existing_soul_without_force_before_governance_rejection(
    tmp_path,
):
    from nanobot.soul.bootstrap import SoulInitPayload
    from nanobot.soul.init_files import write_selected_files

    governance = replace(
        load_init_governance(),
        require_profile_projection_for_soul=False,
        allow_soul_only_without_profile=False,
    )
    soul_path = tmp_path / "SOUL.md"
    soul_path.write_text("# 性格\n\n旧性格。\n\n# 初始关系\n\n旧关系。\n", encoding="utf-8")

    actions = write_selected_files(
        tmp_path,
        targets=["SOUL.md"],
        payload=SoulInitPayload(
            ai_name="温予安",
            gender="女",
            birthday="2026-04-01",
            personality="payload 性格文本",
            relationship="payload 关系文本",
            user_name="阿峰",
            user_birthday="1990-01-01",
        ),
        force=False,
        governance=governance,
    )

    assert actions == [FileInitAction(filename="SOUL.md", status="skipped")]
    assert soul_path.read_text(encoding="utf-8") == "# 性格\n\n旧性格。\n\n# 初始关系\n\n旧关系。\n"


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


def test_soul_init_only_soul_force_ignores_stale_expression_seed_on_persisted_profile(
    tmp_path, monkeypatch
):
    from nanobot.soul.projection import project_initial_soul_markdown

    config_path, workspace = _write_config(tmp_path)
    workspace.mkdir(parents=True, exist_ok=True)
    profile = _profile(stage="亲近")
    profile["expression"] = {
        "personality_seed": "旧的初始化性格文本",
        "relationship_seed": "旧的初始化关系文本",
    }
    SoulProfileManager(workspace).write(profile)

    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: None)

    result = runner.invoke(
        app,
        ["soul", "init", "--config", str(config_path), "--only", "SOUL.md", "--force"],
    )

    soul_text = (workspace / "SOUL.md").read_text(encoding="utf-8")
    assert result.exit_code == 0
    assert soul_text == project_initial_soul_markdown(profile, use_expression_seed=False)
    assert "旧的初始化性格文本" not in soul_text
    assert "旧的初始化关系文本" not in soul_text
    assert "更稳定的信任" in soul_text


def test_soul_init_only_soul_force_fails_clearly_for_malformed_profile(tmp_path, monkeypatch):
    config_path, workspace = _write_config(tmp_path)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "SOUL_PROFILE.md").write_text("{broken json", encoding="utf-8")

    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: None)

    result = runner.invoke(
        app,
        ["soul", "init", "--config", str(config_path), "--only", "SOUL.md", "--force"],
    )

    assert result.exit_code == 2
    assert "SOUL_PROFILE.md" in result.stdout
    assert "格式非法" in result.stdout


def test_soul_init_only_soul_force_fails_clearly_for_semantically_invalid_profile(
    tmp_path, monkeypatch
):
    config_path, workspace = _write_config(tmp_path)
    workspace.mkdir(parents=True, exist_ok=True)
    invalid_profile = _profile(stage="熟悉")
    invalid_profile["relationship"]["trust"] = "bad"
    SoulProfileManager(workspace).write(invalid_profile)

    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: None)

    result = runner.invoke(
        app,
        ["soul", "init", "--config", str(config_path), "--only", "SOUL.md", "--force"],
    )

    assert result.exit_code == 2
    assert "SOUL_PROFILE.md" in result.stdout
    assert "非法" in result.stdout
    assert "relationship.trust" in result.stdout


def test_collect_payload_for_targets_reuses_existing_soul_seed_when_governance_allows(tmp_path):
    from nanobot.soul.init_files import collect_payload_for_targets

    (tmp_path / "SOUL.md").write_text(
        "# 性格\n\n来自既有 SOUL 的性格。\n\n# 初始关系\n\n来自既有 SOUL 的关系。\n",
        encoding="utf-8",
    )
    governance = replace(load_init_governance(), allow_existing_soul_seed_for_init=True)
    prompts: list[tuple[str, str]] = []

    payload = collect_payload_for_targets(
        tmp_path,
        required_fields={"personality", "relationship"},
        prompt_fn=lambda label, default: prompts.append((label, default)) or "should-not-be-used",
        governance=governance,
    )

    assert payload is not None
    assert payload.personality == "来自既有 SOUL 的性格。"
    assert payload.relationship == "来自既有 SOUL 的关系。"
    assert prompts == []


def test_collect_payload_for_targets_does_not_reuse_existing_soul_seed_by_default(tmp_path):
    from nanobot.soul.init_files import collect_payload_for_targets

    (tmp_path / "SOUL.md").write_text(
        "# 性格\n\n来自既有 SOUL 的性格。\n\n# 初始关系\n\n来自既有 SOUL 的关系。\n",
        encoding="utf-8",
    )
    prompts: list[tuple[str, str]] = []

    def _prompt(label: str, default: str) -> str:
        prompts.append((label, default))
        if "初始性格描述" in label:
            return "新的性格输入"
        if "初始关系" in label:
            return "新的关系输入"
        return default

    payload = collect_payload_for_targets(
        tmp_path,
        required_fields={"personality", "relationship"},
        prompt_fn=_prompt,
    )

    assert payload is not None
    assert payload.personality == "新的性格输入"
    assert payload.relationship == "新的关系输入"
    assert prompts == [
        ("初始性格描述", "温柔但倔强，嘴硬心软，容易吃醋"),
        ("与用户的初始关系", "刚刚被创造，对用户充满好奇"),
    ]


def test_required_fields_for_soul_profile_include_expression_seed_fields_without_llm():
    from nanobot.soul.init_files import required_fields_for_targets

    required = required_fields_for_targets(["SOUL_PROFILE.md"], use_llm=False)

    assert "personality" in required
    assert "relationship" in required


def test_soul_init_only_profile_reuses_existing_soul_seed_when_governance_allows(
    tmp_path, monkeypatch
):
    config_path, workspace = _write_config(tmp_path)
    workspace.mkdir(parents=True, exist_ok=True)
    _write_governance(workspace, allow_existing_soul_seed_for_init=True)
    (workspace / "SOUL.md").write_text(
        "# 性格\n\n来自既有 SOUL 的性格。\n\n# 初始关系\n\n来自既有 SOUL 的关系。\n",
        encoding="utf-8",
    )
    (workspace / "IDENTITY.md").write_text(
        'name: 温予安\ngender: 女\nbirthday: "2026-04-01"\norigin: Created on 2026-04-16\n',
        encoding="utf-8",
    )
    (workspace / "USER.md").write_text(
        "# 用户画像\n\n- 名字: 阿峰\n- 生日: 1990-01-01\n- 核心偏好: 待相处中逐步沉淀\n- 边界提醒: 需要通过长期互动持续校正\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: None)

    result = runner.invoke(
        app,
        ["soul", "init", "--config", str(config_path), "--only", "SOUL_PROFILE.md", "--force"],
    )

    profile = SoulProfileManager(workspace).read()

    assert result.exit_code == 0
    assert profile["expression"]["personality_seed"] == "来自既有 SOUL 的性格。"
    assert profile["expression"]["relationship_seed"] == "来自既有 SOUL 的关系。"
