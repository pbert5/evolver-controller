from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import validate_schema_package as validator  # noqa: E402
from compiler import DefinitionError, compile_definition  # noqa: E402
from export_schema import export_manifest  # noqa: E402


def test_schema_package_has_preserved_foundations_and_additive_modules():
    modules = validator.load_modules(ROOT)
    assert validator.REQUIRED_MODULES <= modules.keys()
    assert modules["experiment.yaml"]["classes"]["ExperimentDefinition"]["attributes"]["definition"]["range"] == "SerializedPayload"


def test_import_graph_and_transport_boundary_are_valid():
    modules = validator.load_modules(ROOT)
    validator.validate_imports(ROOT, modules)
    validator.validate_contract(modules)


def test_experiment_purpose_is_compatible_and_action_is_declarative():
    modules = validator.load_modules(ROOT)
    values = modules["experiment.yaml"]["enums"]["ExperimentPurpose"]["permissible_values"]
    assert {"research", "test_fixture", "commissioning"} <= set(values)
    attrs = modules["experiment_program.yaml"]["classes"]["ActionInvocation"]["attributes"]
    assert "action_id" in attrs and "action_version" in attrs
    assert not validator.FORBIDDEN_ACTION_KEYS & set(attrs)


def test_compiler_is_deterministic_and_preserves_legacy_payload():
    definition = {
        "id": "demo", "purpose": "validation", "definition": {"legacy": True},
        "program": {"version": "1", "entry_step_id": "s", "steps": [{
            "id": "s", "entry_actions": [{"action_id": "capture_measurement", "action_version": "1"}],
        }]},
    }
    first = compile_definition(definition)
    second = compile_definition(definition)
    assert first["digest"] == second["digest"]
    assert first["resolved_definition"]["definition"] == {"legacy": True}
    changed = {**definition, "revision": 2}
    assert compile_definition(changed)["digest"] != first["digest"]


def test_compiler_rejects_unknown_unversioned_and_invalid_transition_actions():
    base = {"id": "demo", "purpose": "research", "program": {"version": "1", "entry_step_id": "s", "steps": [{"id": "s"}]}}
    for action in ({"action_id": "unknown", "action_version": "1"}, {"action_id": "wait"}):
        with pytest.raises(DefinitionError):
            compile_definition({**base, "program": {**base["program"], "steps": [{"id": "s", "entry_actions": [action]}]}})
    invalid = {**base, "program": {**base["program"], "steps": [{"id": "s", "transitions": [{"target_step_id": "missing", "condition": {}}]}]}}
    with pytest.raises(DefinitionError, match="unknown step"):
        compile_definition(invalid)


def test_export_manifest_is_deterministic_and_records_source_digest():
    first = export_manifest(ROOT)
    second = export_manifest(ROOT)
    assert first == second
    assert first["schema_package_version"] == "0.1.0"
    assert {item["name"] for item in first["modules"]} >= validator.REQUIRED_MODULES
    assert len(first["source_digest"]) == 64


@pytest.mark.parametrize("filename", sorted(validator.REQUIRED_MODULES))
def test_each_module_is_yaml(filename):
    document = __import__("yaml").safe_load((ROOT / "instrument" / filename).read_text())
    assert document["id"].startswith("https://w3id.org/meta-webui/evolver/")
