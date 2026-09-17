from __future__ import annotations

from http import HTTPStatus

import pytest

from meta_webui_application_backend import evolver_controller
from meta_webui_application_backend.evolver_control.actions import dispatch


@pytest.mark.parametrize(("catalog_id", "expected"), [
    ("evolver.calibrations.list", "list"),
    ("evolver.calibrations.sessions.create", "create"),
    ("evolver.calibrations.sessions.add_observation", "observation"),
    ("evolver.calibrations.sessions.fit", "fit"),
    ("evolver.calibrations.sessions.accept", "accept"),
    ("evolver.calibrations.sessions.cancel", "cancel"),
    ("evolver.calibrations.sessions.capture", "capture"),
    ("evolver.calibrations.artifacts.deliver", "deliver"),
    ("evolver.calibrations.artifacts.supersede", "supersede"),
    ("evolver.calibrations.artifacts.invalidate", "invalidate"),
])
def test_frozen_calibration_catalog_ids_dispatch(monkeypatch, catalog_id, expected) -> None:
    calls = []

    def fake(name):
        def invoke(*args, **kwargs):
            calls.append(name)
            return HTTPStatus.OK, {"mapped": name}
        return invoke

    def fake_session(*args, **kwargs):
        mutation = args[1]
        calls.append(mutation)
        return HTTPStatus.OK, {"mapped": mutation}

    monkeypatch.setattr(evolver_controller, "calibrations", fake("list"))
    monkeypatch.setattr(evolver_controller, "create_calibration_session", fake("create"))
    monkeypatch.setattr(evolver_controller, "calibration_session_mutation", fake_session)
    monkeypatch.setattr(evolver_controller, "capture_latest_observation", fake("capture"))
    monkeypatch.setattr(evolver_controller, "deliver_calibration_artifact", fake("deliver"))
    monkeypatch.setattr(evolver_controller, "supersede_calibration_artifact", fake("supersede"))
    monkeypatch.setattr(evolver_controller, "invalidate_calibration_artifact", fake("invalidate"))
    operator = evolver_controller.OperatorIdentity("alice", "test", frozenset({"manage_calibration"}))
    parameters = {"session_id": "session-1", "artifact_id": "artifact-1",
                  "superseding_artifact_id": "artifact-2", "reason": "expired",
                  "raw_value": 100, "reference_value": 20}

    status, result = dispatch(catalog_id, parameters, operator=operator)

    assert status is HTTPStatus.OK
    assert result == {"mapped": expected}
    assert calls == [expected]


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
