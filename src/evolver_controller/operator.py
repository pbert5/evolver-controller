"""Bounded typed Unix operator protocol for the controller-owned read model."""
from __future__ import annotations

import json
import os
import socket
import socketserver
import stat
import threading
from uuid import uuid4
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping


from .doctor import doctor_report
from .hardware_ipc import PROVISIONING_IPC_TIMEOUT_SECONDS
from .store import EdgeStore

if TYPE_CHECKING:
    from .operator_identity import OperatorIdentity

DEFAULT_SOCKET = "/run/evolver-controller/operator.sock"
PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 64 * 1024
OPERATION_METADATA: dict[str, dict[str, str]] = {
    "binding": {"access": "read", "mode": "live"},
    "capabilities": {"access": "read", "mode": "live"},
    "doctor": {"access": "read", "mode": "live"},
    "instruments": {"access": "read", "mode": "live"},
    "runs": {"access": "read", "mode": "live"},
    "status": {"access": "read", "mode": "live"},
    "hardware": {"access": "mutate", "mode": "live"},
    "run": {"access": "mutate", "mode": "live"},
    "instrument": {"access": "read", "mode": "live"},
    "calibration": {"access": "read", "mode": "live"},
    "calibration_run": {"access": "mutate", "mode": "live"},
    "hardware_lease": {"access": "mutate", "mode": "live"},
    "hardware_layout": {"access": "mutate", "mode": "live"},
    "hardware_provision_identity": {"access": "mutate", "mode": "live"},
}
ALLOWED_OPERATIONS = frozenset(OPERATION_METADATA)


class OperatorError(RuntimeError):
    kind = "operator_error"

    def __init__(self, message: str, *, kind: str | None = None):
        super().__init__(message)
        if kind is not None:
            self.kind = kind


class OperatorUnavailable(OperatorError):
    kind = "unavailable"


class OperatorProtocolError(OperatorError):
    kind = "protocol_error"


def socket_path(value: str | os.PathLike[str] | None = None) -> Path:
    return Path(value or os.environ.get("EVOLVER_OPERATOR_SOCKET", DEFAULT_SOCKET))


def _encode(value: Any) -> bytes:
    return (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _readline(connection: socket.socket) -> bytes:
    data = bytearray()
    while len(data) <= MAX_MESSAGE_BYTES:
        chunk = connection.recv(min(4096, MAX_MESSAGE_BYTES + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if b"\n" in chunk:
            line, _, _ = bytes(data).partition(b"\n")
            if len(line) > MAX_MESSAGE_BYTES:
                raise OperatorProtocolError("operator request is too large", kind="request_too_large")
            return line
    if len(data) > MAX_MESSAGE_BYTES:
        raise OperatorProtocolError("operator request is too large", kind="request_too_large")
    raise OperatorProtocolError("operator request must be one newline-delimited JSON message", kind="invalid_request")


def _request_value(request: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(request, dict) or set(request) != {"operation", "params"}:
        raise OperatorProtocolError("request must contain operation and params", kind="invalid_request")
    if not isinstance(request["operation"], str) or not request["operation"]:
        raise OperatorProtocolError("operation must be a non-empty string", kind="invalid_request")
    if not isinstance(request["params"], dict):
        raise OperatorProtocolError("params must be an object", kind="invalid_request")
    operation = request["operation"]
    if operation not in ALLOWED_OPERATIONS:
        raise OperatorProtocolError(f"unsupported operator operation: {operation}", kind="unsupported_operation")
    return operation, request["params"]


def _dispatch(store: EdgeStore, operation: str, params: dict[str, Any], *,
              operator: "OperatorIdentity | None" = None, hardware_broker: Any | None = None) -> Any:
    if operation == "hardware":
        hardware_operation = params.get("operation")
        if hardware_operation not in {"discover", "protocol_test", "hardware_command", "safe_stop"}:
            raise OperatorProtocolError("unsupported hardware operation", kind="unsupported_operation")
        if operator is None:
            if hardware_operation in {"discover", "protocol_test"}:
                raise OperatorProtocolError(
                    "maintenance operation must be delegated to the hardware service",
                    kind="maintenance_delegated")
            raise OperatorProtocolError("authenticated operator attribution is required", kind="unauthorized")
        body = _hardware_request(params, operator.subject)
        if hardware_operation == "safe_stop":
            if "hardware_maintenance" not in operator.permissions:
                raise OperatorProtocolError("hardware_maintenance permission is required", kind="forbidden")
            if hardware_broker is None:
                raise OperatorProtocolError("safe-stop must be delegated to the hardware service",
                                            kind="maintenance_delegated")
            command_id = body.get("command_id") or f"safe-stop-{uuid4()}"
            authority = store.hardware_authority()
            command = {"command_id": command_id,
                       "controller_generation": authority.get("generation") if authority else None,
                       "operation": "safe_stop", "operator": operator.subject}
            try:
                return store.execute_command(
                    command,
                    lambda: hardware_broker.safe_stop(operator=operator.subject,
                                                      physical=body.get("physical", False),
                                                      command_id=command_id))
            except Exception as error:
                raise OperatorProtocolError(str(error),
                                            kind=getattr(error, "kind", "hardware_error")) from error
        if hardware_operation == "hardware_command":
            body["operation"] = params["operation_name"]
        if hardware_broker is None:
            raise OperatorProtocolError("hardware operation requires the controller broker", kind="hardware_error")
        try:
            if hardware_operation == "discover":
                return hardware_broker.discover(operator=operator.subject)
            if hardware_operation == "protocol_test":
                return hardware_broker.protocol_test(operator=operator.subject,
                                                     target_identity=body.get("target_identity"))
            return hardware_broker.command(
                body["operation_name"], operator=operator.subject,
                target_identity=body["target_identity"], parameters=body["parameters"],
                lease_token=body.get("lease_token"),
                controller_generation=body.get("controller_generation"), lease_expires_at=body.get("lease_expires_at"),
                physical=body.get("physical", False), command_id=body.get("command_id"))
        except Exception as error:
            kind = getattr(error, "kind", "HardwareError")
            if kind in {"hardware", "hardware_error"}:
                kind = "HardwareError"
            raise OperatorProtocolError(str(error), kind=kind) from error
    if operation == "capabilities":
        return {"protocol_version": PROTOCOL_VERSION, "operations": OPERATION_METADATA,
                "read_only": False, "transport": "unix"}
    if operation == "status":
        return {"controller": store.identity(), "binding": store.binding(), "runs": store.list_runs()}
    if operation == "binding":
        return store.binding()
    if operation == "runs":
        return store.list_runs()
    if operation == "instruments":
        return store.list_instruments()
    if operation == "doctor":
        return doctor_report(store)
    if operation == "instrument":
        _only(params, {"action", "instrument_id", "sensor", "channel", "target_identity", "limit"}, operation)
        action = params.get("action")
        if action in {"status", "sensor_read"}:
            if operator is None:
                raise OperatorProtocolError("authenticated operator attribution is required", kind="unauthorized")
            if "hardware_maintenance" not in operator.permissions:
                raise OperatorProtocolError("hardware_maintenance permission is required", kind="forbidden")
            if hardware_broker is None:
                raise OperatorProtocolError("instrument read must be delegated to the hardware service",
                                            kind="maintenance_delegated")
            instrument = _instrument(store, params)
            target_identity = params.get("target_identity") or instrument.get("device_identity")
            if not isinstance(target_identity, str) or not target_identity:
                raise OperatorProtocolError("instrument has no provisioned device identity", kind="not_found")
            if params.get("target_identity") is not None and params["target_identity"] != instrument.get("device_identity"):
                raise OperatorProtocolError("target_identity does not match instrument_id", kind="invalid_request")
            try:
                if action == "status":
                    return hardware_broker.status(operator=operator.subject, target_identity=target_identity)
                sensor = _required_string(params, "sensor")
                channel = params.get("channel")
                if isinstance(channel, bool) or not isinstance(channel, int):
                    raise OperatorProtocolError("channel must be an integer", kind="invalid_request")
                return hardware_broker.read_sensor(operator=operator.subject, target_identity=target_identity,
                                                  sensor=sensor, channel=channel)
            except OperatorProtocolError:
                raise
            except Exception as error:
                raise OperatorProtocolError(str(error), kind=getattr(error, "kind", "hardware_error")) from error
        if action in {"telemetry_latest", "telemetry_list"}:
            instrument = _instrument(store, params)
            records = _cached_telemetry(store, instrument["id"])
            if action == "telemetry_latest":
                return records[-1] if records else None
            limit = params.get("limit", 100)
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
                raise OperatorProtocolError("limit must be an integer between 1 and 1000", kind="invalid_request")
            return records[-limit:]
        if action is not None:
            raise OperatorProtocolError("instrument action is unsupported", kind="unsupported_operation")
        try:
            return store.instrument(_required_string(params, "instrument_id"))
        except KeyError as error:
            raise OperatorProtocolError("instrument not found", kind="not_found") from error
    if operation == "calibration":
        _only(params, {"action", "instrument_id", "references", "requirements"}, operation)
        action = params.get("action")
        if action == "artifacts":
            instrument_id = params.get("instrument_id")
            if instrument_id is not None and (not isinstance(instrument_id, str) or not instrument_id):
                raise OperatorProtocolError("instrument_id must be a non-empty string", kind="invalid_request")
            return store.calibration_artifacts(instrument_id=instrument_id)
        if action == "preflight" and isinstance(params.get("references"), list) and isinstance(params.get("requirements", []), list):
            return store.calibration_preflight(params["references"], requirements=params.get("requirements", []))
        raise OperatorProtocolError("calibration action must be artifacts or preflight", kind="invalid_request")
    if operation == "calibration_run":
        if operator is None:
            raise OperatorProtocolError("authenticated operator attribution is required", kind="unauthorized")
        if "manage_calibration" not in operator.permissions:
            raise OperatorProtocolError("manage_calibration permission is required", kind="forbidden")
        subject = _operator_subject(operator)
        return _calibration_run(store, params, subject)
    if operation == "run":
        _only(params, {"action", "run_id", "based_on_revision"}, operation)
        action = params.get("action")
        run_id = _required_string(params, "run_id")
        if action == "show":
            try:
                return store.run(run_id)
            except KeyError as error:
                raise OperatorProtocolError("run not found", kind="not_found") from error
        if action == "events":
            return store.events_after(run_id)
        if action == "telemetry":
            return [item for stream in store.telemetry_streams() if run_id in stream for item in store.telemetry_after(stream)]
        if action in {"pause", "resume", "stop"}:
            revision = params.get("based_on_revision")
            if isinstance(revision, bool) or not isinstance(revision, int):
                raise OperatorProtocolError("based_on_revision must be an integer", kind="invalid_request")
            try:
                return store.transition_run(run_id=run_id, state={"pause": "paused", "resume": "running", "stop": "stopped"}[action], based_on_revision=revision)
            except KeyError as error:
                raise OperatorProtocolError("run not found", kind="not_found") from error
        raise OperatorProtocolError("run action is unsupported", kind="unsupported_operation")
    if operation == "hardware_lease":
        _only(params, {"action", "operator", "ttl_seconds"}, operation)
        action = params.get("action")
        if action == "status":
            if hardware_broker is None:
                raise OperatorProtocolError("physical lease requires the hardware service", kind="lease_error")
            return hardware_broker.lease_status()
        subject = _operator_subject(operator)
        if params.get("operator") not in {None, subject}:
            raise OperatorProtocolError("operator does not match authenticated operator", kind="unauthorized")
        try:
            if action == "acquire":
                if hardware_broker is None:
                    raise OperatorProtocolError("physical lease requires the hardware service", kind="lease_error")
                generation = store.allocate_local_commissioning_generation()
                return hardware_broker.lease_acquire(operator=subject, ttl_seconds=params.get("ttl_seconds", 900),
                                                     controller_generation=generation)
            if action == "release":
                if hardware_broker is None:
                    raise OperatorProtocolError("physical lease requires the hardware service", kind="lease_error")
                return hardware_broker.lease_release(operator=subject)
        except Exception as error:
            raise OperatorProtocolError(str(error), kind="lease_error") from error
        raise OperatorProtocolError("lease action is unsupported", kind="unsupported_operation")
    if operation == "hardware_layout":
        _only(params, {"instrument_id", "target_identity", "operator", "positions"}, operation)
        subject = _operator_subject(operator)
        if params.get("operator") not in {None, subject}:
            raise OperatorProtocolError("operator does not match authenticated operator", kind="unauthorized")
        target = _required_string(params, "target_identity")
        instrument_id = params.get("instrument_id")
        if instrument_id is None:
            instrument = next((item for item in store.list_instruments()
                               if item.get("device_identity") == target), None)
            if not isinstance(instrument, dict):
                raise OperatorProtocolError("layout target identity is not registered", kind="not_found")
            instrument_id = instrument["id"]
        instrument_id = _required_string({"instrument_id": instrument_id}, "instrument_id")
        positions = params.get("positions")
        if not isinstance(positions, dict):
            raise OperatorProtocolError("positions must be an object", kind="invalid_request")
        try:
            return store.record_physical_layout(instrument_id=instrument_id, positions={int(key): value for key, value in positions.items()}, operator=subject, device_identity=target)
        except (ValueError, KeyError) as error:
            raise OperatorProtocolError(str(error), kind="layout_error") from error
    if operation == "hardware_provision_identity":
        _only(params, {"device_id", "owner_id", "operator", "physical"}, operation)
        subject = _operator_subject(operator)
        if params.get("operator") not in {None, subject}:
            raise OperatorProtocolError("operator does not match authenticated operator", kind="unauthorized")
        if params.get("physical") is not True:
            raise OperatorProtocolError("identity provisioning requires physical opt-in", kind="unsafe")
        if hardware_broker is None:
            raise OperatorProtocolError("identity provisioning must be delegated to the hardware service", kind="maintenance_delegated")
        device_id = _required_string(params, "device_id")
        owner_id = _required_string(params, "owner_id")
        try:
            return hardware_broker.request(hardware_broker.socket_path, {
                "operation": "provision_identity", "device_id": device_id,
                "owner_id": owner_id, "operator": subject, "physical": True,
            }, PROVISIONING_IPC_TIMEOUT_SECONDS)
        except Exception as error:
            raise OperatorProtocolError(str(error), kind="hardware_error") from error
    if operation not in {"status", "binding", "runs", "instruments", "doctor", "capabilities"}:
        raise OperatorProtocolError(f"unsupported operator operation: {operation}", kind="unsupported_operation")
    if params:
        raise OperatorProtocolError("params must be empty for this operation", kind="invalid_request")
    raise OperatorProtocolError(f"unsupported operator operation: {operation}", kind="unsupported_operation")


def _only(params: dict[str, Any], allowed: set[str], operation: str) -> None:
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise OperatorProtocolError(f"unknown {operation} request fields: {', '.join(unknown)}", kind="invalid_request")


def _required_string(params: dict[str, Any], name: str) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value:
        raise OperatorProtocolError(f"{name} must be a non-empty string", kind="invalid_request")
    return value


def _instrument(store: EdgeStore, params: dict[str, Any]) -> dict[str, Any]:
    instrument_id = params.get("instrument_id")
    if instrument_id is not None and (not isinstance(instrument_id, str) or not instrument_id):
        raise OperatorProtocolError("instrument_id must be a non-empty string", kind="invalid_request")
    try:
        if instrument_id is not None:
            return store.instrument(instrument_id)
        target = params.get("target_identity")
        if isinstance(target, str) and target:
            return next(item for item in store.list_instruments() if item.get("device_identity") == target)
    except (KeyError, StopIteration) as error:
        raise OperatorProtocolError("instrument not found", kind="not_found") from error
    raise OperatorProtocolError("instrument_id or target_identity is required", kind="invalid_request")


def _cached_telemetry(store: EdgeStore, instrument_id: str) -> list[dict[str, Any]]:
    prefix = f"instrument:{instrument_id}:"
    records = []
    for stream in store.telemetry_streams():
        for record in store.telemetry_after(stream):
            payload = record.get("payload") if isinstance(record.get("payload"), Mapping) else {}
            if stream.startswith(prefix) or payload.get("instrument_id") == instrument_id:
                observations = []
                vial_ids = payload.get("vial_position_ids") if isinstance(payload.get("vial_position_ids"), list) else []
                for channel in range(len(vial_ids) or 1):
                    vial_id = vial_ids[channel] if channel < len(vial_ids) and isinstance(vial_ids[channel], str) else None
                    for key, metric in ((f"photodiode_adc_{channel}", "photodiode_raw"),
                                        (f"thermistor_adc_{channel}", "thermistor_raw")):
                        if isinstance(payload.get(key), (int, float)) and not isinstance(payload.get(key), bool):
                            observations.append({"instrument_id": instrument_id,
                                                  "controller_id": store.identity()["id"],
                                                  "vial_position_id": vial_id, "channel": channel,
                                                  "raw_metric": metric, "raw_value": payload[key],
                                                  "derived_value": None, "unit": "ADC",
                                                  "captured_at": record.get("captured_at"),
                                                  "freshness": "cached", "source": "telemetry_store",
                                                  "calibration": {"state": "not_calibrated",
                                                                  "artifact_id": None, "artifact_digest": None},
                                                  "evidence_level": "recorded"})
                calibration_details = payload.get("calibration") if isinstance(payload.get("calibration"), Mapping) else {}
                records.append({**record, "instrument_id": instrument_id,
                                "controller_id": store.identity()["id"], "freshness": "cached",
                                "source": "telemetry_store", "evidence_level": "recorded",
                                "calibration": {"state": payload.get("calibration_state", "not_calibrated"),
                                                "artifact_id": payload.get("calibration_artifact_id"),
                                                "artifact_digest": payload.get("calibration_artifact_digest"),
                                                "details": dict(calibration_details)},
                                "observations": observations})
    return sorted(records, key=lambda item: (item.get("captured_at") or "", item.get("sequence", 0)))


def _operator_subject(operator: "OperatorIdentity | None") -> str:
    if operator is None:
        raise OperatorProtocolError("authenticated operator attribution is required", kind="unauthorized")
    return operator.subject


def _calibration_run(store: EdgeStore, params: dict[str, Any], subject: str) -> Any:
    """Apply one authenticated, local calibration-run mutation.

    This is deliberately an edge operation: it records a durable run fact and
    never reaches the hardware service.  ``action`` and the request envelope
    are transport decoration, not scientific observation fields.
    """
    action = params.get("action")
    if not isinstance(action, str) or action not in {"create", "observation", "activate_artifact"}:
        raise OperatorProtocolError(
            "calibration_run action must be create, observation, or activate_artifact",
            kind="invalid_request")
    supplied_operator = params.get("operator")
    if supplied_operator is not None and supplied_operator != subject:
        raise OperatorProtocolError("operator does not match authenticated operator", kind="unauthorized")
    run_id = _required_string(params, "run_id")

    if action == "create":
        _only(params, {"action", "run_id", "calibration_type", "instrument_id",
                       "component_id", "vial_position_id", "operator"}, "calibration_run")
        calibration_type = _required_string(params, "calibration_type")
        instrument_id = _required_string(params, "instrument_id")
        component_id = params.get("component_id")
        vial_position_id = params.get("vial_position_id")
        for name, value in (("component_id", component_id), ("vial_position_id", vial_position_id)):
            if value is not None and (not isinstance(value, str) or not value):
                raise OperatorProtocolError(f"{name} must be a non-empty string", kind="invalid_request")
        try:
            return store.create_calibration_run(run_id=run_id, calibration_type=calibration_type,
                                               instrument_id=instrument_id, component_id=component_id,
                                               vial_position_id=vial_position_id)
        except (KeyError, ValueError, TypeError, RuntimeError) as error:
            raise OperatorProtocolError(str(error), kind="calibration_run_error") from error

    if action == "observation":
        allowed = {"action", "run_id", "observation", "operator"}
        observation = params.get("observation")
        if observation is None:
            # Accept the typed evidence fields directly in the operator
            # envelope for parity with the central observation endpoint.
            observation = {key: value for key, value in params.items()
                           if key not in {"action", "run_id", "operator"}}
            allowed.update(observation)
        _only(params, allowed, "calibration_run")
        if not isinstance(observation, dict):
            raise OperatorProtocolError("observation must be an object", kind="invalid_request")
        # Do not persist transport fields even if a caller puts them in the
        # nested observation; the scientific validator receives only evidence.
        clean_observation = {key: value for key, value in observation.items()
                             if key not in {"action", "run_id", "operator"}}
        try:
            return store.record_calibration_observation(run_id=run_id, observation=clean_observation)
        except (KeyError, ValueError, TypeError, RuntimeError) as error:
            raise OperatorProtocolError(str(error), kind="calibration_run_error") from error

    _only(params, {"action", "run_id", "artifact", "operator", "based_on_revision"}, "calibration_run")
    artifact = params.get("artifact")
    if not isinstance(artifact, dict):
        raise OperatorProtocolError("artifact must be an object", kind="invalid_request")
    based_on_revision = params.get("based_on_revision")
    if isinstance(based_on_revision, bool) or not isinstance(based_on_revision, int):
        raise OperatorProtocolError("based_on_revision must be an integer", kind="invalid_request")
    try:
        return store.activate_calibration_artifact(artifact=artifact, run_id=run_id,
                                                   activated_by=subject,
                                                   based_on_revision=based_on_revision)
    except (KeyError, ValueError, TypeError, RuntimeError) as error:
        raise OperatorProtocolError(str(error), kind="calibration_run_error") from error


def _hardware_request(params: dict[str, Any], subject: str) -> dict[str, Any]:
    """Validate and normalize the typed hardware envelope before brokerage."""
    operation = params.get("operation")
    if operation == "discover":
        allowed = {"operation"}
    elif operation == "protocol_test":
        allowed = {"operation", "target_identity"}
        target = params.get("target_identity")
        if target is not None and (not isinstance(target, str) or not target):
            raise OperatorProtocolError("target_identity must be a non-empty string", kind="invalid_request")
    elif operation == "safe_stop":
        allowed = {"operation", "physical", "command_id", "operator"}
        if params.get("physical") is not True:
            raise OperatorProtocolError("physical opt-in is required", kind="unsafe")
        if "operator" in params and params["operator"] != subject:
            raise OperatorProtocolError("operator does not match authenticated operator", kind="unauthorized")
    elif operation == "hardware_command":
        allowed = {"operation", "operation_name", "target_identity", "parameters",
                   "controller_generation", "lease_token", "lease_owner", "lease_expires_at", "physical", "command_id", "operator"}
        required = {"operation_name", "target_identity", "parameters", "controller_generation", "lease_token", "physical"}
        missing = sorted(required - params.keys())
        if missing:
            raise OperatorProtocolError(f"missing hardware command fields: {', '.join(missing)}", kind="invalid_request")
        if not isinstance(params["operation_name"], str) or not params["operation_name"]:
            raise OperatorProtocolError("operation_name must be a non-empty string", kind="invalid_request")
        if not isinstance(params["target_identity"], str) or not params["target_identity"]:
            raise OperatorProtocolError("target_identity must be a non-empty string", kind="invalid_request")
        if not isinstance(params["parameters"], dict):
            raise OperatorProtocolError("parameters must be an object", kind="invalid_request")
        generation = params["controller_generation"]
        if isinstance(generation, bool) or not isinstance(generation, int):
            raise OperatorProtocolError("controller_generation must be an integer", kind="invalid_request")
        if not isinstance(params["lease_token"], str) or not params["lease_token"]:
            raise OperatorProtocolError("lease_token must be a non-empty string", kind="invalid_request")
        if not isinstance(params["physical"], bool):
            raise OperatorProtocolError("physical must be a boolean", kind="invalid_request")
        for field in ("operator", "lease_owner"):
            if field in params and params[field] != subject:
                raise OperatorProtocolError(f"{field} does not match authenticated operator", kind="unauthorized")
    else:
        raise OperatorProtocolError("unsupported hardware operation", kind="unsupported_operation")
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise OperatorProtocolError(f"unknown hardware request fields: {', '.join(unknown)}", kind="invalid_request")
    if operation == "hardware_command":
        result = {key: params[key] for key in allowed if key in params and key not in {"operator"}}
        result["lease_owner"] = subject
        return result
    if operation == "safe_stop":
        return {key: params[key] for key in allowed if key in params and key != "operator"}
    return dict(params)


def _error(error: OperatorError) -> dict[str, Any]:
    return {"ok": False, "error": {"kind": error.kind, "message": str(error)}}


class _OperatorServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: str, store: EdgeStore, *,
                 operator: OperatorIdentity | None, hardware_broker: Any | None):
        self.store = store
        self.operator = operator
        self.hardware_broker = hardware_broker
        super().__init__(address, _OperatorHandler)


class _OperatorHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            try:
                payload = json.loads(_readline(self.connection).decode("utf-8"))
            except json.JSONDecodeError as error:
                raise OperatorProtocolError("operator request is malformed JSON", kind="malformed_json") from error
            operation, params = _request_value(payload)
            result = _dispatch(self.server.store, operation, params,  # type: ignore[attr-defined]
                               operator=self.server.operator, hardware_broker=self.server.hardware_broker)
            self.wfile.write(_encode({"ok": True, "result": result}))
        except OperatorError as error:
            self.wfile.write(_encode(_error(error)))
        except (UnicodeDecodeError, OSError, KeyError, ValueError):
            self.wfile.write(_encode(_error(OperatorError("operator request failed", kind="internal_error"))))


class OperatorServer:
    def __init__(self, store: EdgeStore, path: str | os.PathLike[str] = DEFAULT_SOCKET, *,
                 operator: OperatorIdentity | None = None, hardware_broker: Any | None = None):
        self.store = store
        self.operator = operator
        self.hardware_broker = hardware_broker
        self.path = socket_path(path)
        self._server: _OperatorServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> "OperatorServer":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            if not stat.S_ISSOCK(self.path.stat().st_mode):
                raise OperatorError(f"operator socket path is not a socket: {self.path}")
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.settimeout(0.2); probe.connect(str(self.path))
                raise OperatorError(f"operator socket is already in use: {self.path}")
            except (ConnectionRefusedError, FileNotFoundError, socket.timeout):
                self.path.unlink()
        self._server = _OperatorServer(str(self.path), self.store,
                                       operator=self.operator, hardware_broker=self.hardware_broker)
        os.chmod(self.path, 0o660)
        self._thread = threading.Thread(target=self._server.serve_forever, name="evolver-operator", daemon=True)
        self._thread.start()
        return self

    def shutdown(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.shutdown(); server.server_close()
        if self.path.exists() and stat.S_ISSOCK(self.path.stat().st_mode):
            self.path.unlink()

    close = shutdown

    def __enter__(self) -> "OperatorServer":
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.shutdown()


class OperatorClient:
    def __init__(self, path: str | os.PathLike[str] = DEFAULT_SOCKET, *, timeout: float = 3.0):
        self.path, self.timeout = socket_path(path), timeout

    def request(self, operation: str, params: dict[str, Any] | None = None) -> Any:
        return request(operation, self.path, self.timeout, params=params)


def request(operation: str, path: str | os.PathLike[str] = DEFAULT_SOCKET, timeout: float = 3.0,
            *, params: dict[str, Any] | None = None) -> Any:
    envelope = {"operation": operation, "params": {} if params is None else params}
    _request_value(envelope)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(str(socket_path(path)))
            connection.sendall(_encode(envelope))
            response = json.loads(_readline(connection).decode("utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise OperatorUnavailable(f"operator service unavailable: {error}", kind="unavailable") from error
    if isinstance(response, dict) and response.get("ok") is True and "result" in response \
            and set(response) == {"ok", "result"}:
        return response["result"]
    error = response.get("error") if isinstance(response, dict) else None
    if isinstance(response, dict) and response.get("ok") is False and isinstance(error, dict) \
            and set(error) == {"kind", "message"} and all(isinstance(error[key], str) for key in error):
        raise OperatorProtocolError(error["message"], kind=error["kind"])
    raise OperatorProtocolError("invalid operator response", kind="invalid_response")
