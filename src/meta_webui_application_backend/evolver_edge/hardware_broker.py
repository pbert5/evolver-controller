"""Controller-owned brokerage boundary for the private hardware socket."""
from __future__ import annotations

import os
from typing import Any, Callable, Mapping

from .hardware import ACTUATOR_BOUNDS, validate_device_operation
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
        return self._call({"operation": "discover", "operator": operator})

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

    def command(self, operation: str, *, operator: str, target_identity: str,
                parameters: Mapping[str, Any], lease_token: str | None = None,
                controller_generation: int | None = None, physical: bool = False,
                command_id: str | None = None) -> dict[str, Any]:
        self._require_operator(operator); self._require_target(target_identity)
        if operation not in _ACTUATORS:
            raise ValueError(f"unsupported broker operation {operation}")
        if physical is not True:
            raise PermissionError("physical opt-in is required")
        binding = self.store.binding(); current_generation = binding.get("generation") if isinstance(binding, Mapping) else None
        if not isinstance(controller_generation, int) or isinstance(controller_generation, bool) or controller_generation <= 0 or controller_generation != current_generation:
            raise ValueError("controller generation is stale or missing")
        if not isinstance(lease_token, str) or not lease_token:
            raise ValueError("active lease is required")
        self.store.validate_control_lease(lease_token=lease_token, owner=operator, generation=controller_generation)
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

    @staticmethod
    def _require_operator(operator: str) -> None:
        if not isinstance(operator, str) or not operator:
            raise PermissionError("operator attribution is required")

    def _require_target(self, target_identity: str) -> None:
        if not isinstance(target_identity, str) or not target_identity:
            raise ValueError("target identity is required")
        if not any(item.get("device_identity") == target_identity for item in self.store.list_instruments()):
            raise ValueError("target identity is not registered")
