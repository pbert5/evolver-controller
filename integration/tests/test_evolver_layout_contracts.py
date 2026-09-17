from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
pytestmark = pytest.mark.integration


def test_parent_submodule_urls_are_exact_relative_sibling_repositories():
    expected = {
        "evolver/evolver-controller": "../evolver-controller.git",
        "evolver/evolver-hardware": "../evolver-hardware.git",
        "evolver/evolver-server": "../evolver-server.git",
        "metactl": "../metactl.git",
        "refference/meta_webui_demo": "../meta_webui_demo.git",
    }
    actual = {}
    path = None
    for line in (ROOT / ".gitmodules").read_text(encoding="utf-8").splitlines():
        if line.startswith("\tpath = "):
            path = line.removeprefix("\tpath = ")
        elif line.startswith("\turl = "):
            assert path is not None
            actual[path] = line.removeprefix("\turl = ")
    assert actual == expected
    assert all(url.startswith("../") for url in actual.values())
    assert all(not url.startswith(("/", "./", "http:", "https:")) for url in actual.values())


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
