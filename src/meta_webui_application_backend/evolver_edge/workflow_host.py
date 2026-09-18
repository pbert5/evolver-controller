"""The controller-owned bridge between workflow runtime and operator authority.

This module is intentionally transport boring: it never opens a device, reads
the edge store, or turns a trusted action name into a second hardware API.
Physical work is sent through ``OperatorClient`` and all other authorities are
injected by the host application.
"""
from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from evolver_procedure_runtime import (
    ActionInvocation,
    ActionRef,
    CheckpointDestination,
    MutationOutcome,
    PollResult,
    Procedure,
    ProcedureEngine,
    SinkRequest,
    WorkflowDefinition,
    WorkflowLibrary,
    WorkflowSession,
    WorkflowState,
    WorkflowError,
    SessionState,
)

from .operator import OperatorClient, OperatorError


class TargetKind(str, Enum):
    PHYSICAL = "physical"
    SIMULATOR = "simulator"


class Availability(str, Enum):
    AVAILABLE = "available"
    READ_ONLY_AVAILABLE = "read_only_available"
    SIMULATOR_ONLY = "simulator_only"
    BLOCKED_DEPENDENCY = "blocked_dependency"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class TargetProjection:
    """Read-only target/connection/capability evidence used by preflight."""

    identity: str
    kind: TargetKind
    controller: Mapping[str, Any]
    instrument: Mapping[str, Any] = field(default_factory=dict)
    binding: Mapping[str, Any] = field(default_factory=dict)
    capabilities: Mapping[str, Any] = field(default_factory=dict)
    connection: Mapping[str, Any] = field(default_factory=dict)
    lease: Mapping[str, Any] = field(default_factory=dict)
    telemetry: Mapping[str, Any] = field(default_factory=dict)
    instrument_id: str | None = None

    @property
    def generation(self) -> int | None:
        value = self.binding.get("generation", self.controller.get("generation"))
        return value if type(value) is int else None


@dataclass(frozen=True)
class ActionAvailability:
    action: str
    version: str | int
    classification: Availability
    reason: str
    provenance: Mapping[str, Any]
    route: str | None = None


@dataclass(frozen=True)
class ActionProjection:
    """One semantic projection for Step/Action/API/CLI/Raw renderers."""

    step: Mapping[str, Any]
    action: Mapping[str, Any]
    api: Mapping[str, Any]
    cli: str | None
    raw: Mapping[str, Any]
    availability: ActionAvailability


@dataclass(frozen=True)
class StageInstanceParameter:
    """One operator-created parameter exposed by a repeatable stage."""

    name: str
    procedure_parameter: str
    schema: Mapping[str, Any]
    required: bool


@dataclass(frozen=True)
class StageInstanceProjection:
    """Shared session projection for CLI and future TUI stage controls."""

    stage_id: str
    title: str
    cardinality: str
    can_add: bool
    parameters: tuple[StageInstanceParameter, ...]
    instances: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class HostContext:
    operator: str | None = None
    lease_token: str | None = None
    lease_owner: str | None = None
    controller_generation: int | None = None
    physical: bool = False
    target_identity: str | None = None


class CentralObservation(Protocol):
    def __call__(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...


class CheckpointWriter(Protocol):
    def __call__(self, request: SinkRequest, destination: CheckpointDestination) -> MutationOutcome: ...


class SafeStopAuthority(Protocol):
    def __call__(self, *, target: TargetProjection, context: HostContext, command_id: str) -> Mapping[str, Any]: ...


def coerce_input(raw: Any, schema: Mapping[str, Any]) -> Any:
    """Canonical bounded conversion for CLI and rendered operator inputs."""
    expected = schema.get("type")
    if not isinstance(raw, str):
        value = raw
    elif expected == "integer":
        try:
            value = int(raw.strip())
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid integer value: {raw}") from error
    elif expected == "number":
        try:
            value = float(raw.strip())
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid number value: {raw}") from error
    elif expected == "boolean":
        lowered = raw.strip().casefold()
        if lowered in {"true", "yes", "y", "1"}:
            value = True
        elif lowered in {"false", "no", "n", "0"}:
            value = False
        else:
            raise ValueError(f"boolean value must be true or false: {raw}")
    else:
        value = raw
    if "values" in schema and value not in schema["values"]:
        raise ValueError(f"invalid value: {value}")
    if "minimum" in schema and value < schema["minimum"]:
        raise ValueError(f"value is below minimum: {value}")
    if "maximum" in schema and value > schema["maximum"]:
        raise ValueError(f"value is above maximum: {value}")
    return value


def operator_safe_stop_authority(client: OperatorClient) -> SafeStopAuthority:
    """Build the production safe-stop authority from the typed operator API."""
    def stop(*, target: TargetProjection, context: HostContext, command_id: str) -> Mapping[str, Any]:
        if context.physical is not True or not context.operator:
            raise PermissionError("physical opt-in and operator attribution are required")
        target_generation = target.generation
        context_generation = context.controller_generation
        if (type(target_generation) is not int or target_generation <= 0 or
                type(context_generation) is not int or context_generation <= 0):
            raise PermissionError("positive controller generations are required")
        if context_generation != target_generation:
            raise PermissionError("controller generation is stale")
        result = client.safe_stop(operator=context.operator, physical=True, command_id=command_id)
        if not isinstance(result, Mapping):
            raise OperatorError("safe-stop authority returned an invalid result", kind="invalid_response")
        return {"status": "accepted", "evidence": "protocol_ack", "authority_result": dict(result),
                "physical_cessation": "not_verified", "command_id": command_id}
    return stop


_VERSIONS = {"1", "1.0", 1}
_TRUSTED_ACTIONS = (
    "set_temperature", "set_stirring", "pulse_pump", "run_pump", "stop_actuator",
    "capture_measurement", "wait", "start_activity", "stop_activity",
    "request_observation", "evaluate_criteria", "emit_marker", "complete_run", "fail_run",
)


class ProcedureActionInvoker:
    """Frozen-runtime invoker backed by the typed operator protocol."""

    def __init__(self, client: OperatorClient, target: TargetProjection, *, context: HostContext,
                 safe_stop_authority: SafeStopAuthority | None = None):
        self.client, self.target, self.context = client, target, context
        self.safe_stop_authority = safe_stop_authority
        self._pending: dict[str, PollResult] = {}

    def availability(self, action: ActionRef | str, parameters: Mapping[str, Any] | None = None) -> ActionAvailability:
        action_id, version = _action_parts(action)
        provenance = {"target": self.target.identity, "target_kind": self.target.kind.value,
                      "capabilities": dict(self.target.capabilities), "controller_generation": self.target.generation}
        if action_id == "set_temperature":
            if self.target.kind is TargetKind.SIMULATOR:
                return ActionAvailability(action_id, version, Availability.SIMULATOR_ONLY,
                                          "logical temperature control is simulator-only", provenance)
            return ActionAvailability(action_id, version, Availability.UNSUPPORTED,
                                      "#58: physical temperature_setpoint authority is unsupported", provenance)
        if action_id == "set_stirring":
            return ActionAvailability(action_id, version, Availability.UNSUPPORTED,
                                      "trusted stirring target is not equivalent to bounded set_stir", provenance)
        if action_id in {"pulse_pump", "run_pump"}:
            capability = self.target.capabilities.get("pump_control", {})
            if isinstance(capability, Mapping) and capability.get("supported") is True:
                return ActionAvailability(action_id, version, Availability.AVAILABLE,
                                          "bounded pump pulse via OperatorClient hardware authority", provenance,
                                          "operator.hardware.hardware_command")
            return ActionAvailability(action_id, version, Availability.UNSUPPORTED,
                                      "target does not report a supported pump_control capability", provenance)
        if action_id == "stop_actuator":
            if self.safe_stop_authority is not None:
                return ActionAvailability(action_id, version, Availability.AVAILABLE,
                                          "dedicated #47 safe-stop authority", {**provenance, "dependency": "#47"},
                                          "operator.safe_stop")
            return ActionAvailability(action_id, version, Availability.BLOCKED_DEPENDENCY,
                                      "#47 safe-stop authority is not integrated", {**provenance, "dependency": "#47"})
        if action_id in {"capture_measurement", "request_observation"}:
            return ActionAvailability(action_id, version, Availability.READ_ONLY_AVAILABLE,
                                      "read-only observation through operator authority", provenance,
                                      "operator.instrument")
        if action_id in {"wait", "evaluate_criteria", "emit_marker"}:
            return ActionAvailability(action_id, version, Availability.AVAILABLE,
                                      "session-local runtime projection", provenance, "runtime.local")
        if action_id in {"start_activity", "stop_activity", "complete_run", "fail_run"}:
            return ActionAvailability(action_id, version, Availability.UNSUPPORTED,
                                      "domain run/activity authority is not exposed by the operator contract", provenance)
        return ActionAvailability(action_id, version, Availability.UNSUPPORTED,
                                  "trusted action has no host realization", provenance)

    @property
    def controller_generation(self) -> int | None:
        """Expose the target fence required by runtime cleanup coordination."""
        return self.target.generation

    def describe(self, action: ActionRef | str) -> Mapping[str, Any]:
        """Return the same authorization/fence projection used by preflight."""
        action_id, version = _action_parts(action)
        availability = self.availability(action)
        return {
            "id": action_id,
            "version": version,
            "authorized": availability.classification not in {
                Availability.UNSUPPORTED, Availability.BLOCKED_DEPENDENCY,
            },
            "controller_generation": self.controller_generation,
        }

    def preflight(self, action: ActionRef | str, parameters: dict[str, Any]) -> None:
        action_id, version = _action_parts(action)
        if action_id not in _TRUSTED_ACTIONS:
            raise ValueError(f"unknown trusted action: {action_id}")
        if version not in _VERSIONS:
            raise ValueError(f"unsupported action version: {action_id}@{version}")
        availability = self.availability(action, parameters)
        if availability.classification in {Availability.UNSUPPORTED, Availability.BLOCKED_DEPENDENCY}:
            raise ValueError(f"{action_id}: {availability.classification.value}: {availability.reason}")
        if availability.classification is Availability.SIMULATOR_ONLY and self.target.kind is not TargetKind.SIMULATOR:
            raise ValueError(f"{action_id}: simulator-only action on physical target")

    def invoke(self, action: ActionRef | str, parameters: dict[str, Any]) -> ActionInvocation:
        self.preflight(action, parameters)
        action_id, _ = _action_parts(action)
        token = str(uuid4())
        if action_id in {"wait", "evaluate_criteria", "emit_marker", "start_activity", "stop_activity",
                         "complete_run", "fail_run"}:
            result = PollResult(True, True, {"status": "accepted", "evidence": "session_local", "action": action_id})
        elif action_id == "set_temperature" and self.target.kind is TargetKind.SIMULATOR:
            value = parameters.get("target_temperature_c", parameters.get("target", parameters.get("temperature_c")))
            if type(value) not in {int, float} or not 0 <= value <= 100:
                result = PollResult(True, False, error="temperature target must be numeric in 0..100 °C")
            else:
                result = PollResult(True, True, {"status": "simulated", "evidence": "simulated", "parameters": dict(parameters)})
        elif action_id in {"capture_measurement", "request_observation"}:
            result = self._observe()
        elif action_id == "stop_actuator":
            try:
                result = PollResult(True, True, self.safe_stop_authority(
                    target=self.target, context=self.context, command_id=token))
            except Exception as error:
                result = PollResult(True, False, error=str(error))
        else:
            result = self._invoke_operator(action_id, parameters, token)
        self._pending[token] = result
        return ActionInvocation(token)

    def poll(self, invocation: ActionInvocation) -> PollResult:
        try:
            return self._pending.pop(invocation.token)
        except KeyError as error:
            raise ValueError("unknown or already-consumed action invocation") from error

    def _observe(self) -> PollResult:
        try:
            instrument_id = self.target.instrument_id or self.context.target_identity
            if instrument_id:
                value = self.client.request("instrument", {"instrument_id": instrument_id})
            else:
                value = self.client.request("instruments")
        except OperatorError as error:
            return PollResult(True, False, error=str(error))
        return PollResult(True, True, {"status": "observed", "evidence": "operator_read_only", "value": value})

    def _invoke_operator(self, action_id: str, parameters: Mapping[str, Any], token: str) -> PollResult:
        if self.target.kind is TargetKind.SIMULATOR:
            return PollResult(True, False, error=f"{action_id} has no simulator adapter")
        if self.context.physical is not True or not self.context.operator:
            return PollResult(True, False, error="physical opt-in and operator attribution are required")
        if self.context.lease_token is None or self.context.lease_owner != self.context.operator:
            return PollResult(True, False, error="active operator lease is required")
        if self.context.controller_generation != self.target.generation:
            return PollResult(True, False, error="controller generation is stale")
        duration = parameters.get("duration_ms", parameters.get("pulse_duration_ms"))
        channel = parameters.get("channel", 0)
        if type(channel) is not int or not 0 <= channel <= 5:
            return PollResult(True, False, error="pump channel must be an integer in 0..5")
        if type(duration) is not int or not 1 <= duration <= 1000:
            return PollResult(True, False, error="pump duration_ms must be an integer in 1..1000")
        payload = {"operation": "hardware", "params": {
            "operation": "hardware_command", "operation_name": "pulse_pump",
            "target_identity": self.target.identity,
            "parameters": {"channel": channel, "direction": parameters.get("direction", "forward"), "duration_ms": duration},
            "controller_generation": self.context.controller_generation,
            "lease_token": self.context.lease_token, "lease_owner": self.context.lease_owner,
            "physical": True, "command_id": token, "operator": self.context.operator,
        }}
        try:
            value = self.client.request(payload["operation"], payload["params"])
        except OperatorError as error:
            return PollResult(True, False, error=str(error))
        return PollResult(True, True, {"status": "accepted", "evidence": "protocol_ack", "authority_result": value})


class WorkflowHost:
    """Production host facade consumed by CLI/TUI and future API renderers."""

    def __init__(self, client: OperatorClient, *, target: TargetProjection,
                 workflows: WorkflowLibrary, procedures: Mapping[tuple[str, str | int], Procedure],
                 context: HostContext, central_observation: CentralObservation | None = None,
                 checkpoint_writer: CheckpointWriter | None = None,
                 safe_stop_authority: SafeStopAuthority | None = None):
        self.client, self.target, self.workflows, self.procedures = client, target, workflows, dict(procedures)
        self.context = context
        self.invoker = ProcedureActionInvoker(client, target, context=context,
                                              safe_stop_authority=safe_stop_authority)
        self.central_observation = central_observation
        self.checkpoint_writer = checkpoint_writer

    def list_workflows(self) -> tuple[WorkflowDefinition, ...]:
        return self.workflows.list()

    def show_workflow(self, workflow_id: str, version: str | int | None = None) -> WorkflowDefinition:
        return self.workflows.get(workflow_id, version)

    def search_workflows(self, text: str) -> tuple[WorkflowDefinition, ...]:
        return self.workflows.search(text)

    def new_session(self, definition: WorkflowDefinition) -> WorkflowSession:
        return WorkflowSession(definition, ProcedureEngine(self.invoker), self.procedures)

    @staticmethod
    def coerce_input(raw: Any, schema: Mapping[str, Any]) -> Any:
        """Use the CLI's bounded textual input contract for rendered forms."""
        return coerce_input(raw, schema)

    def coerce_session_input(self, session: WorkflowSession, name: str, raw: Any) -> Any:
        """Coerce a UI value using the active procedure parameter schema."""
        if session.active_stage_id and session.active_instance_id:
            instance = next(item for item in session.instances[session.active_stage_id]
                            if item.id == session.active_instance_id)
            schema = instance.procedure_session.procedure.parameters.get(name, {})
            if isinstance(schema, Mapping):
                return self.coerce_input(raw, schema)
        schema = session.definition.parameters.get(name, {})
        return self.coerce_input(raw, schema if isinstance(schema, Mapping) else {})

    def can_abort(self, session: WorkflowSession) -> bool:
        """Report whether the active runtime has an authorized safe abort path."""
        if session.state in {WorkflowState.CREATED, WorkflowState.SUCCEEDED,
                             WorkflowState.FAILED, WorkflowState.ABORTED}:
            return True
        if not session.active_stage_id or not session.active_instance_id:
            return False
        instance = next(item for item in session.instances[session.active_stage_id]
                        if item.id == session.active_instance_id)
        return all(self.invoker.availability(action).classification not in {
            Availability.UNSUPPORTED, Availability.BLOCKED_DEPENDENCY,
        } for action in instance.procedure_session.procedure.abort_actions)

    def _project_template_step(self, stage_id: str, procedure: Procedure, step: Any,
                               *, status: str = "READY") -> dict[str, Any]:
        """Project a trusted procedure step without creating a runtime instance."""
        kind = getattr(getattr(step, "kind", None), "value", getattr(step, "kind", "unknown"))
        step_data: dict[str, Any] = {
            "id": step.id, "step_id": step.id, "stage_id": stage_id,
            "procedure_id": procedure.id, "title": step.prompt or step.id,
            "kind": kind, "status": status,
        }
        if step.input_ref:
            spec = procedure.parameters.get(step.input_ref.id, {})
            step_data["input"] = {"name": step.input_ref.id, **dict(spec)}
        if step.action_ref:
            action = self.project_action(step=step_data, action=step.action_ref,
                                         parameters=step.parameters)
            step_data["representation"] = {
                "Step": step_data["title"], "Action": action.action,
                "API": action.api, "CLI": action.cli or "Not available", "Raw": action.raw,
            }
        else:
            reason = f"Not applicable: {kind} steps do not declare an action"
            step_data["representation"] = {
                "Step": step_data["title"], "Action": reason, "API": reason,
                "CLI": reason, "Raw": {"id": step.id, "kind": kind, "status": status},
            }
        return step_data

    def project_session_for_ui(self, session: WorkflowSession,
                               inspection: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        """Build the authoritative rich session projection consumed by renderers."""
        active_stage = session.active_stage_id
        active_instance = session.active_instance_id
        stages: list[dict[str, Any]] = []
        selected_step = None
        representations: Mapping[str, Any] = {}
        correction: dict[str, Any] = {}
        history: list[Mapping[str, Any]] = []
        requested = dict(inspection or {})
        first_inspection: dict[str, Any] = {}
        runtime_inspection: dict[str, Any] = {}
        for stage in session.definition.stages:
            procedure = self.procedures.get((stage.procedure_id, stage.procedure_version))
            if procedure is None:
                raise WorkflowError(f"unable to resolve trusted procedure {stage.procedure_id}@{stage.procedure_version} for stage {stage.id}")
            stage_projection = self.project_stage_instances(session, stage.id)
            stage_data: dict[str, Any] = {
                "id": stage.id, "title": stage_projection.title,
                "cardinality": stage_projection.cardinality, "can_add": stage_projection.can_add,
                "status": "CURRENT" if stage.id == active_stage else "READY",
                "parameters": [{"name": item.name, "type": item.schema.get("type"),
                                "required": item.required, **dict(item.schema)}
                               for item in stage_projection.parameters],
                "instances": [], "steps": [],
            }
            for item in session.instances[stage.id]:
                procedure_session = item.procedure_session
                current = procedure_session.current_step_id
                attempts = procedure_session.attempt_history
                attempt_by_step = {attempt.step_id: attempt for attempt in attempts}
                steps: list[dict[str, Any]] = []
                for step in procedure_session.procedure.steps:
                    attempt = attempt_by_step.get(step.id)
                    status = "CURRENT" if item.id == active_instance and step.id == current else "READY"
                    if attempt and attempt.status in {"stale", "superseded"}:
                        status = attempt.status.upper()
                    elif attempt and attempt.status == "completed":
                        status = "COMPLETED"
                    if item.id == active_instance and step.id == current and session.attention:
                        status = "ATTENTION"
                    step_data = self._project_template_step(stage.id, procedure_session.procedure, step, status=status)
                    step_data["instance_id"] = item.id
                    if item.id == active_instance and step.id == current:
                        representations = step_data["representation"]
                        runtime_inspection = {"stage_id": stage.id, "instance_id": item.id,
                                              "procedure_id": procedure.id, "step_id": step.id}
                    steps.append(step_data)
                    if step.id == current and item.id == active_instance:
                        selected_step = step.id
                        correction = {"legal": step.correction.replaceable,
                                      "kind": step.correction.kind,
                                      "actions": (["Correct/redo value"] if step.correction.replaceable else [])}
                history.extend({"step_id": attempt.step_id, "attempt": attempt.number,
                                "status": attempt.status, "result": attempt.result}
                               for attempt in attempts)
                stage_data["instances"].append({"id": item.id,
                    "title": f"{stage_projection.title} {item.id.rsplit('-', 1)[-1]}",
                    "status": "COMPLETED" if item.completed else "CURRENT" if item.id == active_instance else "READY",
                    "parameters": dict(item.parameters), "steps": steps})
            if stage_data["instances"]:
                stage_data["steps"] = stage_data["instances"][0]["steps"]
            else:
                stage_data["steps"] = [self._project_template_step(stage.id, procedure, step)
                                        for step in procedure.steps]
            if stage_data["steps"] and not first_inspection:
                first = stage_data["steps"][0]
                first_inspection = {"stage_id": stage.id, "procedure_id": procedure.id,
                                    "step_id": first["step_id"]}
            stages.append(stage_data)
        selected_stage = requested.get("stage_id")
        selected_step_id = requested.get("step_id")
        selected_data = None
        if selected_stage and selected_step_id:
            for stage in stages:
                if stage["id"] != selected_stage:
                    continue
                requested_instance = requested.get("instance_id")
                candidates = ([] if requested_instance else list(stage.get("steps", ())))
                for instance in stage.get("instances", ()):
                    if requested_instance is None or instance.get("id") == requested_instance:
                        candidates.extend(instance.get("steps", ()))
                selected_data = next((item for item in candidates if item.get("step_id") == selected_step_id), None)
                if selected_data:
                    break
        if selected_data is None and not requested and runtime_inspection:
            for stage in stages:
                if stage["id"] != runtime_inspection["stage_id"]:
                    continue
                for instance in stage.get("instances", ()):
                    if instance.get("id") == runtime_inspection["instance_id"]:
                        selected_data = next((item for item in instance.get("steps", ())
                                              if item.get("step_id") == runtime_inspection["step_id"]), None)
                        break
        if selected_data is None:
            selected_data = next((item for stage in stages for item in stage.get("steps", ())
                                  if item.get("step_id") == selected_step), None)
        if selected_data is None:
            selected_data = next((item for stage in stages for item in stage.get("steps", ())), None)
        if selected_data is not None:
            selected_step = selected_data["step_id"]
            representations = selected_data.get("representation", {})
            first_inspection = {"stage_id": selected_data.get("stage_id"),
                                "procedure_id": selected_data.get("procedure_id"),
                                "step_id": selected_data.get("step_id")}
            if selected_data.get("instance_id"):
                first_inspection["instance_id"] = selected_data["instance_id"]
        current_schema = ()
        if active_stage and active_instance:
            instance = next(item for item in session.instances[active_stage] if item.id == active_instance)
            step = next((item for item in instance.procedure_session.procedure.steps
                         if item.id == instance.procedure_session.current_step_id), None)
            if step and step.input_ref:
                spec = instance.procedure_session.procedure.parameters.get(step.input_ref.id, {})
                current_schema = ({"name": step.input_ref.id, "label": step.prompt or step.input_ref.id,
                                  **dict(spec)},)
        state = session.state.value.upper()
        attention = {"WAITING_INPUT": ("input",), "WAITING_CONDITION": ("choice",)}.get(state, ())
        return {"workflow_id": session.definition.id, "title": session.definition.name,
                "status": state, "attention": attention, "progress":
                f"{sum(1 for stage in session.instances.values() for item in stage if item.completed)} / {len(session.definition.stages)}",
                "lease": "ACTIVE" if self.context.lease_token else "UNBOUND",
                "procedures": tuple(stages), "selected_step": selected_step,
                "inspection": first_inspection,
                "representations": representations, "drawer": {"Input schema": current_schema,
                    "Info": {"workflow": session.definition.name, "state": state},
                    "Inputs": dict(session.parameters), "Safety": {"target": self.target.identity,
                        "capabilities": dict(self.target.capabilities), "abort_supported": self.can_abort(session)},
                    "Evidence": dict(self.target.telemetry), "Outputs": {}, "Events": history},
                "metadata": {"target": self.target.identity, "connectivity": self.target.connection.get("state", "unknown"),
                    "controller": dict(self.target.controller), "instrument": dict(self.target.instrument),
                    "central": dict(self.target.telemetry), "history": history}, "correction": correction}

    def preflight(self, definition: WorkflowDefinition, parameters: Mapping[str, Any] | None = None) -> WorkflowSession:
        session = self.new_session(definition)
        session.preflight(parameters)
        return session

    def project_action(self, *, step: Mapping[str, Any], action: ActionRef | str,
                       parameters: Mapping[str, Any] | None = None) -> ActionProjection:
        params = dict(parameters or {})
        availability = self.invoker.availability(action, params)
        action_id, version = _action_parts(action)
        raw = {"id": action_id, "version": version, "parameters": params}
        api = {"route": availability.route, "action_id": action_id, "version": version,
               "target": self.target.identity, "parameters": params}
        cli = None
        if availability.route:
            cli = f"evoctl action run {action_id} --target {shlex.quote(self.target.identity)}"
            if params:
                cli += f" --parameters {shlex.quote(json.dumps(params, sort_keys=True, separators=(',', ':')))}"
        return ActionProjection(dict(step), {"id": action_id, "version": version}, api, cli, raw, availability)

    def project_stage_instances(self, session: WorkflowSession, stage_id: str) -> StageInstanceProjection:
        """Project one stage without exposing runtime internals to renderers."""
        stage = next((item for item in session.definition.stages if item.id == stage_id), None)
        if stage is None:
            raise WorkflowError(f"unknown workflow stage: {stage_id}")
        procedure = self.procedures.get((stage.procedure_id, stage.procedure_version))
        if procedure is None:
            raise WorkflowError(f"unknown procedure reference: {stage.procedure_id}@{stage.procedure_version}")
        parameters: list[StageInstanceParameter] = []
        for procedure_parameter, binding in stage.bindings.items():
            if set(binding) != {"instance_parameter"}:
                continue
            name = binding["instance_parameter"]
            schema = procedure.parameters.get(procedure_parameter)
            if not isinstance(name, str) or not isinstance(schema, Mapping):
                raise WorkflowError(f"invalid instance parameter binding: {stage_id}.{procedure_parameter}")
            parameters.append(StageInstanceParameter(
                name=name, procedure_parameter=procedure_parameter, schema=dict(schema),
                required=schema.get("required", True) is not False,
            ))
        instances = tuple(
            {"id": instance.id,
             "status": "completed" if instance.completed else "active" if (
                 session.active_stage_id == stage_id and session.active_instance_id == instance.id
             ) else "ready",
             "parameters": dict(instance.parameters)}
            for instance in session.instances[stage_id]
        )
        return StageInstanceProjection(
            stage_id=stage.id,
            title=str(stage.metadata.get("title", stage.id.replace("_", " ").title())),
            cardinality=stage.cardinality.value,
            can_add=stage.cardinality.value == "repeatable" and session.state not in {
                WorkflowState.SUCCEEDED, WorkflowState.FAILED, WorkflowState.ABORTED,
            },
            parameters=tuple(parameters),
            instances=instances,
        )

    def add_stage_instance(self, session: WorkflowSession, stage_id: str,
                           parameters: Mapping[str, Any] | None = None) -> StageInstanceProjection:
        """Create one instance through the runtime; creation invokes no action."""
        projection = self.project_stage_instances(session, stage_id)
        if not projection.can_add:
            raise WorkflowError(f"stage is not accepting instances: {stage_id}")
        expected = {item.name for item in projection.parameters}
        supplied = dict(parameters or {})
        missing = {item.name for item in projection.parameters if item.required and item.name not in supplied}
        unknown = set(supplied) - expected
        if missing:
            raise WorkflowError(f"required instance parameters are unset: {', '.join(sorted(missing))}")
        if unknown:
            raise WorkflowError(f"unknown stage instance parameters: {', '.join(sorted(unknown))}")
        for parameter in projection.parameters:
            if parameter.name in supplied:
                self._validate_instance_value(parameter.name, supplied[parameter.name], parameter.schema)
        session.add_instance(stage_id, supplied)
        return self.project_stage_instances(session, stage_id)

    @staticmethod
    def _validate_instance_value(name: str, value: Any, schema: Mapping[str, Any]) -> None:
        expected = schema.get("type")
        valid = {
            "integer": type(value) is int,
            "number": type(value) in {int, float},
            "string": isinstance(value, str),
            "boolean": type(value) is bool,
        }.get(expected, True)
        if not valid:
            raise WorkflowError(f"invalid instance parameter type: {name}")
        if "values" in schema and value not in schema["values"]:
            raise WorkflowError(f"invalid instance parameter value: {name}")
        if "minimum" in schema and value < schema["minimum"]:
            raise WorkflowError(f"instance parameter is below minimum: {name}")
        if "maximum" in schema and value > schema["maximum"]:
            raise WorkflowError(f"instance parameter is above maximum: {name}")

    def edge_observation_sink(self) -> Callable[[SinkRequest], MutationOutcome]:
        def write(request: SinkRequest) -> MutationOutcome:
            if request.sink_id != "edge.calibration_run.observation" or request.session is None:
                return MutationOutcome("rejected", "edge observation requires a session binding")
            try:
                self.client.request("calibration_run", {"action": "observation", "run_id": request.session.session_id,
                                                         "observation": dict(request.payload), "operator": self.context.operator})
            except OperatorError as error:
                return MutationOutcome("rejected", str(error))
            return MutationOutcome("accepted")
        return write

    def central_observation_sink(self) -> Callable[[SinkRequest], MutationOutcome]:
        def write(request: SinkRequest) -> MutationOutcome:
            if request.sink_id != "central.calibration_session.observation" or self.central_observation is None:
                return MutationOutcome("rejected", "central observation authority is unavailable")
            try:
                self.central_observation(request.payload)
            except Exception as error:
                return MutationOutcome("rejected", str(error))
            return MutationOutcome("accepted")
        return write

    def checkpoint_sink(self) -> Callable[[SinkRequest], MutationOutcome]:
        def write(request: SinkRequest) -> MutationOutcome:
            if request.checkpoint is None or self.checkpoint_writer is None:
                return MutationOutcome("rejected", "host checkpoint destination is unavailable")
            return self.checkpoint_writer(request, request.checkpoint)
        return write


def resolve_target(client: OperatorClient, identity: str, *, kind: TargetKind = TargetKind.PHYSICAL) -> TargetProjection:
    """Resolve a target from operator read models; never reaches the store directly."""
    if not isinstance(identity, str) or not identity:
        raise ValueError("target identity is required")
    if kind is TargetKind.SIMULATOR:
        return TargetProjection(identity, kind, {"id": identity},
                                capabilities={"pump_control": {"supported": True},
                                               "temperature_setpoint": {"supported": True, "verification": "simulated"}},
                                connection={"state": "simulated"}, telemetry={"verification": "simulated"})
    try:
        status = client.request("status")
        binding = client.request("binding")
        instrument = client.request("instrument", {"instrument_id": identity})
    except OperatorError as error:
        raise ValueError(f"target resolution failed: {error}") from error
    if not isinstance(instrument, Mapping):
        raise ValueError("operator returned an invalid target projection")
    capabilities = instrument.get("capabilities", {})
    if not isinstance(capabilities, Mapping):
        capabilities = {}
    controller = status.get("controller", {}) if isinstance(status, Mapping) else {}
    device_identity = instrument.get("device_identity")
    return TargetProjection(device_identity if isinstance(device_identity, str) and device_identity else identity, kind,
                            controller if isinstance(controller, Mapping) else {},
                            instrument=instrument, binding=binding if isinstance(binding, Mapping) else {},
                            capabilities=capabilities, connection={"state": "operator_reachable"},
                            lease={}, telemetry={"source": "operator_read_model"}, instrument_id=identity)


def _action_parts(action: ActionRef | str) -> tuple[str, str | int]:
    if isinstance(action, ActionRef):
        return action.id, action.version if action.version is not None else "1"
    if isinstance(action, str) and action:
        return action, "1"
    raise ValueError("action must be an ActionRef or non-empty string")
