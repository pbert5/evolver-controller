"""Composition contracts for the public Meta Ball test topology.

These tests intentionally inspect declarative sources and repository layout;
component behavior remains tested in its owning repository process.
"""

import json
import re
from pathlib import Path


ROOT = Path(__file__).parents[2]
CATALOG = ROOT / "metactl/applications/evolver/actions.json"
TEST_ROOTS = (
    "private-schema/tests",
    "integration/tests",
    "evolver-controller/tests",
    "evolver-hardware/tests",
    "evolver-server/tests",
    "metactl/tests",
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
