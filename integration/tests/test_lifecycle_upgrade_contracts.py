from pathlib import Path

import pytest


pytestmark = pytest.mark.integration
ROOT = Path(__file__).parents[2]


def test_developer_upgrade_is_fast_forward_only_and_reuses_fixed_compose_health() -> None:
    script = (ROOT / "tools/evolver-edge").read_text(encoding="utf-8")

    assert "status --porcelain" in script
    assert "fetch --prune origin" in script
    assert "merge --ff-only" in script
    assert "submodule sync --recursive" in script
    assert "submodule update --init --recursive" in script
    assert 'run_compose up -d --build' in script
    assert "final_state running" in script
    assert "git reset" not in script
    assert "--volumes" not in script


def test_documentation_keeps_release_and_checkout_upgrade_semantics_distinct() -> None:
    docs = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("docs/evoctl.md", "docs/development.md", "docs/operator.md")
    )

    assert "evoctl update apply RELEASE" in docs
    assert "tools/evolver-edge upgrade" in docs
    assert "source-checkout" in docs
    assert "metactl server upgrade" in docs
    assert "remains unavailable" in docs
