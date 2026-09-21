"""Hardware wire validation shared with the controller IPC boundary only."""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping

from .store import EdgeStoreError


DEVICE_PROTOCOL_VERSION = "evolver.device.v2"
ACTUATOR_BOUNDS = {
    "od_led_level": (0, 255), "pump_duration_ms": (1, 1000),
    "stir_duration_ms": (1, 1000), "stir_level": (1, 250),
    "heater_duration_ms": (1, 250), "heater_level": (1, 64),
}


class ProbeOutcome(StrEnum):
    OPEN = "open"
    PERMISSION = "permission"
    BUSY = "busy"
    TIMEOUT = "timeout"
    PROTOCOL = "protocol"
    MALFORMED = "malformed"
    STATUS = "status"
    IDENTITY = "identity"


class HardwareUnavailableError(EdgeStoreError):
    outcome: ProbeOutcome = ProbeOutcome.OPEN
    evidence: Mapping[str, Any] = {}

    def __init__(self, message: str, *, outcome: ProbeOutcome | None = None,
                 evidence: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.outcome = outcome or ProbeOutcome.OPEN
        self.evidence = dict(evidence or {"detail": message})


class ProbeError(HardwareUnavailableError):
    def __init__(self, outcome: ProbeOutcome, message: str,
                 *, evidence: Mapping[str, Any] | None = None,
                 cause: BaseException | None = None) -> None:
        super().__init__(message, outcome=outcome,
                         evidence={"outcome": outcome.value, **(evidence or {})})
        if cause is not None:
            self.__cause__ = cause


def validate_device_operation(operation: str, parameters: Mapping[str, Any]) -> None:
    """Reject unsupported actuator semantics before hardware IPC."""
    if operation not in {"get_status", "read_sensor", "safe_stop", "set_output", "pulse_pump", "set_stir", "pulse_heater", "set_temperature"}:
        raise ValueError(f"unsupported device operation {operation}")
    if operation == "pulse_pump" and parameters.get("direction", "forward") != "forward":
        raise ValueError("reverse pumping is unsupported by verified firmware")
    if operation in {"read_sensor", "set_output", "pulse_pump", "pulse_heater", "set_temperature"}:
        channel = parameters.get("channel")
        if isinstance(channel, bool) or not isinstance(channel, int):
            raise ValueError("channel must be an integer")
        high = 5 if operation in {"pulse_pump", "set_temperature"} else 1
        if not 0 <= channel <= high:
            raise ValueError(f"channel must be between 0 and {high}")
    if operation == "set_stir":
        channel = parameters.get("channel")
        if isinstance(channel, bool) or not isinstance(channel, int) or not 0 <= channel <= 1:
            raise ValueError("stir channel must be between 0 and 1")
