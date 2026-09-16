"""Controller-owned, typed brokerage to the private hardware daemon."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Mapping

from ..evolver_edge.hardware import ACTUATOR_BOUNDS, validate_device_operation
from ..evolver_edge.hardware_ipc import DEFAULT_SOCKET, request as ipc_request
from ..evolver_edge.store import EdgeStore


class HardwareBrokerError(RuntimeError):
    kind = "HardwareError"


class HardwareUnavailable(HardwareBrokerError):
    kind = "HardwareUnavailable"


class HardwareProtocolError(HardwareBrokerError):
    kind = "HardwareProtocolError"


Request = Callable[[str | Path, dict[str, Any], float | None], dict[str, Any]]


class HardwareBroker:
    """Forward bounded hardware operations while retaining controller context."""

    def __init__(self, store: EdgeStore | None = None, *, socket_path: str | Path | None = None,
                 request: Request = ipc_request, timeout: float = 5.0) -> None:
        self.store = store
        self.socket_path = socket_path or os.environ.get("EVOLVER_HARDWARE_SOCKET", DEFAULT_SOCKET)
        self.request = request
        self.timeout = timeout

    def _send(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self.request(self.socket_path, payload, self.timeout)
        except (OSError, TimeoutError, ConnectionError) as error:
            raise HardwareUnavailable(f"hardware service unavailable: {error}") from error
        except Exception as error:
            kind = getattr(error, "kind", "")
            if kind in {"ProbeError", "HardwareProtocolError"} or any(
                    marker in str(error).lower() for marker in ("protocol", "reply", "malformed")):
                raise HardwareProtocolError(f"hardware protocol rejected request: {error}") from error
            raise HardwareUnavailable(f"hardware service unavailable: {error}") from error
        if not isinstance(result, dict):
            raise HardwareProtocolError("hardware service returned a non-object result")
        return result

    @staticmethod
    def _operator(operator: str) -> str:
        if not isinstance(operator, str) or not operator.strip():
            raise PermissionError("authenticated operator attribution is required")
        return operator.strip()

    def discover(self, *, operator: str) -> dict[str, Any]:
        return self._send({"operation": "discover", "operator": self._operator(operator)})

    def protocol_test(self, *, operator: str) -> dict[str, Any]:
        return self._send({"operation": "protocol_test", "operator": self._operator(operator)})

    def command(self, command: Mapping[str, Any], *, operator: str) -> dict[str, Any]:
        operator = self._operator(operator)
        operation = command.get("operation")
        if not isinstance(operation, str):
            raise ValueError("hardware operation is required")
        parameters = command.get("parameters")
        if not isinstance(parameters, Mapping):
            raise ValueError("hardware parameters must be an object")
        validate_device_operation(operation, parameters)
        bounds = {
            "set_output": (("od_led_level", "level"),),
            "pulse_pump": (("pump_duration_ms", "duration_ms"),),
            "set_stir": (("stir_duration_ms", "duration_ms"), ("stir_level", "level")),
            "pulse_heater": (("heater_duration_ms", "duration_ms"), ("heater_level", "level")),
        }.get(operation, ())
        for name, key in bounds:
            value = parameters.get(key)
            low, high = ACTUATOR_BOUNDS[name]
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError(f"{name} must be between {low} and {high}")
        target = command.get("target_identity")
        if not isinstance(target, str) or not target:
            raise ValueError("target_identity is required")
        generation = command.get("controller_generation")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation <= 0:
            raise PermissionError("active positive controller generation is required")
        if command.get("physical") is not True:
            raise PermissionError("physical opt-in is required")
        token, owner = command.get("lease_token"), command.get("lease_owner")
        if not isinstance(token, str) or not token or owner != operator:
            raise PermissionError("active operator lease is required")
        if self.store is not None:
            binding = self.store.binding() or {}
            if generation != binding.get("generation"):
                raise PermissionError("controller generation is stale")
            self.store.validate_control_lease(lease_token=token, owner=operator, generation=generation)
            if not any(item.get("device_identity") == target for item in self.store.list_instruments()):
                raise ValueError("target identity is not registered")
        payload = dict(command)
        payload.update({"operator": operator, "lease_owner": operator,
                        "parameters": dict(parameters), "target_identity": target,
                        "controller_generation": generation})
        return self._send(payload)
