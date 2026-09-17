from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import validate_schema_package as validator  # noqa: E402
from compiler import DefinitionError, compile_definition, compile_program, load_definition, load_trusted_action_registry  # noqa: E402
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
    assert set(values) == {"research", "test_fixture", "commissioning", "calibration", "validation", "verification", "endurance", "diagnostic"}
    assert set(modules["experiment.yaml"]["enums"]["BundleExecutionMode"]["permissible_values"]) == {"declarative_state_machine"}
    attrs = modules["experiment_program.yaml"]["classes"]["ActionInvocation"]["attributes"]
    assert "action_id" in attrs and "action_version" in attrs
    assert not validator.FORBIDDEN_ACTION_KEYS & set(attrs)


def test_compiler_is_deterministic_and_preserves_legacy_payload():
    definition = {
        "id": "demo", "purpose": "validation", "definition": {"legacy": True},
        "program": {"version": "1", "entry_step_id": "s", "steps": [{
            "id": "s", "entry_actions": [{"action_id": "capture_measurement", "action_version": "1"}],
        }], "completion_policy": {"mode": "all_steps"}, "failure_policy": {"mode": "stop_run"}},
    }
    first = compile_definition(definition)
    second = compile_definition(definition)
    assert first["digest"] == second["digest"]
    assert first["resolved_definition"]["definition"] == {"legacy": True}
    changed = {**definition, "revision": 2}
    assert compile_definition(changed)["digest"] != first["digest"]


def test_compiler_projects_program_to_edge_state_machine_plan():
    program = {
        "version": "3", "entry_step_id": "warm", "steps": [
            {"id": "warm", "entry_actions": [{"action_id": "wait", "action_version": "1"}],
             "transitions": [{"target_step_id": "done", "condition": {
                 "operator": "eq", "operands": [{"kind": "literal", "literal": True}]}}]},
            {"id": "done"},
        ], "completion_policy": {"mode": "all_steps"},
        "failure_policy": {"mode": "stop_run"},
    }
    plan = compile_program(program)
    assert plan["initial_state"] == "warm"
    assert plan["states"]["warm"]["entry_actions"][0]["action_id"] == "wait"
    assert plan["states"]["warm"]["transitions"][0]["target_step_id"] == "done"
    bundle = compile_definition({"id": "demo", "purpose": "research", "program": program})
    assert bundle["execution_plan"] == plan


def test_compiler_rejects_unknown_unversioned_and_invalid_transition_actions():
    base = {"id": "demo", "purpose": "research", "program": {"version": "1", "entry_step_id": "s", "steps": [{"id": "s"}], "completion_policy": {"mode": "all_steps"}, "failure_policy": {"mode": "stop_run"}}}
    for action in ({"action_id": "unknown", "action_version": "1"}, {"action_id": "wait"}):
        with pytest.raises(DefinitionError):
            compile_definition({**base, "program": {**base["program"], "steps": [{"id": "s", "entry_actions": [action]}]}})
    invalid = {**base, "program": {**base["program"], "steps": [{"id": "s", "transitions": [{"target_step_id": "missing", "condition": {}}]}]}}
    with pytest.raises(DefinitionError, match="unknown step"):
        compile_definition(invalid)


def test_compiler_rejects_unknown_experiment_purpose():
    base = {"id": "demo", "purpose": "legacy", "program": {"version": "1", "entry_step_id": "s", "steps": [{"id": "s"}], "completion_policy": {"mode": "all_steps"}, "failure_policy": {"mode": "stop_run"}}}
    with pytest.raises(DefinitionError, match="purpose: unknown experiment purpose"):
        compile_definition(base)


def test_export_manifest_is_deterministic_and_records_source_digest():
    first = export_manifest(ROOT)
    second = export_manifest(ROOT)
    assert first == second
    assert first["schema_package_version"] == "0.1.0"
    assert {item["name"] for item in first["modules"]} >= validator.REQUIRED_MODULES
    assert len(first["source_digest"]) == 64
    assert any(item["name"] == "registry/trusted_actions.yaml" for item in first["modules"])


def test_trusted_action_registry_is_versioned_and_bound_to_bundle():
    registry = load_trusted_action_registry()
    assert registry["revision"] == "trusted-actions-1"
    definition = {
        "id": "registry-demo", "purpose": "research",
        "program": {"version": "1", "entry_step_id": "s", "steps": [{"id": "s", "entry_actions": [{"action_id": "wait", "action_version": "1"}]}], "completion_policy": {"mode": "all_steps"}, "failure_policy": {"mode": "stop_run"}},
    }
    assert compile_definition(definition)["action_registry_revision"] == registry["revision"]


@pytest.mark.parametrize("filename", ["calibration_temperature.yaml", "calibration_pump_flow.yaml"])
def test_schema_defined_calibration_examples_compile_through_canonical_bridge(filename):
    definition = load_definition((ROOT / "examples" / filename).read_text())
    bundle = compile_definition(definition)
    assert bundle["purpose"] == "calibration"
    assert bundle["resolved_definition"]["program"]["steps"][0]["entry_actions"]
    assert bundle["action_registry_revision"] == "trusted-actions-1"


def test_compiler_validates_conditions_random_windows_and_validation_criteria():
    definition = {
        "id": "expanded", "purpose": "validation", "validation_plan": {"criteria": [{"metric": "x", "comparator": "between", "lower_bound": 1, "upper_bound": 2}]},
        "program": {"version": "1", "entry_step_id": "s", "steps": [{"id": "s", "periodic_actions": [{"action": {"action_id": "wait", "action_version": "1"}, "trigger": {"kind": "random_window", "random_window": {"earliest": {"value": 1}, "latest": {"value": 2}, "seed": 7, "algorithm_version": "1"}}}]}], "completion_policy": {"mode": "all_steps"}, "failure_policy": {"mode": "stop_run"}},
    }
    first = compile_definition(definition)
    second = compile_definition({"program": definition["program"], "purpose": "validation", "id": "expanded", "validation_plan": definition["validation_plan"]})
    assert first["digest"] == second["digest"]
    bad = {**definition, "validation_plan": {"criteria": [{"metric": "x", "comparator": "between"}]}}
    with pytest.raises(DefinitionError, match="between"):
        compile_definition(bad)


@pytest.mark.parametrize("filename", sorted(validator.REQUIRED_MODULES))
def test_each_module_is_yaml(filename):
    document = __import__("yaml").safe_load((ROOT / "instrument" / filename).read_text())
    assert document["id"].startswith("https://w3id.org/meta-webui/evolver/")
