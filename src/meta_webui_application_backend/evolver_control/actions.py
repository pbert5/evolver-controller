"""Central eVOLVER action adapter.

This is the application boundary for named central actions.  It deliberately
contains no state or policy of its own: action handlers call the existing
``evolver_controller`` routes/functions, which remain authoritative for
authorization, fencing, idempotency, audit facts, and queued-vs-applied
semantics.
"""
from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from typing import Any, Mapping

from .. import evolver_controller
from ..evolver_edge.hardware_broker import HardwareBroker as FencedHardwareBroker


class UnknownAction(ValueError):
    """Raised when a caller supplies an action outside this adapter contract."""


# These IDs are part of the frozen central action catalog.  Keep the compact
# names below as the implementation vocabulary so older callers retain their
# behavior while catalog clients get exact, stable dispatch matches.
_CALIBRATION_ACTION_ALIASES = {
    "evolver.calibrations.list": "calibrations",
    "evolver.calibrations.sessions.create": "calibration_create",
    "evolver.calibrations.sessions.observation": "calibration_observation",
    "evolver.calibrations.sessions.fit": "calibration_fit",
    "evolver.calibrations.sessions.accept": "calibration_accept",
    "evolver.calibrations.sessions.cancel": "calibration_cancel",
    "evolver.calibrations.sessions.capture": "calibration_capture_observation",
    "evolver.calibrations.artifacts.deliver": "calibration_deliver",
    "evolver.calibrations.artifacts.supersede": "calibration_supersede",
    "evolver.calibrations.artifacts.invalidate": "calibration_invalidate",
}

def _body(parameters: Mapping[str, Any]) -> dict[str, Any]:
    return dict(parameters)


def _operator_required(operator: evolver_controller.OperatorIdentity | None,
                       permission: str) -> tuple[HTTPStatus, dict[str, Any]] | None:
    # A small explicit check is needed only for controller functions whose
    # public route adds the authorization gate before calling the function.
    return evolver_controller._require_operator(operator, permission)


def dispatch(action: str, parameters: Mapping[str, Any] | None = None, *,
             operator: evolver_controller.OperatorIdentity | None = None,
             state_root: Path | None = None, hardware_broker: Any | None = None) -> tuple[HTTPStatus, dict[str, Any]]:
    """Dispatch one named central action to the existing controller seam.

    ``parameters`` is request data, not executable code.  Responses preserve
    the controller's status and payload so callers can distinguish accepted
    (queued intent) from completed/applied evidence.
    """
    if not isinstance(action, str) or not action:
        raise UnknownAction("action must be a non-empty string")
    action = _CALIBRATION_ACTION_ALIASES.get(action, action)
    params = parameters if isinstance(parameters, Mapping) else {}
    body = _body(params)

    if action in {"hardware_discover", "hardware_protocol_test", "hardware_command"}:
        denied = _operator_required(operator, "hardware_maintenance")
        if denied:
            return denied
        if hardware_broker is None:
            from .hardware import HardwareBroker
            hardware_broker = HardwareBroker()
        try:
            if isinstance(hardware_broker, FencedHardwareBroker):
                if action == "hardware_discover":
                    return HTTPStatus.OK, hardware_broker.discover(operator=operator.subject)
                if action == "hardware_protocol_test":
                    return HTTPStatus.OK, hardware_broker.protocol_test(
                        operator=operator.subject, target_identity=body.get("target_identity"))
                return HTTPStatus.OK, hardware_broker.command(
                    str(body.get("operation")), operator=operator.subject,
                    target_identity=body.get("target_identity"), parameters=body.get("parameters"),
                    lease_token=body.get("lease_token"), controller_generation=body.get("controller_generation"),
                    physical=body.get("physical", False), command_id=body.get("command_id"))
            if action == "hardware_discover":
                return HTTPStatus.OK, hardware_broker.discover(operator=operator.subject)
            if action == "hardware_protocol_test":
                return HTTPStatus.OK, hardware_broker.protocol_test(operator=operator.subject)
            return HTTPStatus.OK, hardware_broker.command(body, operator=operator.subject)
        except Exception as error:
            kind = getattr(error, "kind", "HardwareError")
            status = (HTTPStatus.SERVICE_UNAVAILABLE if kind == "HardwareUnavailable"
                      else HTTPStatus.BAD_GATEWAY if kind == "HardwareProtocolError"
                      else HTTPStatus.BAD_REQUEST)
            return status, {"error": str(error), "kind": kind}

    # Read projections and durable command facts.
    if action in {"controllers", "evolver.controllers"}:
        return evolver_controller.controllers(controller_id=params.get("controller_id"), state_root=state_root)
    if action in {"instruments", "evolver.instruments"}:
        return evolver_controller.instruments(instrument_id=params.get("instrument_id"), state_root=state_root)
    if action in {"runs", "evolver.runs"}:
        return evolver_controller.runs(run_id=params.get("run_id"), state_root=state_root)
    if action in {"commands", "command", "evolver.commands"}:
        return evolver_controller.command_projection(str(params.get("controller_id", "")), params.get("command_id"), state_root=state_root)
    if action in {"controller_freshness", "evolver.controller_freshness"}:
        return evolver_controller.controller_freshness(controller_id=params.get("controller_id"), state_root=state_root)
    if action in {"recovery", "recovery_manifest", "evolver.recovery"}:
        controller_id = str(params.get("controller_id", ""))
        if params.get("request") is True:
            denied = _operator_required(operator, "recover_controller")
            if denied:
                return denied
            return evolver_controller.request_recovery_manifest(
                controller_id, requested_by=operator.subject, auth_source=operator.source, state_root=state_root)
        status, projection = evolver_controller.controllers(controller_id=controller_id, state_root=state_root)
        if status is not HTTPStatus.OK:
            return status, projection
        manifest = projection["controller"].get("recovery_manifest")
        return HTTPStatus.OK, {"controller_id": controller_id, "recovery_manifest": manifest,
                               "webui_controller": projection["webui_controller"]}

    # Enrollment is split between operator-issued tokens and machine enrollment.
    if action in {"enrollment_token", "create_enrollment_token", "evolver.enrollment_token"}:
        denied = _operator_required(operator, "manage_controller")
        if denied:
            return denied
        return evolver_controller.create_enrollment_token(
            server_url=body.get("server_url", ""),
            ttl_seconds=body.get("ttl_seconds", evolver_controller.DEFAULT_TOKEN_TTL_SECONDS),
            purpose=body.get("purpose", "enrollment"), release_binding=body.get("release_binding"),
            state_root=state_root)
    if action in {"enroll", "evolver.enroll"}:
        return evolver_controller.enroll(body, state_root=state_root)

    controller_id = params.get("controller_id")
    if action in {"refresh", "controller_refresh", "evolver.controller_refresh"}:
        return evolver_controller.request_controller_refresh(str(controller_id), body, operator=operator, state_root=state_root)
    if action in {"hardware_rescan", "controller_hardware_rescan", "evolver.controller_hardware_rescan"}:
        return evolver_controller.request_controller_refresh(str(controller_id), body, operator=operator, hardware=True, state_root=state_root)
    if action in {"assign_endpoint", "assign_controller_endpoint", "evolver.assign_controller_endpoint"}:
        return evolver_controller.assign_controller_endpoint(str(controller_id), body, operator=operator, state_root=state_root)
    if action in {"desired_release", "controller_set_desired_release", "evolver.controller_set_desired_release"}:
        return evolver_controller.set_desired_release(str(controller_id), body, operator=operator, state_root=state_root)
    if action in {"archive_controller", "evolver.archive_controller"}:
        return evolver_controller.archive_controller(str(controller_id), operator=operator, state_root=state_root)
    if action in {"restore_controller", "evolver.restore_controller"}:
        return evolver_controller.archive_controller(str(controller_id), operator=operator, state_root=state_root, restore=True)
    if action in {"rollback", "controller_rollback", "evolver.controller_rollback"}:
        return evolver_controller.request_rollback(str(controller_id), body, operator=operator, state_root=state_root)

    if action in {"lease", "manual_control_lease", "evolver.manual_control_lease"}:
        return evolver_controller.manual_control_lease(str(controller_id), body, operator=operator,
                                                       action=str(params.get("lease_action", "acquire")), state_root=state_root)
    if action in {"manual_command", "instrument_manual_command", "evolver.instrument_manual_command"}:
        return evolver_controller.manual_control_command(str(controller_id), body, operator=operator, state_root=state_root)

    if action in {"run_command", "evolver.run_command", "pause_run", "resume_run", "stop_run"}:
        run_id = str(params.get("run_id", ""))
        command_body = dict(body)
        if action in {"pause_run", "resume_run", "stop_run"}:
            command_body.setdefault("action", action.removesuffix("_run"))
        denied = _operator_required(operator, "operate_run")
        if denied:
            return denied
        return evolver_controller.mutate_run(run_id, command_body, requested_by=operator.subject,
                                             auth_source=operator.source, state_root=state_root)
    if action in {"run_resources", "evolver.run_resources"}:
        return evolver_controller.run_resources(str(params.get("run_id", "")), state_root=state_root)
    if action in {"add_run_resource", "release_run_resource", "replace_run_resource", "confirm_run_move"}:
        operation = {"add_run_resource": "add", "release_run_resource": "release",
                     "replace_run_resource": "replace", "confirm_run_move": "confirm_move"}[action]
        return evolver_controller.mutate_run_resource(
            str(params.get("run_id", "")), body, operator=operator,
            assignment_id=params.get("assignment_id"), action=operation, state_root=state_root)
    if action in {"recovery_diff", "evolver.recovery_diff"}:
        return evolver_controller.recovery_diff(str(controller_id), state_root=state_root)
    if action in {"recovery_import", "evolver.recovery_import"}:
        denied = _operator_required(operator, "recover_controller")
        if denied:
            return denied
        return evolver_controller.import_recovery_snapshot(str(controller_id), body, state_root=state_root)

    # Calibration state is central-owned.  Keep these mutations as a thin
    # action adapter over the controller functions so permission checks,
    # durable facts, and queued distribution semantics remain centralized.
    if action in {"calibrations", "evolver.calibrations"}:
        return evolver_controller.calibrations(calibration_id=params.get("calibration_id"), state_root=state_root)
    if action in {"calibration_workspace", "evolver.calibration_workspace"}:
        return evolver_controller.calibration_workspace(state_root=state_root)
    if action in {"calibration_create", "create_calibration_session", "evolver.calibration_create"}:
        return evolver_controller.create_calibration_session(body, operator=operator, state_root=state_root)
    if action in {"calibration_observation", "evolver.calibration_observation"}:
        observation = {key: value for key, value in body.items()
                       if key not in {"action", "session_id"}}
        return evolver_controller.calibration_session_mutation(
            str(params.get("session_id", "")), "observation", observation,
            operator=operator, state_root=state_root)
    if action in {"calibration_fit", "evolver.calibration_fit",
                  "calibration_cancel", "evolver.calibration_cancel",
                  "calibration_accept", "evolver.calibration_accept"}:
        mutation = action.removeprefix("evolver.").removeprefix("calibration_")
        return evolver_controller.calibration_session_mutation(
            str(params.get("session_id", "")), mutation, body,
            operator=operator, state_root=state_root)
    if action in {"calibration_capture_observation", "evolver.calibration_capture_observation"}:
        return evolver_controller.capture_latest_observation(
            str(params.get("session_id", "")), body,
            operator=operator, state_root=state_root)
    if action in {"calibration_fixture", "evolver.calibration_fixture"}:
        return evolver_controller.create_pump_fixture_artifacts(
            str(params.get("instrument_id", "")), body.get("records"),
            operator=operator, state_root=state_root)
    if action in {"calibration_deliver", "calibration_activate_artifact",
                  "evolver.calibration_deliver", "evolver.calibration_activate_artifact"}:
        artifact_id = str(params.get("artifact_id", ""))
        if action.endswith("activate_artifact"):
            # The central operation is distribution; activation is recorded
            # by the edge after it receives the immutable artifact.
            action = "calibration_deliver"
        return evolver_controller.deliver_calibration_artifact(
            artifact_id, operator=operator, request_id=body.get("request_id"),
            state_root=state_root)
    if action in {"calibration_supersede", "evolver.calibration_supersede"}:
        return evolver_controller.supersede_calibration_artifact(
            str(params.get("artifact_id", "")),
            superseding_artifact_id=str(body.get("superseding_artifact_id", "")),
            operator=operator, state_root=state_root)
    if action in {"calibration_invalidate", "evolver.calibration_invalidate"}:
        return evolver_controller.invalidate_calibration_artifact(
            str(params.get("artifact_id", "")), reason=str(body.get("reason", "")),
            operator=operator, state_root=state_root)

    raise UnknownAction(f"unknown central eVOLVER action: {action}")


class CentralEvolverActionAdapter:
    """Injectable adapter for application callers and focused contract tests."""

    def __init__(self, *, state_root: Path | None = None) -> None:
        self.state_root = state_root

    def dispatch(self, action: str, parameters: Mapping[str, Any] | None = None, *,
                 operator: evolver_controller.OperatorIdentity | None = None,
                 hardware_broker: Any | None = None) -> tuple[HTTPStatus, dict[str, Any]]:
        return dispatch(action, parameters, operator=operator, state_root=self.state_root,
                        hardware_broker=hardware_broker)
