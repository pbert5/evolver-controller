"""Validation of immutable experiment bundles received by the controller."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

Json = dict[str, Any]
EXPERIMENT_PURPOSES = frozenset({
    "research", "test_fixture", "commissioning", "calibration",
    "validation", "verification", "endurance", "diagnostic",
})
EXECUTION_MODES = frozenset({"declarative_state_machine"})


class BundleResolutionError(ValueError):
    """A received bundle is malformed or fails an immutable-content check."""


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def calibration_artifact_digest(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("artifact_digest", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


CALIBRATION_TARGET_FIELDS = ("instrument_id", "vial_position_id", "component_id", "calibration_type")
CALIBRATION_ARTIFACT_FIELDS = ("id", "artifact_digest", *CALIBRATION_TARGET_FIELDS, "method", "method_version")
CALIBRATION_REQUIREMENT_FIELDS = ("capability", *CALIBRATION_TARGET_FIELDS, "required")


def normalize_calibration_requirement(value: Any, index: int, *, error_type: type[Exception] = BundleResolutionError) -> Json:
    if not isinstance(value, Mapping):
        raise error_type(f"calibration requirement[{index}] is not an object")
    item = dict(value)
    required = item.get("required")
    if not isinstance(required, bool):
        raise error_type(f"calibration requirement[{index}] must declare required as true or false")
    for field in ("capability", "instrument_id", "vial_position_id", "calibration_type"):
        if not isinstance(item.get(field), str) or not item[field]:
            raise error_type(f"calibration requirement[{index}] lacks capability or target identity")
    component = item.get("component_id")
    if component is not None and (not isinstance(component, str) or not component):
        raise error_type(f"calibration requirement[{index}] has an invalid component identity")
    return {field: item.get(field) for field in CALIBRATION_REQUIREMENT_FIELDS}


def calibration_requirement_key(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(value.get(field) for field in ("capability", *CALIBRATION_TARGET_FIELDS))


def validate_bundle(bundle: Mapping[str, Any]) -> Json:
    """Validate and return a received immutable bundle without constructing it."""
    if not isinstance(bundle, Mapping):
        raise BundleResolutionError("bundle must be an object")
    payload = dict(bundle)
    supplied_digest = payload.pop("digest", None)
    if not isinstance(supplied_digest, str) or not supplied_digest:
        raise BundleResolutionError("received bundle must contain a digest")
    if canonical_digest(payload) != supplied_digest:
        raise BundleResolutionError("bundle digest does not match canonical content")
    requirements = payload.get("calibration_requirements", [])
    if not isinstance(requirements, list):
        raise BundleResolutionError("calibration_requirements must be a list")
    normalized = [normalize_calibration_requirement(item, index) for index, item in enumerate(requirements)]
    keys = [calibration_requirement_key(item) for item in normalized]
    if len(keys) != len(set(keys)):
        raise BundleResolutionError("calibration requirements must not duplicate a capability target")
    references = payload.get("calibration_references", [])
    if not isinstance(references, list):
        raise BundleResolutionError("calibration_references must be a list")
    for index, reference in enumerate(references):
        if not isinstance(reference, Mapping):
            raise BundleResolutionError(f"calibration reference[{index}] is not an object")
        required = ("artifact_id", "artifact_digest", "instrument_id", "vial_position_id",
                    "calibration_type", "method", "method_version")
        if any(not isinstance(reference.get(field), str) or not reference[field] for field in required):
            raise BundleResolutionError(f"calibration reference[{index}] lacks immutable identity")
    payload["calibration_requirements"] = normalized
    payload["digest"] = supplied_digest
    return payload


def experiment_purpose(value: Any) -> str:
    if value is None:
        # Bundles created before purpose became required retain the stable
        # compatibility view used by EdgeStore.bundle().
        return "research"
    if not isinstance(value, str) or value not in EXPERIMENT_PURPOSES:
        raise BundleResolutionError(f"unsupported experiment purpose: {value!r}")
    return value
