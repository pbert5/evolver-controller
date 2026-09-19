from __future__ import annotations

import pytest

from evolver_controller.bundle import BundleResolutionError, canonical_digest, validate_bundle


def bundle(**changes):
    value = {"id": "bundle-1", "purpose": "research", "execution_mode": "declarative_state_machine",
             "execution_plan": {"steps": []}, "calibration_requirements": [], "calibration_references": []}
    value.update(changes)
    value["digest"] = canonical_digest(value)
    return value


def test_received_bundle_with_valid_digest_and_references_is_accepted() -> None:
    reference = {"artifact_id": "artifact-1", "artifact_digest": "sha256:artifact",
                 "instrument_id": "instrument-1", "vial_position_id": "vial-1",
                 "calibration_type": "temperature", "method": "reference", "method_version": "1"}
    received = bundle(calibration_references=[reference])
    assert validate_bundle(received) == received


def test_received_bundle_rejects_digest_tampering() -> None:
    received = bundle()
    received["execution_plan"] = {"steps": ["tampered"]}
    with pytest.raises(BundleResolutionError, match="digest"):
        validate_bundle(received)


def test_received_bundle_rejects_invalid_reference() -> None:
    received = bundle(calibration_references=[{"artifact_id": "artifact-1"}])
    received["digest"] = canonical_digest({key: value for key, value in received.items() if key != "digest"})
    with pytest.raises(BundleResolutionError, match="immutable identity"):
        validate_bundle(received)
