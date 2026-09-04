from pathlib import Path
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


def test_zsh_widget_is_safe_and_both_profiles_wire_it():
    widget = (ROOT / "tools/navi-widget.zsh").read_text()
    assert "zle .accept-line" in widget
    assert "selected=$(navi --print 2>/dev/tty) || return 0" in widget
    assert "LBUFFER=$selected" in widget
    assert "zle -N meta-ball-navi-accept-line" in widget

    for profile in ("server", "evolver-edge"):
        zshrc = (ROOT / ".devcontainer/dotfiles/.zshrc").read_text()
        assert "NAVI_PATH=\"${NAVI_PATH:-/workspaces/meta_bal/docs/navi/generated}\"" in zshrc
        assert "tools/navi-widget.zsh" in zshrc
