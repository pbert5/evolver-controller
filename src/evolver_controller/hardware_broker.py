"""Controller-owned brokerage boundary for the private hardware socket."""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Callable, Mapping
from uuid import uuid4

from .hardware_protocol import ACTUATOR_BOUNDS, validate_device_operation
from .hardware_ipc import DEFAULT_IPC_TIMEOUT_SECONDS, request as ipc_request
from .store import EdgeStore, EdgeStoreError


class HardwareBrokerError(EdgeStoreError):
    kind = "hardware"


class HardwareBrokerUnavailable(HardwareBrokerError):
    kind = "unavailable"


class HardwareBrokerProtocolError(HardwareBrokerError):
    kind = "protocol"


_ACTUATORS = frozenset({"safe_stop", "set_output", "pulse_pump", "set_stir", "pulse_heater"})
# Controller-side default for the isolated hardware-service boundary.
DEFAULT_HARDWARE_SOCKET = "/run/evolver-hardware/hardware.sock"


def resolve_hardware_socket(socket_path: str | None = None) -> str:
    """Resolve the controller-to-hardware IPC socket by explicit precedence."""
    return socket_path if socket_path is not None else os.environ.get("EVOLVER_HARDWARE_SOCKET", DEFAULT_HARDWARE_SOCKET)


def _map_ipc_error(error: BaseException) -> HardwareBrokerError:
    message = str(error)[:256]
    if isinstance(error, (TimeoutError, OSError)) or any(marker in message.lower() for marker in ("unavailable", "timed out", "timeout", "refused")):
        return HardwareBrokerUnavailable(message)
    return HardwareBrokerProtocolError(message)


class HardwareBroker:
    def __init__(self, store: EdgeStore, socket_path: str | None = None, *,
                 request: Callable[[str, dict[str, Any], float | None], dict[str, Any]] = ipc_request,
                 timeout: float = DEFAULT_IPC_TIMEOUT_SECONDS) -> None:
        self.store, self.socket_path, self.request, self.timeout = store, resolve_hardware_socket(socket_path), request, timeout

    def _call(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self.request(self.socket_path, payload, self.timeout)
        except Exception as error:
            raise _map_ipc_error(error) from error
        if not isinstance(result, dict):
            raise HardwareBrokerProtocolError("hardware response must be an object")
        return result

    def discover(self, *, operator: str) -> dict[str, Any]:
        self._require_operator(operator)
        result = self._call({"operation": "discover", "operator": operator})
        if result.get("identity_state") == "provisioned" and result.get("id"):
            registered = dict(result)
            registered["controller_id"] = self.store.identity()["id"]
            self.store.register_instruments([registered])
        return result

    def protocol_test(self, *, operator: str, target_identity: str | None = None) -> dict[str, Any]:
        self._require_operator(operator)
        payload = {"operation": "protocol_test", "operator": operator}
        if target_identity is not None:
            self._require_target(target_identity)
            payload["target_identity"] = target_identity
        result = self._call(payload)
        if target_identity is not None and result.get("device_identity") not in {None, target_identity}:
            raise HardwareBrokerProtocolError("protocol test target identity mismatch")
        return result

    def _instrument_for_target(self, target_identity: str) -> dict[str, Any]:
        if self.store is None:
            raise ValueError("controller inventory is required for instrument reads")
        self._require_target(target_identity)
        instrument = next(item for item in self.store.list_instruments()
                          if item.get("device_identity") == target_identity)
        return instrument

    @staticmethod
    def _calibration(response: Mapping[str, Any]) -> dict[str, Any]:
        calibration = response.get("calibration")
        if isinstance(calibration, Mapping):
            result = dict(calibration)
        else:
            result = {}
        state = result.get("state") or response.get("calibration_state") or "not_calibrated"
        result["state"] = state
        result.setdefault("artifact_id", response.get("calibration_artifact_id"))
        result.setdefault("artifact_digest", response.get("calibration_artifact_digest"))
        return result

    @staticmethod
    def _numeric(value: Any) -> Any:
        if isinstance(value, str):
            try:
                return float(value) if "." in value else int(value)
            except ValueError:
                return value
        return value

    def status(self, *, operator: str, target_identity: str) -> dict[str, Any]:
        """Read current device status through the private hardware IPC."""
        self._require_operator(operator)
        instrument = self._instrument_for_target(target_identity)
        response = self._call({"operation": "get_status", "target_identity": target_identity,
                               "operator": operator})
        reported_identity = response.get("device_identity")
        if reported_identity is not None and reported_identity != target_identity:
            raise HardwareBrokerProtocolError("hardware status identity does not match target identity")
        observed_at = response.get("observed_at") or datetime.now(UTC).isoformat()
        return {"instrument_id": instrument.get("id"), "controller_id": instrument.get("controller_id"),
                "device_identity": target_identity, "status": dict(response),
                "observed_at": observed_at, "freshness": "fresh", "source": "hardware_ipc",
                "evidence_level": response.get("verification", "protocol_verified"),
                "calibration": self._calibration(response)}

    def read_sensor(self, *, operator: str, target_identity: str, sensor: str, channel: int) -> dict[str, Any]:
        """Acquire one raw temperature/OD observation without actuating."""
        self._require_operator(operator)
        instrument = self._instrument_for_target(target_identity)
        if sensor not in {"temperature", "od"}:
            raise ValueError("sensor must be temperature or od")
        if isinstance(channel, bool) or not isinstance(channel, int) or channel < 0:
            raise ValueError("channel must be a non-negative integer")
        positions = instrument.get("vial_positions", [])
        if channel >= len(positions):
            raise ValueError("channel is not registered for target instrument")
        response = self._call({"operation": "read_sensor", "target_identity": target_identity,
                               "parameters": {"sensor": sensor, "channel": channel},
                               "operator": operator})
        reported_identity = response.get("device_identity")
        if reported_identity is not None and reported_identity != target_identity:
            raise HardwareBrokerProtocolError("sensor identity does not match target identity")
        if "value" not in response and "raw_value" not in response:
            raise HardwareBrokerProtocolError("sensor response is missing raw value")
        calibration = self._calibration(response)
        calibrated = calibration.get("state") in {"calibrated", "valid", "verified"} and bool(
            calibration.get("artifact_id") or calibration.get("artifact_digest"))
        raw_value = self._numeric(response.get("value", response.get("raw_value")))
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise HardwareBrokerProtocolError("sensor response raw value is malformed")
        derived = response.get("derived_value") if calibrated else None
        vial = positions[channel] if isinstance(positions[channel], Mapping) else {}
        return {"instrument_id": instrument.get("id"), "device_identity": target_identity,
                "controller_id": instrument.get("controller_id"),
                "vial_position_id": vial.get("id"), "sensor": sensor, "channel": channel,
                "raw_metric": response.get("metric") or f"{sensor}_raw", "raw_value": raw_value,
                "derived_value": derived, "unit": response.get("unit", "ADC"),
                "observed_at": response.get("observed_at") or datetime.now(UTC).isoformat(),
                "freshness": "fresh", "source": "hardware_ipc", "calibration": calibration,
                "evidence_level": response.get("verification", "protocol_verified")}

    def command(self, operation: str, *, operator: str, target_identity: str,
                parameters: Mapping[str, Any], lease_token: str | None = None,
                controller_generation: int | None = None, physical: bool = False,
                command_id: str | None = None) -> dict[str, Any]:
        self._require_operator(operator); self._require_target(target_identity)
        if operation not in _ACTUATORS:
            raise ValueError(f"unsupported broker operation {operation}")
        if physical is not True:
            raise PermissionError("physical opt-in is required")
        authority = self.store.hardware_authority()
        current_generation = authority.get("generation") if authority else None
        authority_domain = authority.get("domain") if authority else None
        if not isinstance(controller_generation, int) or isinstance(controller_generation, bool) or controller_generation <= 0 or controller_generation != current_generation:
            raise ValueError("controller generation is stale or missing")
        if not isinstance(lease_token, str) or not lease_token:
            raise ValueError("active lease is required")
        self.store.validate_control_lease(lease_token=lease_token, owner=operator,
                                          generation=controller_generation, authority_domain=authority_domain)
        validate_device_operation(operation, parameters)
        bounds = {"set_stir": (("stir_duration_ms", "duration_ms"), ("stir_level", "level")),
                  "set_output": (("od_led_level", "level"),), "pulse_pump": (("pump_duration_ms", "duration_ms"),),
                  "pulse_heater": (("heater_duration_ms", "duration_ms"), ("heater_level", "level"))}
        for name, key in bounds.get(operation, ()):
            value = parameters.get(key); low, high = ACTUATOR_BOUNDS[name]
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError(f"{name} must be between {low} and {high}")
        payload = {"operation": operation, "target_identity": target_identity, "parameters": dict(parameters),
                   "physical": True, "operator": operator, "lease_token": lease_token,
                   "controller_generation": controller_generation}
        if command_id is not None: payload["command_id"] = command_id
        return self._call(payload)

    def safe_stop(self, *, operator: str, physical: bool = False,
                  command_id: str | None = None) -> dict[str, Any]:
        self._require_operator(operator)
        if physical is not True:
            raise PermissionError("physical opt-in is required")
        authority = self.store.hardware_authority()
        generation = authority.get("generation") if authority else None
        if not isinstance(generation, int) or isinstance(generation, bool) or generation <= 0:
            raise ValueError("controller generation is stale or missing")
        command_id = command_id or f"safe-stop-{uuid4()}"
        results: list[dict[str, Any]] = []
        for index, instrument in enumerate(self.store.list_instruments()):
            item_id = f"{command_id}:{index}"
            device_identity = instrument.get("device_identity")
            if not isinstance(device_identity, str) or not device_identity:
                results.append({"command_id": item_id, "request_accepted": False,
                                "verification": "unverified",
                                "error": "instrument has no provisioned device identity"})
                continue
            payload = {"operation": "safe_stop", "target_identity": device_identity,
                       "parameters": {}, "physical": True, "operator": operator,
                       "controller_generation": generation, "command_id": item_id}
            try:
                results.append(self._call(payload))
            except Exception as error:
                results.append({"command_id": item_id, "request_accepted": False,
                                "verification": "unverified", "error": str(error)})
        accepted = bool(results) and all(item.get("request_accepted", False) for item in results)
        return {"command_id": command_id, "request_accepted": accepted,
                "verification": "protocol_verified" if accepted else "unverified", "results": results}

    @staticmethod
    def _require_operator(operator: str) -> None:
        if not isinstance(operator, str) or not operator:
            raise PermissionError("operator attribution is required")

    def _require_target(self, target_identity: str) -> None:
        if not isinstance(target_identity, str) or not target_identity:
            raise ValueError("target identity is required")
        if not any(item.get("device_identity") == target_identity for item in self.store.list_instruments()):
            raise ValueError("target identity is not registered")
