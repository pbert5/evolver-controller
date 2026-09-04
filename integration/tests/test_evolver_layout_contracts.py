from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
pytestmark = pytest.mark.integration


def test_evolver_components_and_authoritative_schema_use_nested_layout():
    modules = (ROOT / ".gitmodules").read_text(encoding="utf-8")
    for name in ("evolver-controller", "evolver-hardware", "evolver-server"):
        assert f"path = evolver/{name}" in modules
        assert not (ROOT / name).exists()
        assert (ROOT / "evolver" / name / ".git").exists()
    schema = ROOT / "evolver/evolver-schemas"
    assert schema.is_dir()
    assert (schema / "README.md").is_file()
    assert (schema / "instrument/schema.yaml").is_file()


def test_root_does_not_author_a_second_evolver_schema_tree():
    old = ROOT / "applications/evolver/schemas"
    assert not any(old.rglob("*.yaml")) if old.exists() else True
