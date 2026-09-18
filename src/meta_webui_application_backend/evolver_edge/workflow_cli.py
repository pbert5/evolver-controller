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
    "multiple_concurrent_sessions", "successful_completion", "unsupported_temperature", "waiting_for_input",
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


class ScenarioHost(WorkflowHost):
    """A WorkflowHost with an observable, side-effect-free operator fake."""

    def __init__(self, definitions: tuple[WorkflowDefinition, ...], *, input_step: bool = False,
                 unsupported: bool = False):
        self.operator = _ScenarioOperator()
        self.invocations: list[str] = []
        self.abort_count = 0
        target = TargetProjection("scenario-1", TargetKind.PHYSICAL, {"id": "scenario-controller", "generation": 1},
                                  binding={"generation": 1}, capabilities={} if unsupported else {"pump_control": {"supported": True}},
                                  connection={"state": "simulated"})
        procedures = {(item.id + ".procedure", 1): _procedure(
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
                result = session.advance()
                child = result.child
                payload = {"workflow_id": workflow_id, "session_id": self._session_id(session),
                           "state": result.state.value, "stage_id": result.stage_id, "instance_id": result.instance_id,
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
                    session.continue_stage()
            self._emit("outcome", {"workflow_id": workflow_id, "session_id": self._session_id(session),
                                    "state": session.state.value, "primary_outcome": session.error})
            return 0 if session.state is WorkflowState.SUCCEEDED else 2
        except (KeyboardInterrupt, EOFError) as interruption:
            reason = "operator cancelled" if isinstance(interruption, KeyboardInterrupt) else "input closed"
            session.abort(reason)
            if hasattr(self.host, "abort_count"):
                self.host.abort_count += 1
            self._emit("outcome", {"workflow_id": workflow_id, "session_id": self._session_id(session),
                                    "state": "aborted", "primary_outcome": reason,
                                    "cleanup_outcome": "completed"})
            return 130

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
