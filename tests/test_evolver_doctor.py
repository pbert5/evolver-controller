from pathlib import Path

from meta_webui_application_backend.evolver_edge import EdgeStore
from meta_webui_application_backend.evolver_edge.cli import main
from meta_webui_application_backend.evolver_edge.doctor import doctor_report


def test_doctor_is_read_only_and_reports_offline_operator_state(tmp_path: Path) -> None:
    with EdgeStore(tmp_path) as store:
        original_identity = store.identity()
        report = doctor_report(
            store,
            service_status=lambda _unit: (0, "active"),
            central_health=lambda _url: (_ for _ in ()).throw(AssertionError("unbound doctor must not probe central")),
            application_root=tmp_path,
        )
        assert report["summary"]["FAIL"] == 0
        assert report["central_state"] == "disconnected"
        assert {check["name"]: check["status"] for check in report["checks"]}["central_binding"] == "WARN"
        assert store.identity() == original_identity


def test_doctor_warns_for_orphaned_sync_and_unprovisioned_physical_hardware(tmp_path: Path) -> None:
    with EdgeStore(tmp_path) as store:
        store.bind(webui_controller_id="central", server_url="https://central", credential="secret")
        store.set_connection_state("orphaned")
        store.register_instruments([{
            "id": "physical-1", "instrument_type": "min-evolver", "vial_positions": [], "capabilities": {},
            "source": "physical", "identity_state": "unprovisioned", "connection_state": "disconnected",
        }])
        report = doctor_report(store, service_status=lambda _unit: (3, "inactive"),
                               central_health=lambda _url: (False, "central unavailable"), application_root=tmp_path)
    statuses = {check["name"]: check["status"] for check in report["checks"]}
    assert statuses["recovery_state"] == statuses["central_sync"] == "WARN"
    assert statuses["physical_identity"] == statuses["physical_connection"] == "WARN"
    assert "secret" not in str(report)


def test_cli_doctor_returns_nonzero_only_for_durable_recovery_failure(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr("meta_webui_application_backend.evolver_edge.cli.doctor_report", lambda _store: {
        "summary": {"PASS": 1, "WARN": 0, "FAIL": 1}, "checks": []
    })
    assert main(["--state-root", str(tmp_path), "doctor"]) == 2
    assert '"FAIL": 1' in capsys.readouterr().out
