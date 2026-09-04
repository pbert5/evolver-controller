"""Root contracts for composition between the extracted repositories.

These tests intentionally exercise the catalog/index and public projections.
Implementation behavior remains covered by the component-owned test suites.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from framework.action_catalog import load_action_catalog


ROOT = Path(__file__).parents[2]
pytestmark = pytest.mark.integration
CONTRACT = json.loads((ROOT / "integration/artifacts/root-contract-topology.json").read_text(encoding="utf-8"))
INDEX = ROOT / CONTRACT["action_catalog_index"]


def _metactl_module():
    path = ROOT / "metactl/tools/metactl.py"
    spec = importlib.util.spec_from_file_location("root_metactl_entrypoint", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # The root ``tools`` directory is also a namespace package. Put the
    # extracted metactl package first while loading its public entrypoint so
    # its sibling imports resolve to the metactl-owned transport.
    import sys
    sys.path.insert(0, str(ROOT / "metactl"))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _catalogs():
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    return index, [
        (reference["id"], load_action_catalog(INDEX.parent / reference["path"]))
        for reference in index["catalogs"]
    ]


def test_deployment_index_automatically_enrolls_every_catalog_action():
    index, catalogs = _catalogs()
    assert index["deployment_index"] == [identifier for identifier, _ in catalogs]

    enrolled = {}
    for catalog_id, catalog in catalogs:
        for action in catalog.actions:
            assert action["id"] not in enrolled, f"duplicate enrolled action: {action['id']}"
            enrolled[action["id"]] = (catalog_id, action)

    layout = _metactl_module()._layout(INDEX)
    assert set(layout["actions"]) == set(enrolled)
    assert all(entry["available"] == (entry["status"] == "implemented")
               for entry in layout["actions"].values())


def test_enrolled_operator_catalog_is_the_single_route_and_schema_source():
    _, catalogs = _catalogs()
    actions = {action["id"]: action for _, catalog in catalogs for action in catalog.actions}
    api = {action_id: contract for _, catalog in catalogs for action_id, contract in catalog.api.items()}

    assert api
    assert set(api) <= set(actions)
    for action_id, route in api.items():
        assert route["method"] in {"GET", "POST", "PATCH", "DELETE"}
        assert route["path"].startswith("/api/")
        for name in __import__("re").findall(r"\{([^{}]+)\}", route["path"]):
            assert actions[action_id]["parameters"][name].get("required") is True

    server_contract = ROOT / "evolver-server/src/meta_webui_application_backend/evolver_control/contract.py"
    source = server_contract.read_text(encoding="utf-8")
    assert 'from .actions import ACTION_ADAPTERS' in source
    assert "def operator_actions" in source
    assert "def validate_parameters" in source


def test_public_action_manifest_has_catalog_topology_without_importing_child_tests():
    _, catalogs = _catalogs()
    expected = {action_id for _, catalog in catalogs for action_id in catalog.api}
    service = ROOT / "evolver-server/src/meta_webui_application_backend/evolver_control/service.py"
    source = service.read_text(encoding="utf-8")
    assert CONTRACT["server_action_manifest_route"] in source
    assert "contract.manifest()" in source
    assert expected


def test_release_builder_artifact_contract_is_root_owned_and_explicit():
    builder = ROOT / CONTRACT["release_builder"]
    assert builder.is_file()
    source = builder.read_text(encoding="utf-8")
    for field in CONTRACT["release_manifest_required"]:
        assert json.dumps(field) in source or f'"{field}"' in source
    assert "manifest.json" in source
    assert "sha256" in source


@pytest.mark.parametrize("reference", json.loads(INDEX.read_text(encoding="utf-8"))["catalogs"])
def test_catalog_reference_stays_inside_application_topology(reference):
    applications = ROOT / CONTRACT["action_catalog_directory"]
    resolved = (INDEX.parent / reference["path"]).resolve()
    assert applications.resolve() in resolved.parents
    assert resolved.is_file()
