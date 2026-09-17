from pathlib import Path
import json
import subprocess

import pytest


pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[2]
GENERATOR = ROOT / "tools/generate_navi_cheats"


def test_generated_navi_catalog_is_fresh():
    result = subprocess.run([str(GENERATOR), "--check"], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_generator_is_deterministic_and_uses_all_sources():
    sources = sorted((ROOT / "docs/navi/cheatsheets").glob("*.cheat"))
    generated = (ROOT / "docs/navi/generated/meta-ball.cheat").read_text()
    assert sources
    assert generated.startswith("# GENERATED FILE. DO NOT EDIT.\n")
    for source in sources:
        assert source.read_text().strip() in generated


def test_every_deployment_action_has_a_generated_search_entry():
    index = json.loads((ROOT / "metactl/applications/deployment/action-catalog.json").read_text())
    generated = (ROOT / "docs/navi/generated/meta-ball.cheat").read_text()
    for reference in index["catalogs"]:
        catalog = json.loads((ROOT / "metactl/applications/deployment" / reference["path"]).read_text())
        for action in catalog["actions"]:
            assert f"metactl {action['id']}" in generated


def test_navi_uses_the_first_class_presentation_paths_with_action_metadata():
    generated = (ROOT / "docs/navi/generated/meta-ball.cheat").read_text()
    assert "% Meta BAL path controllers commands list [action_id=evolver.controllers.commands.list]" in generated
    assert "% Meta BAL path controllers adopt [action_id=evolver.controllers.add]" in generated
    assert "[planned]" in generated


def test_generated_navi_includes_authoritative_path_positionals():
    generated = (ROOT / "docs/navi/generated/meta-ball.cheat").read_text()
    assert "metactl controllers show <controller_id>" in generated
    assert "metactl controllers freshness <controller_id>" in generated


def test_curated_navi_catalog_covers_primary_developer_lanes():
    generated = (ROOT / "docs/navi/generated/meta-ball.cheat").read_text().lower()
    for phrase in ("server shell", "evolver-edge up", "tools/test all", "postgres",
                   "metactl api tui", "recovery", "calibration", "release"):
        assert phrase in generated


def test_zsh_widget_is_safe_and_both_profiles_wire_it():
    widget = (ROOT / "tools/navi-widget.zsh").read_text()
    assert "zle .accept-line" in widget
    assert "selected=$(navi --print 2>/dev/tty) || return 0" in widget
    assert "LBUFFER=$selected" in widget
    assert "zle -N meta-ball-navi-accept-line" in widget

    for profile in ("server", "evolver-edge"):
        fragment = (ROOT / ".devcontainer/dotfiles/meta-ball.zsh").read_text()
        assert "NAVI_PATH=\"${NAVI_PATH:-/workspaces/meta_bal/docs/navi/generated}\"" in fragment
        assert "tools/navi-widget.zsh" in fragment


def test_parent_docs_do_not_reintroduce_retired_evoctl_claim():
    readme = (ROOT / "README.md").read_text()
    assert "there is no separate `evoctl` command" not in readme
    assert "docs/operator.md" in readme
