from __future__ import annotations

from meta_webui_application_backend.evolver_edge import service


def test_service_construction_passes_explicit_hardware_socket(tmp_path):
    with service.EdgeStore(tmp_path) as store:
        broker = service.build_hardware_broker(store, "/configured/hardware.sock")

    assert broker.socket_path == "/configured/hardware.sock"
