from __future__ import annotations

from http import HTTPStatus

from meta_webui_application_backend.evolver_control.actions import dispatch
from meta_webui_application_backend.evolver_control.hardware import HardwareBroker
from meta_webui_application_backend.evolver_controller import OperatorIdentity


OPERATOR = OperatorIdentity("alice", "test", frozenset({"hardware_maintenance"}))


def test_hardware_discovery_is_brokered_with_operator_attribution() -> None:
    calls = []

    def request(path, payload, timeout):
        calls.append((path, payload, timeout))
        return {"device_identity": "MEV-1", "source": "physical"}

    status, result = dispatch("hardware_discover", {"operator": "ignored"},
                              operator=OPERATOR, hardware_broker=HardwareBroker(request=request))
    assert status is HTTPStatus.OK
    assert result["device_identity"] == "MEV-1"
    assert calls[0][1] == {"operation": "discover", "operator": "alice"}


def test_hardware_broker_maps_unavailable_and_protocol_failures() -> None:
    def unavailable(path, payload, timeout):
        raise OSError("no such socket")

    status, result = dispatch("hardware_discover", {}, operator=OPERATOR,
                              hardware_broker=HardwareBroker(request=unavailable))
    assert status is HTTPStatus.SERVICE_UNAVAILABLE
    assert result["kind"] == "HardwareUnavailable"

    def protocol(path, payload, timeout):
        error = RuntimeError("invalid reply")
        error.kind = "ProbeError"  # type: ignore[attr-defined]
        raise error

    status, result = dispatch("hardware_protocol_test", {}, operator=OPERATOR,
                              hardware_broker=HardwareBroker(request=protocol))
    assert status is HTTPStatus.BAD_GATEWAY
    assert result["kind"] == "HardwareProtocolError"


def test_mutating_hardware_requires_generation_lease_target_physical_and_bounds() -> None:
    broker = HardwareBroker(request=lambda path, payload, timeout: payload)
    base = {"operation": "set_stir", "target_identity": "MEV-1",
            "parameters": {"channel": 0, "duration_ms": 100, "level": 1}}
    for missing in ({}, {"controller_generation": 1},
                    {"controller_generation": 1, "lease_token": "t", "lease_owner": "alice"},
                    {"controller_generation": 1, "lease_token": "t", "lease_owner": "alice", "physical": True,
                     "target_identity": ""}):
        try:
            broker.command({**base, **missing}, operator="alice")
        except (PermissionError, ValueError):
            pass
        else:
            raise AssertionError("unsafe command was accepted")
    result = broker.command({**base, "controller_generation": 1, "lease_token": "t",
                             "lease_owner": "alice", "physical": True}, operator="alice")
    assert result["operator"] == "alice"
    try:
        broker.command({**base, "controller_generation": 1, "lease_token": "t",
                        "lease_owner": "alice", "physical": True,
                        "parameters": {"channel": 0, "duration_ms": 100, "level": 999}}, operator="alice")
    except ValueError:
        pass
    else:
        raise AssertionError("out-of-bounds command was accepted")
