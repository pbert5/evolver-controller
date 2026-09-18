"""Plain, deterministic renderers and scenario fixtures for ``evoctl workflow``.

The CLI is deliberately an adapter: workflow execution remains in
``WorkflowHost`` and ``WorkflowSession``.  Scenario hosts use the same public
contracts with an in-memory operator, so tests never need a socket or device.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping

from evolver_procedure_runtime import WorkflowDefinition, WorkflowLibrary, WorkflowState, compile_procedure

from .workflow_host import HostContext, TargetKind, TargetProjection, WorkflowHost, operator_safe_stop_authority

_SENSITIVE = ("token", "secret", "password", "credential", "authorization", "private_key", "api_key")
_MAX_STRING = 512

SCENARIO_NAMES = tuple(sorted((
    "bounded_poll", "central_disconnected", "concurrent_sessions", "correction_retry_stale", "failure_cleanup",
    "instrument_disconnected", "library_browsing", "observation_required", "physical_intervention",
    "multiple_concurrent_sessions", "repeatable_calibration", "successful_completion", "unsupported_temperature",
    "waiting_for_input",
)))


def _redact(value: Any, *, key: str | None = None) -> Any:
    if key and any(part in key.casefold() for part in _SENSITIVE):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {str(name): _redact(item, key=str(name)) for name, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str) and len(value) > _MAX_STRING:
        return value[:_MAX_STRING - 1] + "…"
    return value


def jsonl_line(event: str, payload: Mapping[str, Any], *, sequence: int = 0) -> str:
    record = {"schema_version": 1, "event": event, "sequence": sequence, "payload": _redact(payload)}
    return json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"


def parse_parameters(values: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"parameter must be NAME=VALUE: {value}")
        name, raw = value.split("=", 1)
        if not name:
            raise ValueError("parameter name cannot be empty")
        try:
            result[name] = json.loads(raw)
        except json.JSONDecodeError:
            result[name] = raw
    return result


def production_host(client: Any, *, target: str, simulator: bool = False, context: Any = None,
                    repository_root: str | Path | None = None) -> WorkflowHost:
    """Build the real host from trusted local manifests and operator authority."""
    from .workflow_host import HostContext, resolve_target

    root = Path(repository_root or Path(__file__).resolve().parents[5])
    library = WorkflowLibrary.from_directories([root / "workflows" / "calibration"])
    procedures: dict[tuple[str, str | int], Any] = {}
    for path in sorted((root / "workflows" / "examples").glob("*.yaml")):
        import yaml
        procedure = compile_procedure(yaml.safe_load(path.read_text(encoding="utf-8")))
        procedures[(procedure.id, procedure.version)] = procedure
    target_projection = resolve_target(client, target, kind=TargetKind.SIMULATOR if simulator else TargetKind.PHYSICAL)
    bound_context = context or HostContext(target_identity=target)
    if bound_context.controller_generation is None:
        bound_context = replace(bound_context, controller_generation=target_projection.generation)
    return WorkflowHost(client, target=target_projection, workflows=library, procedures=procedures,
                        context=bound_context,
                        safe_stop_authority=operator_safe_stop_authority(client))


class _ScenarioOperator:
    def __init__(self) -> None:
        self.requests: list[tuple[str, Mapping[str, Any]]] = []

    def request(self, operation: str, params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        self.requests.append((operation, dict(params or {})))
        return {"status": "observed", "operation": operation}


def _definition(identifier: str, name: str, *, action: str = "wait") -> WorkflowDefinition:
    return WorkflowDefinition.from_mapping({
        "id": identifier, "name": name, "version": 1, "category": "scenario",
        "description": "deterministic CLI scenario", "parameters": {"value": {"type": "integer", "minimum": 0, "maximum": 100}},
        "requirements": {}, "stages": [{"id": "main", "procedure": {"id": identifier + ".procedure", "version": 1},
        "cardinality": "once", "bindings": {"value": {"workflow_parameter": "value"}}}],
        "metadata": {"scenario": True},
    })


def _procedure(identifier: str, *, action: str = "wait", input_step: bool = False):
    steps = []
    if input_step:
        steps.append({"id": "input", "kind": "input", "parameter": "parameter:operator_value",
                      "prompt": "operator value", "max_input_length": 32, "next_step_id": "step:action"})
    steps.extend([
        {"id": "action", "kind": "action", "action": f"action:{action}", "parameters": {}, "next_step_id": "step:done"},
        {"id": "done", "kind": "complete"},
    ])
    parameters = {"value": {"type": "integer"}}
    if input_step:
        parameters["operator_value"] = {"type": "integer"}
    return compile_procedure({"id": identifier + ".procedure", "name": identifier, "version": 1,
                              "purpose": "scenario", "parameters": parameters,
                              "entry_step_id": "step:input" if input_step else "step:action",
                              "steps": steps, "abort_actions": [], "default_timeout": 10, "metadata": {}})


def _calibration_definition() -> WorkflowDefinition:
    return WorkflowDefinition.from_mapping({
        "id": "scenario.repeatable-calibration", "name": "Repeatable Calibration", "version": 1,
        "category": "scenario", "description": "deterministic repeatable-stage calibration",
        "parameters": {}, "requirements": {},
        "stages": [
            {"id": "setup", "metadata": {"title": "Setup"},
             "procedure": {"id": "scenario.repeatable-calibration.setup", "version": 1}},
            {"id": "points", "metadata": {"title": "Calibration Points"},
             "procedure": {"id": "scenario.repeatable-calibration.points", "version": 1},
             "cardinality": "repeatable", "bindings": {
                 "reference_value": {"instance_parameter": "reference_value"},
             }},
            {"id": "review", "metadata": {"title": "Review"},
             "procedure": {"id": "scenario.repeatable-calibration.review", "version": 1}},
        ], "metadata": {"scenario": True, "repeatable_fixture": True},
    })


def _calibration_procedures() -> dict[tuple[str, str | int], Any]:
    def procedure(suffix: str, parameters: Mapping[str, Any] | None = None):
        return compile_procedure({
            "id": "scenario.repeatable-calibration." + suffix, "name": suffix.title(), "version": 1,
            "purpose": "deterministic scenario", "parameters": dict(parameters or {}),
            "entry_step_id": {"type": "step", "id": "complete"},
            "steps": [{"id": "complete", "kind": "complete"}],
            "abort_actions": [], "default_timeout": 10, "metadata": {},
        })
    return {
        ("scenario.repeatable-calibration.setup", 1): procedure("setup"),
        ("scenario.repeatable-calibration.points", 1): procedure(
            "points", {"reference_value": {"type": "number", "minimum": 0, "maximum": 100}}
        ),
        ("scenario.repeatable-calibration.review", 1): procedure("review"),
    }


class ScenarioHost(WorkflowHost):
    """A WorkflowHost with an observable, side-effect-free operator fake."""

    def __init__(self, definitions: tuple[WorkflowDefinition, ...], *, input_step: bool = False,
                 unsupported: bool = False, procedures: Mapping[tuple[str, str | int], Any] | None = None):
        self.operator = _ScenarioOperator()
        self.invocations: list[str] = []
        self.abort_count = 0
        target = TargetProjection("scenario-1", TargetKind.PHYSICAL, {"id": "scenario-controller", "generation": 1},
                                  binding={"generation": 1}, capabilities={} if unsupported else {"pump_control": {"supported": True}},
                                  connection={"state": "simulated"})
        procedures = procedures or {(item.id + ".procedure", 1): _procedure(
            item.id, action="set_temperature" if unsupported else "wait", input_step=input_step
        ) for item in definitions}
        super().__init__(self.operator, target=target, workflows=WorkflowLibrary(definitions), procedures=procedures,
                         context=HostContext(operator="scenario", target_identity="scenario-1"))


class ScenarioRegistry:
    """Stable named fixtures consumed by product tests and preview tooling."""

    def names(self) -> tuple[str, ...]:
        return SCENARIO_NAMES

    def host(self, name: str) -> ScenarioHost:
        if name not in SCENARIO_NAMES:
            raise KeyError(f"unknown scenario: {name}")
        if name == "library_browsing":
            definitions = (_definition("scenario.calibration.a", "Calibration A"),
                           _definition("scenario.calibration.b", "Calibration B"))
        elif name == "waiting_for_input":
            definitions = (_definition("scenario.input", "Input Scenario"),)
        elif name == "unsupported_temperature":
            definitions = (_definition("scenario.temperature", "Temperature Scenario", action="set_temperature"),)
        elif name == "repeatable_calibration":
            definitions = (_calibration_definition(),)
            return ScenarioHost(definitions, procedures=_calibration_procedures())
        else:
            definitions = (_definition("scenario." + name, name.replace("_", " ").title()),)
        return ScenarioHost(definitions, input_step=name == "waiting_for_input", unsupported=name == "unsupported_temperature")


class WorkflowCLI:
    def __init__(self, host: WorkflowHost, *, output: Any, jsonl: bool = False,
                 input_reader: Callable[[str], str] | None = None):
        self.host, self.output, self.jsonl = host, output, jsonl
        self.input_reader = input_reader or input
        self._sequence = 0

    def _emit(self, event: str, payload: Mapping[str, Any]) -> None:
        if self.jsonl:
            self.output.write(jsonl_line(event, payload, sequence=self._sequence))
            self._sequence += 1
        else:
            self.output.write(str(dict(payload)) + "\n")

    def list_workflows(self) -> int:
        for item in self.host.list_workflows():
            self.output.write(f"{item.id}@{item.version}\t{item.category}\t{item.name}\n")
        return 0

    def show_workflow(self, workflow_id: str) -> int:
        item = self.host.show_workflow(workflow_id)
        self.output.write(f"{item.name} ({item.id}@{item.version})\n{item.description}\nstages:\n")
        for stage in item.stages:
            self.output.write(f"  - {stage.id}: {stage.procedure_id}@{stage.procedure_version} [{stage.cardinality.value}]\n")
        return 0

    def preflight(self, workflow_id: str, parameters: Mapping[str, Any] | None = None) -> int:
        definition = self.host.show_workflow(workflow_id)
        try:
            self.host.preflight(definition, parameters)
        except Exception as error:
            self._emit("preflight", {"workflow_id": workflow_id, "state": "failed", "error": str(error)})
            return 2
        self._emit("preflight", {"workflow_id": workflow_id, "state": "preflighted", "actions_invoked": 0})
        return 0

    def run(self, workflow_id: str, parameters: Mapping[str, Any] | None = None) -> int:
        definition = self.host.show_workflow(workflow_id)
        session = self.host.new_session(definition)
        try:
            session.preflight(parameters)
            while session.state not in {WorkflowState.SUCCEEDED, WorkflowState.FAILED, WorkflowState.ABORTED}:
                if session.active_stage_id and session.active_instance_id is None:
                    if not self._choose_repeatable_instance(session):
                        continue
                    if session.state in {WorkflowState.SUCCEEDED, WorkflowState.FAILED, WorkflowState.ABORTED}:
                        break
                result = session.advance()
                child = result.child
                stage_title = None
                if result.stage_id is not None:
                    stage_title = self.host.project_stage_instances(session, result.stage_id).title
                payload = {"workflow_id": workflow_id, "session_id": self._session_id(session),
                           "state": result.state.value, "stage_id": result.stage_id, "stage_title": stage_title,
                           "instance_id": result.instance_id,
                           "procedure_state": child.state.value if child else None,
                           "attention": session.attention, "error": result.error}
                self._emit("transition", payload)
                if child and child.input_parameter:
                    value = self.input_reader(child.input_prompt or child.input_parameter)
                    spec = session.instances[result.stage_id][0].procedure_session.procedure.parameters.get(child.input_parameter, {})
                    if isinstance(spec, Mapping) and spec.get("type") == "integer":
                        value = int(value)
                    elif isinstance(spec, Mapping) and spec.get("type") == "number":
                        value = float(value)
                    session.engine.provide_parameter(session.instances[result.stage_id][0].procedure_session,
                                                     child.input_parameter, value)
                if result.state is WorkflowState.STAGE_COMPLETE:
                    stage_projection = self.host.project_stage_instances(session, result.stage_id)
                    if stage_projection.cardinality == "repeatable":
                        self._choose_repeatable_instance(session)
                    else:
                        session.continue_stage()
            self._emit("outcome", {"workflow_id": workflow_id, "session_id": self._session_id(session),
                                    "state": session.state.value, "primary_outcome": session.error})
            return (0 if session.state is WorkflowState.SUCCEEDED else
                    130 if session.state is WorkflowState.ABORTED else 2)
        except (KeyboardInterrupt, EOFError) as interruption:
            reason = "operator cancelled" if isinstance(interruption, KeyboardInterrupt) else "input closed"
            session.abort(reason)
            if hasattr(self.host, "abort_count"):
                self.host.abort_count += 1
            self._emit("outcome", {"workflow_id": workflow_id, "session_id": self._session_id(session),
                                    "state": "aborted", "primary_outcome": reason,
                                    "cleanup_outcome": "completed"})
            return 130

    def _choose_repeatable_instance(self, session: Any) -> bool:
        """Handle the explicit add/continue boundary for an empty repeatable stage."""
        projection = self.host.project_stage_instances(session, session.active_stage_id)
        if not projection.can_add:
            raise ValueError(f"active stage cannot accept an instance: {projection.stage_id}")
        self._emit("stage_instance_prompt", {
            "stage_id": projection.stage_id, "title": projection.title,
            "cardinality": projection.cardinality,
            "existing_instance_ids": [item["id"] for item in projection.instances],
            "choices": ["add", "continue", "abort"],
            "parameters": [{"name": item.name, "type": item.schema.get("type"), "required": item.required}
                           for item in projection.parameters],
        })
        choice = self.input_reader(
            f"{projection.title} [A] Add point [C] Continue to next stage [Q] Abort: "
        ).strip().casefold()
        if choice in {"q", "quit", "abort"}:
            session.abort("operator cancelled")
            if hasattr(self.host, "abort_count"):
                self.host.abort_count += 1
            return True
        if choice in {"c", "continue"}:
            session.continue_stage()
            return True
        if choice not in {"a", "add", "point"}:
            self._emit("stage_instance_error", {"stage_id": projection.stage_id,
                                                  "error": "choose add, continue, or abort"})
            return False
        values: dict[str, Any] = {}
        try:
            for parameter in projection.parameters:
                raw = self.input_reader(f"{parameter.name} ({parameter.schema.get('type', 'value')}): ")
                values[parameter.name] = self._coerce_input(raw, parameter.schema)
            created = self.host.add_stage_instance(session, projection.stage_id, values)
        except (ValueError, TypeError) as error:
            self._emit("stage_instance_error", {"stage_id": projection.stage_id, "error": str(error)})
            return False
        self._emit("stage_instance_created", {
            "stage_id": created.stage_id, "instance_id": created.instances[-1]["id"],
            "instance_count": len(created.instances), "actions_invoked": 0,
        })
        return False

    @staticmethod
    def _coerce_input(raw: str, schema: Mapping[str, Any]) -> Any:
        expected = schema.get("type")
        try:
            if expected == "integer":
                return int(raw)
            if expected == "number":
                return float(raw)
            if expected == "boolean":
                lowered = raw.strip().casefold()
                if lowered in {"true", "yes", "y", "1"}:
                    return True
                if lowered in {"false", "no", "n", "0"}:
                    return False
                raise ValueError("boolean value must be true or false")
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid {expected} value: {raw}") from error
        return raw

    @staticmethod
    def _session_id(session: Any) -> str:
        if session.active_stage_id and session.active_instance_id:
            return session.instances[session.active_stage_id][0].procedure_session.run_id
        for instances in session.instances.values():
            for instance in instances:
                run_id = getattr(instance.procedure_session, "run_id", None)
                if run_id:
                    return run_id
        return "workflow-session"
