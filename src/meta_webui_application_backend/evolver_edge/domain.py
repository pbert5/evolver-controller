"""Pure edge-domain validation and planning primitives.

These helpers sit below the CLI/sync layers.  They validate bounded intent and
derive calibrated pump timing, but never open a transport or claim that a
device acknowledged a physical action.
"""
from __future__ import annotations

from typing import Any, Mapping

from .store import EdgeStoreError


def bounded_int(value: Any, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise EdgeStoreError(f"{field} must be an integer in {minimum}..{maximum}")
    return value


def validate_bounded_operation(operation: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the small operation vocabulary accepted by edge execution."""
    values = dict(parameters)
    if operation == "safe_stop":
        return {}
    channel = bounded_int(values.get("channel"), field="channel", minimum=0, maximum=5)
    if operation == "pulse_pump":
        duration = bounded_int(values.get("duration_ms"), field="pump duration_ms", minimum=1, maximum=1000)
        if values.get("direction", "forward") != "forward":
            raise EdgeStoreError("reverse pumping is unsupported")
        return {"channel": channel, "direction": "forward", "duration_ms": duration}
    if operation == "set_stir":
        level = bounded_int(values.get("level"), field="stir level", minimum=1, maximum=250)
        duration = bounded_int(values.get("duration_ms"), field="stir duration_ms", minimum=1, maximum=1000)
        return {"channel": channel, "level": level, "duration_ms": duration}
    if operation == "pulse_heater":
        level = bounded_int(values.get("level"), field="heater level", minimum=1, maximum=64)
        duration = bounded_int(values.get("duration_ms"), field="heater duration_ms", minimum=1, maximum=250)
        return {"channel": channel, "level": level, "duration_ms": duration}
    raise EdgeStoreError(f"unsupported bounded operation: {operation}")


def plan_calibrated_dispense(*, artifact: Mapping[str, Any], volume_ul: float,
                             channel: int, maximum_duration_ms: int = 1000) -> dict[str, Any]:
    """Create a pump pulse from immutable flow calibration evidence.

    Calibration coefficients are interpreted as ``volume_ul = slope * ms +
    intercept``.  The result is a plan only; callers must still pass it through
    normal generation, lease, idempotency, and hardware safety gates.
    """
    if isinstance(volume_ul, bool) or not isinstance(volume_ul, (int, float)) or volume_ul <= 0:
        raise EdgeStoreError("dispense volume_ul must be positive")
    bounded_int(channel, field="pump channel", minimum=0, maximum=5)
    bounded_int(maximum_duration_ms, field="maximum dispense duration_ms", minimum=1, maximum=1000)
    if artifact.get("calibration_type") != "pump_flow_rate":
        raise EdgeStoreError("dispense requires a pump_flow_rate calibration artifact")
    if artifact.get("assessment", {}).get("status", "valid") != "valid":
        raise EdgeStoreError("dispense calibration artifact is not valid")
    coefficients = artifact.get("coefficients")
    if not isinstance(coefficients, Mapping):
        raise EdgeStoreError("dispense calibration coefficients are missing")
    try:
        if "ul_per_ms" in coefficients:
            slope, intercept = float(coefficients["ul_per_ms"]), 0.0
        elif "flow_ml_per_min" in coefficients:
            slope, intercept = float(coefficients["flow_ml_per_min"]) / 60.0, 0.0
        else:
            slope, intercept = float(coefficients["slope"]), float(coefficients.get("intercept", 0.0))
    except (KeyError, TypeError, ValueError) as error:
        raise EdgeStoreError("dispense calibration coefficients are invalid") from error
    if slope <= 0:
        raise EdgeStoreError("dispense calibration slope must be positive")
    duration = (float(volume_ul) - intercept) / slope
    rounded = int(round(duration))
    if rounded < 1 or rounded > maximum_duration_ms:
        raise EdgeStoreError("calibrated dispense exceeds pump duration safety bound")
    return {"operation": "pulse_pump", "parameters": {"channel": channel, "direction": "forward",
            "duration_ms": rounded}, "calibration": {"artifact_id": artifact.get("id"),
            "artifact_digest": artifact.get("artifact_digest"), "volume_ul": float(volume_ul),
            "flow_model": "volume_ul=slope*duration_ms+intercept", "duration_ms": rounded}}


def reject_calibrated_dispense(*, reason: str, artifact: Mapping[str, Any] | None = None,
                               run_id: str | None = None, volume_ul: float | None = None) -> dict[str, Any]:
    """Create explicit, non-actuating rejection evidence."""
    return {"disposition": "rejected_calibration", "reason": reason,
            "run_id": run_id, "requested_volume_ul": volume_ul,
            "calibration": {"artifact_id": artifact.get("id") if artifact else None,
                             "artifact_digest": artifact.get("artifact_digest") if artifact else None}}
