"""The controller-owned bridge between workflow runtime and operator authority.

This module is intentionally transport boring: it never opens a device, reads
the edge store, or turns a trusted action name into a second hardware API.
Physical work is sent through ``OperatorClient`` and all other authorities are
injected by the host application.
"""
from __future__ import annotations

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
        cli = f"evoctl workflow action {action_id} --target {self.target.identity}" if availability.route else None
        return ActionProjection(dict(step), {"id": action_id, "version": version}, api, cli, raw, availability)

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
