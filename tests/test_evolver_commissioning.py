from datetime import datetime, timedelta, timezone

import pytest

from meta_webui_application_backend.evolver_commissioning import advance_commissioning, assignment_warning, calibration_staleness


def test_commissioning_requires_physical_or_calibrated_evidence() -> None:
    record = {"state": "calibration_evaluated"}
    with pytest.raises(ValueError):
        advance_commissioning(record, "commission", evidence="protocol_verified")
    assert advance_commissioning(record, "commission", evidence="physically_verified")["state"] == "ready"


def test_stale_calibration_is_advisory_and_does_not_interrupt_active_run() -> None:
    calibration = calibration_staleness({"created_at": (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()}, max_age_days=180)
    assert calibration["staleness"] == "stale"
    warning = assignment_warning(calibration, active_run=True)
    assert warning["warning"] is True
    assert warning["active_run_uninterrupted"] is True
