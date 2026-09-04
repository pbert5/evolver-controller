"""Pure, deterministic calibration evidence and fitting primitives.

This module never talks to hardware.  It preserves individual observations and
only exposes transformations whose signal path is understood.  OD fitting is
intentionally explicitly unsupported until the min-eVOLVER optical path is
verified against a historical transform.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence


EVIDENCE_TYPES = frozenset({"temperature", "optical_density", "od_blank", "pump_flow_rate", "pump_direction", "vial_position", "custom"})
FIRMWARE_SUPPORTED_PROCEDURES = frozenset()
SESSION_TRANSITIONS = {"collecting": frozenset({"review", "cancelled", "rejected"}), "review": frozenset({"review", "ready_to_accept", "cancelled", "rejected"}), "ready_to_accept": frozenset({"completed", "cancelled", "rejected"}), "completed": frozenset(), "cancelled": frozenset(), "rejected": frozenset()}
class CalibrationConflictError(ValueError): pass

CALIBRATION_RUN_STATES = frozenset({"ready", "running", "paused", "completed", "failed", "stopped"})


def calibration_run_definition(*, run_id: str, calibration_type: str,
                               instrument_id: str, component_id: str | None = None,
                               vial_position_id: str | None = None) -> dict[str, Any]:
    """Return the immutable bundle payload for an edge calibration run.

    Calibration is an experiment with ordinary run provenance.  The payload
    contains no executable code and deliberately has no calibration
    requirement: it produces the evidence later used to create an artifact.
    """
    if calibration_type not in {"temperature", "pump_flow_rate"}:
        raise ValueError("only temperature and pump_flow_rate calibration runs are supported")
    if not run_id or not instrument_id:
        raise ValueError("calibration run requires run_id and instrument_id")
    return {"id": f"calibration-bundle:{run_id}", "name": f"Calibration {run_id}",
            "purpose": "commissioning", "schema_version": "1",
            "execution_mode": "declarative_state_machine",
            "source": {"experiment_id": f"calibration:{run_id}", "dataset_revision": "1", "created_at": "runtime"},
            "resolved_definition": {"content": {"calibration_type": calibration_type,
                "instrument_id": instrument_id, "component_id": component_id,
                "vial_position_id": vial_position_id}},
            "execution_plan": {"content": {"calibration_type": calibration_type,
                "instrument_id": instrument_id, "component_id": component_id,
                "vial_position_id": vial_position_id}},
            "runtime_parameters": [], "source_metadata": [],
            "calibration_requirements": []}


def calibration_run_state(*, run_id: str, calibration_type: str,
                          instrument_id: str, component_id: str | None = None,
                          vial_position_id: str | None = None) -> dict[str, Any]:
    """Return the effective state stored on a calibration ExperimentRun."""
    if calibration_type not in {"temperature", "pump_flow_rate"}:
        raise ValueError("unsupported calibration run type")
    return {"kind": "calibration", "run_id": run_id, "calibration_type": calibration_type,
            "instrument_id": instrument_id, "component_id": component_id,
            "vial_position_id": vial_position_id, "state": "running", "observations": []}


def assess_artifact(artifact: Mapping[str, Any], *, active: bool = False) -> dict[str, Any]:
    """Assess immutable artifact evidence without changing the artifact."""
    reasons: list[str] = []
    if artifact.get("calibration_type") not in {"temperature", "pump_flow_rate"}:
        reasons.append("unsupported_calibration_type")
    if not artifact.get("artifact_digest") or not artifact.get("evidence_digest"):
        reasons.append("missing_digest")
    if not isinstance(artifact.get("coefficients"), Mapping):
        reasons.append("missing_coefficients")
    status = "valid" if not reasons else "invalid"
    return {"artifact_id": artifact.get("id"), "status": status, "active": bool(active and status == "valid"),
            "reasons": reasons}


def activation_record(artifact: Mapping[str, Any], *, run_id: str,
                      activated_by: str) -> dict[str, Any]:
    assessment = assess_artifact(artifact)
    if assessment["status"] != "valid":
        raise ValueError("only a valid calibration artifact may be activated")
    if not run_id or not activated_by:
        raise ValueError("activation requires run_id and activated_by")
    return {"event_type": "calibration_activated", "artifact_id": artifact.get("id"),
            "artifact_digest": artifact.get("artifact_digest"), "run_id": run_id,
            "activated_by": activated_by}
def transition_session(session: Mapping[str, Any], target: str) -> dict[str, Any]:
    current = str(session.get("state", ""))
    if target not in SESSION_TRANSITIONS.get(current, frozenset()): raise CalibrationConflictError(f"illegal calibration session transition: {current} -> {target}")
    result = dict(session); result["state"] = target; return result
def validate_observation(calibration_type: str, observation: Mapping[str, Any]) -> dict[str, Any]:
    item = dict(observation)
    if calibration_type == "pump_flow_rate":
        try: duration, volume = float(item["pulse_duration_ms"]), float(item["delivered_volume_ul"])
        except (KeyError, TypeError, ValueError) as exc: raise ValueError("pump_flow_rate observations require pulse_duration_ms and delivered_volume_ul") from exc
        if duration <= 0 or volume < 0 or not math.isfinite(duration + volume): raise ValueError("pump_flow_rate observation values are invalid")
        item.setdefault("source_type", "manual"); item.setdefault("raw_metric", "pump_flow"); return item
    if not isinstance(item.get("raw_value"), (int, float)) or not isinstance(item.get("reference_value"), (int, float)): raise ValueError(f"{calibration_type} observations require raw_value and reference_value")
    item.setdefault("source_type", "manual"); return item
def derive_temperature(raw: Mapping[str, Any], artifact: Mapping[str, Any]) -> dict[str, Any] | None:
    if raw.get("metric") != "thermistor_raw" or artifact.get("calibration_type") != "temperature" or artifact.get("assessment", {}).get("status") != "valid": return None
    if raw.get("instrument_id") != artifact.get("instrument_id") or raw.get("vial_position_id") != artifact.get("vial_position_id"): return None
    value, coefficients = raw.get("value"), artifact.get("coefficients", {})
    if not isinstance(value, (int, float)) or not isinstance(coefficients, Mapping): return None
    try: calibrated = float(coefficients["slope"]) * float(value) + float(coefficients["intercept"])
    except (KeyError, TypeError, ValueError): return None
    bounds = artifact.get("calibration_range", {}); extrapolated = isinstance(bounds, Mapping) and (float(value) < float(bounds.get("raw_min", value)) or float(value) > float(bounds.get("raw_max", value)))
    return {"instrument_id": raw.get("instrument_id"), "vial_position_id": raw.get("vial_position_id"), "metric": "temperature_c", "value": calibrated, "unit": "°C", "calibration_state": "valid", "extrapolated": extrapolated, "source_raw_metric": "thermistor_raw", "source_stream_id": raw.get("stream_id"), "source_sequence": raw.get("sequence"), "calibration_artifact_id": artifact.get("id"), "calibration_artifact_digest": artifact.get("artifact_digest"), "calibration_method": artifact.get("method"), "calibration_method_version": artifact.get("method_version"), "calibration_assessment": artifact.get("assessment")}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def fit_temperature_linear_v1(observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Fit reference temperature = slope * raw ADC + intercept."""
    points = []
    for item in observations:
        try:
            raw = float(item["raw_value"])
            reference = float(item["reference_value"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("temperature observations require numeric raw_value and reference_value") from exc
        if not math.isfinite(raw) or not math.isfinite(reference):
            raise ValueError("temperature observations must be finite")
        points.append((raw, reference))
    if len(points) < 2 or len({raw for raw, _ in points}) < 2:
        raise ValueError("temperature_linear_v1 requires at least two distinct raw observations")
    x_bar = sum(raw for raw, _ in points) / len(points)
    y_bar = sum(ref for _, ref in points) / len(points)
    denominator = sum((raw - x_bar) ** 2 for raw, _ in points)
    slope = sum((raw - x_bar) * (ref - y_bar) for raw, ref in points) / denominator
    intercept = y_bar - slope * x_bar
    residuals = [ref - (slope * raw + intercept) for raw, ref in points]
    rmse = math.sqrt(sum(error * error for error in residuals) / len(residuals))
    return {
        "method": "temperature_linear_v1", "method_version": "1",
        "coefficients": {"slope": slope, "intercept": intercept, "input_unit": "ADC", "output_unit": "°C"},
        "fit_diagnostics": {"observations": len(points), "rmse": rmse, "max_absolute_error": max(abs(error) for error in residuals)},
        "calibration_range": {"raw_min": min(raw for raw, _ in points), "raw_max": max(raw for raw, _ in points), "reference_min": min(ref for _, ref in points), "reference_max": max(ref for _, ref in points)},
    }


def fit_pump_flow_v1(observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Calculate an offline flow coefficient from operator-entered volumes."""
    rates = []
    for item in observations:
        try:
            duration = float(item["pulse_duration_ms"])
            volume = float(item["delivered_volume_ul"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("pump observations require pulse_duration_ms and delivered_volume_ul") from exc
        if duration <= 0 or volume < 0 or not math.isfinite(duration + volume):
            raise ValueError("pump observation duration must be positive and volume must be finite")
        rates.append(volume / duration)
    if not rates:
        raise ValueError("at least one pump observation is required")
    mean = sum(rates) / len(rates)
    return {"method": "pump_flow_rate_v1", "method_version": "1", "coefficients": {"ul_per_ms": mean}, "fit_diagnostics": {"observations": len(rates), "min_ul_per_ms": min(rates), "max_ul_per_ms": max(rates)}}


def calculate_candidate(calibration_type: str, observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if calibration_type == "temperature":
        return fit_temperature_linear_v1(observations)
    if calibration_type == "pump_flow_rate":
        return fit_pump_flow_v1(observations)
    if calibration_type in {"optical_density", "od_blank"}:
        raise ValueError("OD calibration method not yet supported for this min-eVOLVER signal path")
    raise ValueError(f"no supported fitting method for calibration type {calibration_type}")
