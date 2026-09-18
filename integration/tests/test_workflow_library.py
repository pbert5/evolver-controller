from pathlib import Path

import yaml

from evolver_procedure_runtime import ProcedureEngine, WorkflowDefinition, WorkflowLibrary, WorkflowSession, compile_procedure


ROOT = Path(__file__).parents[2]
WORKFLOW_ROOT = ROOT / "workflows" / "calibration"
DESCRIPTOR_ROOT = ROOT / "workflows" / "examples"


class PreflightOnlyInvoker:
    controller_generation = 1

    def __init__(self):
        self.invocations = []

    def describe(self, action):
        return {"id": action.id, "version": action.version, "authorized": True, "controller_generation": 1}

    def preflight(self, action, parameters):
        pass

    def invoke(self, action, parameters):
        self.invocations.append(action.id)
        raise AssertionError("workflow preflight must not invoke actions")


def _procedure_catalog():
    return {
        (document["id"], document["version"]): compile_procedure(document)
        for path in sorted(DESCRIPTOR_ROOT.glob("*.yaml"))
        for document in [yaml.safe_load(path.read_text(encoding="utf-8"))]
    }


def _example_value(spec):
    if spec["type"] == "enum":
        return spec["values"][0]
    return {"integer": 1, "number": 1.0, "string": "example", "boolean": True}[spec["type"]]


def test_calibration_workflow_manifests_compose_existing_procedures_without_side_effects():
    definitions = [WorkflowDefinition.from_mapping(yaml.safe_load(path.read_text(encoding="utf-8")), source=str(path))
                   for path in sorted(WORKFLOW_ROOT.glob("*.yaml"))]
    procedures = _procedure_catalog()
    assert {item.id for item in definitions} == {
        "calibration.temperature", "calibration.pump-flow", "calibration.optical-density.static",
        "calibration.optical-density.growth-curve",
    }
    for definition in definitions:
        invoker = PreflightOnlyInvoker()
        session = WorkflowSession(definition, ProcedureEngine(invoker), procedures)
        session.preflight({name: _example_value(spec) for name, spec in definition.parameters.items()})
        assert invoker.invocations == []
        assert any(stage.cardinality.value == "repeatable" for stage in definition.stages)
        for stage in definition.stages:
            assert (stage.procedure_id, stage.procedure_version) in procedures


def test_library_discovery_is_scoped_to_explicit_workflow_directory():
    library = WorkflowLibrary.from_directories([WORKFLOW_ROOT])
    assert [item.id for item in library.list()] == [
        "calibration.optical-density.growth-curve", "calibration.pump-flow",
        "calibration.optical-density.static", "calibration.temperature",
    ]
    assert library.search("Temperature")[0].id == "calibration.temperature"
