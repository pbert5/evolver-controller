"""Composition contracts for the public Meta Ball test topology.

These tests intentionally inspect declarative sources and repository layout;
component behavior remains tested in its owning repository process.
"""

import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
pytestmark = pytest.mark.integration
CATALOG = ROOT / "metactl/applications/evolver/actions.json"
TEST_ROOTS = (
    "private-schema/tests",
    "integration/tests",
    "evolver/evolver-controller/tests",
    "evolver/evolver-hardware/tests",
    "evolver/evolver-server/tests",
    "metactl/tests",
    "evolver/evolver-schemas/tests",
)


def _catalog() -> dict:
    return json.loads(CATALOG.read_text())


def test_every_implemented_action_is_projected_and_bound() -> None:
    document = _catalog()
    actions = {item["id"]: item for item in document["actions"]}
    assert len(actions) == len(document["actions"]), "action IDs must be unique"
    implemented = {key for key, item in actions.items() if item["status"] == "implemented"}
    assert implemented == set(document["api"]), "implemented actions and API projection drifted"
    for action_id in implemented:
        action = actions[action_id]
        assert action["registry"]["id"] == "evolver-control"
        assert action["registry"]["binding"] == action_id
        assert action["permissions"]
        assert action["safety"]["risk"] in {"low", "medium", "high"}
        contract = document["api"][action_id]
        assert contract["method"] in {"GET", "POST", "PATCH", "DELETE"}
        placeholders = set(re.findall(r"\{([^{}]+)\}", contract["path"]))
        declared = action.get("parameters", {})
        assert placeholders <= declared.keys()
        assert all(declared[name].get("required") for name in placeholders)


def test_planned_actions_are_not_accidentally_exposed() -> None:
    document = _catalog()
    planned = {item["id"] for item in document["actions"] if item["status"] != "implemented"}
    assert not planned & set(document["api"])


def test_all_owned_test_roots_are_enrolled_in_repository_topology() -> None:
    settings = json.loads((ROOT / ".vscode/settings.json").read_text())
    assert tuple(settings["python.testing.pytestArgs"]) == TEST_ROOTS
    for relative in TEST_ROOTS:
        assert (ROOT / relative).is_dir()
    runner = (ROOT / "tools/test").read_text()
    for component in ("controller", "hardware", "server", "metactl"):
        assert component in runner


def test_hardware_safety_is_explicitly_non_physical() -> None:
    development = (ROOT / "docs/development.md").read_text().lower()
    assert "no physical hardware" in development
    assert "no node.js" in development
    assert "no physical outputs" not in development  # avoid silently weakening component policy


def test_retired_execution_and_native_deployment_identifiers_cannot_return() -> None:
    """Keep the current product boundary explicit without banning prose."""
    roots = (ROOT / "evolver/evolver-schemas", ROOT / "evolver/evolver-controller",
             ROOT / "evolver/evolver-server", ROOT / "metactl", ROOT / "docs", ROOT / "README.md")
    forbidden = ("isolated_legacy_runner", "NativePackageBackend", "NixUpdateBackend")
    for root in roots:
        paths = (root,) if root.is_file() else root.rglob("*")
        for path in paths:
            if not path.is_file() or path.suffix in {".pyc", ".lock"} or "tests" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert not any(marker in text for marker in forbidden), f"retired identifier in {path}"


def test_normalized_history_migration_declares_scientific_relations() -> None:
    migration = next((ROOT / "evolver/evolver-server/applications/deployment/databases/postgres/migrations").glob("0026_*.sql"))
    text = migration.read_text(encoding="utf-8")
    for table in ("experiment_bundles", "experiment_runs", "run_revisions", "run_events",
                  "run_measurements", "run_activities", "run_action_executions",
                  "run_telemetry", "validation_artifacts"):
        assert f"evolver.{table}" in text
