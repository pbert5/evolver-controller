from __future__ import annotations

import pytest

from meta_webui_application_backend.evolver_edge.bundle import (
    BundleResolutionError,
    calibration_artifact_digest,
    resolve_bundle,
)
from meta_webui_application_backend.evolver_edge import EdgeStore
from meta_webui_application_backend.evolver_controller import resolve_definition_bundle


def requirement(required: bool) -> dict[str, object]:
    return {"capability": "temperature", "required": required, "calibration_type": "temperature",
            "instrument_id": "instrument-1", "vial_position_id": "vial-1"}


def artifact() -> dict[str, object]:
    value: dict[str, object] = {"id": "artifact-1", "instrument_id": "instrument-1", "vial_position_id": "vial-1",
                                "calibration_type": "temperature", "method": "reference", "method_version": "1"}
    value["artifact_digest"] = calibration_artifact_digest(value)
    return value


def test_boolean_required_values_are_valid_and_preserve_optional_semantics() -> None:
    optional = resolve_bundle({"id": "optional", "calibration_requirements": [requirement(False)]}, [])
    assert optional["calibration_requirements"][0]["required"] is False
    assert optional["calibration_references"] == []

    required = resolve_bundle({"id": "required", "calibration_requirements": [requirement(True)]}, [artifact()])
    assert required["calibration_references"][0]["required"] is True


def test_resolver_rejects_duplicate_or_mismatched_selected_evidence() -> None:
    value = artifact()
    with pytest.raises(BundleResolutionError, match="duplicates"):
        resolve_bundle({"id": "duplicate", "calibration_requirements": [requirement(True)]}, [value, dict(value)])
    changed = dict(value, method_version="2")
    with pytest.raises(BundleResolutionError, match="digest"):
        resolve_bundle({"id": "mismatch", "calibration_requirements": [requirement(True)]}, [changed])


def test_edge_preflight_accepts_explicit_true_and_false_references(tmp_path) -> None:
    with EdgeStore(tmp_path) as edge:
        stored = edge.put_calibration_artifact(artifact())
        reference = {"artifact_id": stored["id"], "artifact_digest": stored["artifact_digest"],
                     "instrument_id": "instrument-1", "vial_position_id": "vial-1",
                     "calibration_type": "temperature", "method": "reference", "method_version": "1",
                     "capability": "temperature", "required": True}
        assert edge.calibration_preflight([reference], requirements=[requirement(True)])["eligible"]
        reference["required"] = False
        optional = dict(requirement(False)); optional["capability"] = "temperature-optional"
        reference["capability"] = optional["capability"]
        assert edge.calibration_preflight([reference], requirements=[optional])["eligible"]


def test_definition_adapter_freezes_only_caller_selected_calibration(tmp_path) -> None:
    selected = artifact()
    definition = {
        "id": "definition-1", "name": "temperature run", "dataset_id": "dataset-1",
        "dataset_revision": "rev-7", "definition_digest": "definition-digest",
        "purpose": "research",
        "definition": {"media_type": "application/json", "content": {
            "schema_version": "1", "execution_mode": "declarative_state_machine",
            "execution_plan": {"steps": []}, "runtime_parameters": [], "source_metadata": []}},
        "calibration_requirements": [requirement(True)],
    }
    bundle = resolve_definition_bundle(definition, [selected], resolved_at="2026-08-26T12:00:00Z")

    assert bundle["source"] == {"experiment_id": "definition-1", "dataset_revision": "rev-7", "created_at": "2026-08-26T12:00:00Z"}
    assert bundle["calibration_references"][0]["artifact_id"] == selected["id"]
    assert bundle["digest"]
    # The adapter has no latest-selection path: an empty caller selection is a
    # hard failure for the required declaration even if a catalog artifact exists.
    with pytest.raises(BundleResolutionError, match="required calibration is missing"):
        resolve_definition_bundle(definition, [], resolved_at="2026-08-26T12:00:00Z")
