"""Pure edge-domain validation and planning primitives.

These helpers sit below the CLI/sync layers.  They validate bounded intent and
derive calibrated pump timing, but never open a transport or claim that a
device acknowledged a physical action.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

from .bundle import calibration_artifact_digest
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


def plan_calibrated_temperature(*, artifact: Mapping[str, Any], target_temperature_c: float,
                                instrument: Mapping[str, Any], vial_position_id: str | None = None,
                                channel: Any = None) -> dict[str, Any]:
    """Plan a bounded Celsius setpoint using one immutable vial calibration.

    The returned command is typed controller intent.  It contains the raw ADC
    target expected by the firmware-facing boundary, but this function never
    opens a transport or performs actuation.
    """
    if not isinstance(artifact, Mapping):
        raise EdgeStoreError("temperature calibration artifact is required")
    if artifact.get("calibration_type") != "temperature":
        raise EdgeStoreError("temperature setpoint requires a temperature calibration artifact")
    assessment = artifact.get("assessment")
    if not isinstance(assessment, Mapping) or assessment.get("status") != "valid":
        raise EdgeStoreError("temperature calibration artifact is not valid")
    required = ("id", "artifact_digest", "instrument_id", "vial_position_id", "method", "method_version")
    if any(not isinstance(artifact.get(field), str) or not artifact[field] for field in required):
        raise EdgeStoreError("temperature calibration artifact lacks immutable identity")
    try:
        if artifact["artifact_digest"] != calibration_artifact_digest(artifact):
            raise EdgeStoreError("temperature calibration artifact digest mismatch")
    except (TypeError, ValueError) as error:
        raise EdgeStoreError("temperature calibration artifact is not canonical JSON") from error
    if artifact["method"] != "temperature_linear_v1":
        raise EdgeStoreError("unsupported temperature calibration method")
    if not isinstance(target_temperature_c, (int, float)) or isinstance(target_temperature_c, bool) \
            or not math.isfinite(float(target_temperature_c)):
        raise EdgeStoreError("temperature target must be finite")
    target = float(target_temperature_c)
    if not 0.0 <= target <= 100.0:
        raise EdgeStoreError("temperature target must be in 0..100 °C")
    if not isinstance(instrument, Mapping) or instrument.get("id") != artifact["instrument_id"]:
        raise EdgeStoreError("temperature calibration instrument does not match target")
    vial = artifact["vial_position_id"] if vial_position_id is None else vial_position_id
    if vial != artifact["vial_position_id"]:
        raise EdgeStoreError("temperature calibration vial does not match target")
    if channel is not None:
        raise EdgeStoreError("temperature channel must be resolved from vial position")
    positions = instrument.get("vial_positions")
    if not isinstance(positions, (list, tuple)):
        raise EdgeStoreError("instrument vial positions are unavailable")
    matches = [item for item in positions if isinstance(item, Mapping) and item.get("id") == vial]
    if len(matches) != 1:
        raise EdgeStoreError("temperature vial position is missing or ambiguous")
    position = matches[0].get("position_index")
    if isinstance(position, bool) or not isinstance(position, int) or not 0 <= position <= 5:
        raise EdgeStoreError("temperature vial position has no bounded channel")
    coefficients = artifact.get("coefficients")
    calibration_range = artifact.get("calibration_range")
    if not isinstance(coefficients, Mapping) or not isinstance(calibration_range, Mapping):
        raise EdgeStoreError("temperature calibration coefficients and range are required")
    try:
        slope = float(coefficients["slope"])
        intercept = float(coefficients["intercept"])
        reference_min = float(calibration_range["reference_min"])
        reference_max = float(calibration_range["reference_max"])
        raw_min_value = calibration_range["raw_min"]
        raw_max_value = calibration_range["raw_max"]
    except (KeyError, TypeError, ValueError) as error:
        raise EdgeStoreError("temperature calibration coefficients and range are invalid") from error
    if isinstance(raw_min_value, bool) or not isinstance(raw_min_value, (int, float)) \
            or isinstance(raw_max_value, bool) or not isinstance(raw_max_value, (int, float)) \
            or not math.isfinite(float(raw_min_value)) or not math.isfinite(float(raw_max_value)) \
            or not float(raw_min_value).is_integer() or not float(raw_max_value).is_integer():
        raise EdgeStoreError("temperature calibration raw bounds are invalid")
    raw_min, raw_max = int(raw_min_value), int(raw_max_value)
    if not all(math.isfinite(value) for value in (slope, intercept, reference_min, reference_max)) \
            or slope == 0 or reference_min > reference_max or raw_min > raw_max:
        raise EdgeStoreError("temperature calibration coefficients and range are invalid")
    if not reference_min <= target <= reference_max:
        raise EdgeStoreError("temperature target is outside calibration range")
    raw_float = (target - intercept) / slope
    raw_target = int(math.floor(raw_float + 0.5))
    if not 1 <= raw_target <= 65535 or not raw_min <= raw_target <= raw_max:
        raise EdgeStoreError("temperature raw target is outside calibration bounds")
    predicted = slope * raw_target + intercept
    return {"operation": "set_temperature", "parameters": {"channel": position,
            "raw_target_adc": raw_target}, "calibration": {
                "artifact_id": artifact["id"], "artifact_digest": artifact["artifact_digest"],
                "method": artifact["method"], "method_version": artifact["method_version"],
                "requested_temperature_c": target, "predicted_temperature_c": predicted,
                "quantization_error_c": predicted - target}}


def reject_calibrated_dispense(*, reason: str, artifact: Mapping[str, Any] | None = None,
                               run_id: str | None = None, volume_ul: float | None = None) -> dict[str, Any]:
    """Create explicit, non-actuating rejection evidence."""
    return {"disposition": "rejected_calibration", "reason": reason,
            "run_id": run_id, "requested_volume_ul": volume_ul,
            "calibration": {"artifact_id": artifact.get("id") if artifact else None,
                             "artifact_digest": artifact.get("artifact_digest") if artifact else None}}
