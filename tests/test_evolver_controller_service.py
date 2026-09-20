from __future__ import annotations

from evolver_controller import service


def test_service_construction_passes_explicit_hardware_socket(tmp_path):
    with service.EdgeStore(tmp_path) as store:
        broker = service.build_hardware_broker(store, "/configured/hardware.sock")

    assert broker.socket_path == "/configured/hardware.sock"


def test_service_operator_identity_matches_live_mutation_permissions() -> None:
    identity = service.build_operator_identity("edge")

    assert identity.subject == "edge"
    assert identity.permissions == frozenset({"hardware_maintenance", "manage_calibration", "operate_run"})
