"""Tests for soul methodology source definitions."""

import json

from nanobot.soul.bootstrap import load_workspace_template
from nanobot.soul.methodology import (
    RELATIONSHIP_STAGES,
    build_default_soul_governance,
    load_init_governance,
    render_soul_governance_json,
    render_soul_method_markdown,
)


def test_render_soul_method_markdown_lists_all_relationship_stages():
    content = render_soul_method_markdown()

    for stage in RELATIONSHIP_STAGES:
        assert stage in content


def test_load_workspace_template_uses_methodology_rendered_soul_method():
    assert load_workspace_template("SOUL_METHOD.md") == render_soul_method_markdown()


def test_default_soul_governance_includes_init_flags():
    governance = build_default_soul_governance()

    assert governance["init"]["require_profile_projection_for_soul"] is True
    assert governance["init"]["allow_soul_only_without_profile"] is False
    assert governance["init"]["allow_existing_soul_seed_for_init"] is False


def test_render_soul_governance_json_includes_init_flags():
    payload = json.loads(render_soul_governance_json())

    assert payload["init"]["require_profile_projection_for_soul"] is True
    assert payload["init"]["allow_soul_only_without_profile"] is False
    assert payload["init"]["allow_existing_soul_seed_for_init"] is False


def test_load_init_governance_reads_workspace_flag_overrides(tmp_path):
    (tmp_path / "SOUL_GOVERNANCE.json").write_text(
        json.dumps(
            {
                "init": {
                    "require_profile_projection_for_soul": False,
                    "allow_soul_only_without_profile": True,
                    "allow_existing_soul_seed_for_init": True,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    governance = load_init_governance(tmp_path)

    assert governance.require_profile_projection_for_soul is False
    assert governance.allow_soul_only_without_profile is True
    assert governance.allow_existing_soul_seed_for_init is True
