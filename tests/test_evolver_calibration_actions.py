from __future__ import annotations

from http import HTTPStatus

from meta_webui_application_backend import evolver_controller
from meta_webui_application_backend.evolver_control.actions import dispatch


def test_central_calibration_actions_use_manage_calibration_and_strip_envelope(monkeypatch) -> None:
    calls = []

    def mutate(session_id, mutation, body, *, operator, state_root):
        calls.append((session_id, mutation, body, operator, state_root))
        return HTTPStatus.OK, {"session_id": session_id}

    monkeypatch.setattr(evolver_controller, "calibration_session_mutation", mutate)
    operator = evolver_controller.OperatorIdentity("alice", "test", frozenset({"manage_calibration"}))
    status, result = dispatch("calibration_observation", {
        "session_id": "session-1", "action": "observation", "raw_value": 100,
        "reference_value": 20,
    }, operator=operator)
    assert status is HTTPStatus.OK
    assert result == {"session_id": "session-1"}
    assert calls[0][1] == "observation"
    assert calls[0][2] == {"raw_value": 100, "reference_value": 20}


def test_central_calibration_mutations_are_denied_without_permission() -> None:
    operator = evolver_controller.OperatorIdentity("alice", "test", frozenset())
    status, result = dispatch("calibration_create", {"calibration_type": "temperature",
                                                       "instrument_id": "instrument-1"},
                              operator=operator)
    assert status is HTTPStatus.FORBIDDEN
    assert result["kind"] == "OperatorPermissionDenied"
