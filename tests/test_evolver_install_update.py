from __future__ import annotations

import pytest

from meta_webui_application_backend.evolver_edge import EdgeStore, UpdateManager, UpdatePolicy
from meta_webui_application_backend.evolver_edge.install import (
    hardware_systemd_unit,
    inspect_installation,
    installer_script,
    repair_installation,
    systemd_unit,
    uninstall_installation,
)
from meta_webui_application_backend.evolver_edge.lifecycle import plan_lifecycle
from meta_webui_application_backend.evolver_edge.update import (
    NativePackageBackend,
    NixUpdateBackend,
    OCIUpdateBackend,
)


def _bundle() -> dict[str, object]:
    return {
        "id": "bundle",
        "name": "bundle",
        "purpose": "test_fixture",
        "schema_version": "1",
        "execution_mode": "declarative_state_machine",
        "source": {},
        "resolved_definition": {},
        "execution_plan": {},
        "runtime_parameters": [],
        "source_metadata": [],
    }


class RecordingBackend:
    name = "recording"

    def __init__(self) -> None:
        self.installed: list[str] = []

    def install(self, release: str) -> None:
        self.installed.append(release)


def test_update_defers_under_active_run_and_explicit_update_records_only_after_install(tmp_path):
    backend = RecordingBackend()
    with EdgeStore(tmp_path) as store:
        store.put_bundle(_bundle())
        store.create_run(run_id="active", bundle_id="bundle", instrument_ids=["instrument"], state="running")
        manager = UpdateManager(store, backend)

        assert manager.request("2026.08.19").action == "deferred"
        assert backend.installed == []
        assert store.meta("controller_software_release") is None

        assert manager.request("2026.08.19", explicit=True).action == "installed"
        assert backend.installed == ["2026.08.19"]
        assert store.meta("controller_software_release") == "2026.08.19"


def test_manual_policy_and_release_validation_are_local_and_side_effect_free(tmp_path):
    backend = RecordingBackend()
    with EdgeStore(tmp_path) as store:
        manager = UpdateManager(store, backend, policy=UpdatePolicy.MANUAL)
        assert manager.request("release").reason == "manual policy"
        assert manager.plan("release").action == "deferred"
        assert backend.installed == []
        with pytest.raises(Exception, match="pinned release"):
            manager.plan("v1?ref=main")


def test_update_backends_use_fixed_commands_and_oci_cannot_fake_an_update():
    commands: list[list[str]] = []
    runner = lambda command: commands.append(list(command))
    NixUpdateBackend(flake="github:example/project", runner=runner).install("v1")
    NativePackageBackend(manager="dnf", runner=runner).install("v2")
    assert commands == [
        ["nix", "profile", "install", "github:example/project?ref=v1"],
        ["dnf", "install", "--assumeyes", "evolver-controller-v2"],
    ]
    with pytest.raises(Exception, match="planned/unsupported"):
        OCIUpdateBackend(image="example/evolver").install("v3")


def test_lifecycle_plan_keeps_reinstall_state_and_handoff_separate():
    binding = {"server_url": "http://old:18086", "webui_controller_id": "central", "generation": 3}
    clean = plan_lifecycle(
        operation="clean-reinstall",
        current_installation=True,
        current_release="r1",
        target_release="r2",
        current_binding=binding,
    )
    assert clean.state_actions == ("keep durable state",)
    assert "preserved" in clean.warnings[0]

    handoff = plan_lifecycle(
        operation="handoff",
        current_installation=True,
        current_release="r1",
        current_binding=binding,
        target_server="http://new:18086",
        connectivity="orphaned",
    )
    assert handoff.software_actions == ()
    assert handoff.binding_actions == ("release old generation", "enroll new server")
    assert handoff.requires_confirmation


def test_failed_forced_adoption_with_active_run_is_blocked():
    plan = plan_lifecycle(
        operation="forced-adoption",
        current_installation=True,
        current_binding={"generation": 3},
        target_server="http://new:18086",
        active_runs=[{"id": "run-1", "state": "running"}],
        confirmed=True,
    )
    assert any("active" in reason for reason in plan.blocked_reasons)


def test_install_inspection_and_units_preserve_state_and_are_conservative(tmp_path):
    native = tmp_path / "native"
    absent = inspect_installation(tmp_path, native_root=native)
    assert absent.controller is None

    with EdgeStore(tmp_path) as store:
        identity = store.identity()
        store.bind(webui_controller_id="central", server_url="http://old", credential="secret")

    present = inspect_installation(tmp_path, native_root=native)
    assert present.controller["id"] == identity["id"]
    assert present.durable_state_present
    assert present.identity_present and present.binding_present

    unit = systemd_unit()
    assert "Restart=on-failure" in unit
    assert "StateDirectory=evolver-controller" in unit
    assert "UMask=0077" in unit
    assert "After=network-online.target evolver-hardware.service" in unit
    assert "Before=evolver-controller.service" in hardware_systemd_unit()


def test_installer_script_contains_atomic_switch_and_failed_health_rollback():
    script = installer_script(default_server_url="https://webui.example/", release="release-b")
    assert 'RELEASE_ROOT="$NATIVE_ROOT/releases/$RELEASE_ID"' in script
    assert 'mv -Tf "$NATIVE_ROOT/.current.new" "$NATIVE_ROOT/current"' in script
    assert 'mv -Tf "$NATIVE_ROOT/.previous.new" "$NATIVE_ROOT/previous"' in script
    assert "new native release failed service health; rolling back to previous release" in script
    assert 'mv -Tf "$NATIVE_ROOT/.current.rollback" "$NATIVE_ROOT/current"' in script
    assert 'RELEASE_PUBLISHED=false' in script
    assert 'INSTALL_COMMITTED=false' in script


def test_uninstall_refuses_active_run_then_preserves_durable_identity(tmp_path):
    state = tmp_path / "state"
    native = tmp_path / "native"
    systemd = tmp_path / "systemd"
    cache = tmp_path / "cache"
    with EdgeStore(state) as store:
        store.put_bundle(_bundle())
        store.create_run(run_id="active", bundle_id="bundle", instrument_ids=["instrument"], state="running")
        identity = store.identity()

    releases = native / "releases" / "r1"
    releases.mkdir(parents=True)
    (native / ".evolver-owned").write_text("installer\n")
    (native / "current").symlink_to(releases)
    cache.mkdir()
    (cache / ".evolver-owned").write_text("installer\n")

    with pytest.raises(RuntimeError, match="active/non-terminal"):
        uninstall_installation(state, native_root=native, systemd_root=systemd, cache_root=cache)

    result = uninstall_installation(
        state,
        native_root=native,
        systemd_root=systemd,
        cache_root=cache,
        force_active=True,
    )
    assert result["action"] == "uninstalled"
    assert (state / "edge.sqlite3").exists()
    with EdgeStore(state) as store:
        assert store.identity()["id"] == identity["id"]
        assert store.run("active")["state"] == "running"
    assert not (native / "releases").exists()


def test_repair_uses_injected_roots_without_contacting_host_systemd(tmp_path, monkeypatch):
    state = tmp_path / "state"
    native = tmp_path / "native"
    current = native / "releases" / "r1" / "bin"
    current.mkdir(parents=True)
    for name in ("evolverctl", "evolver-controller", "evolver-hardware"):
        executable = current / name
        executable.write_text("#!/bin/sh\n")
        executable.chmod(0o755)
    (native / "current").symlink_to(current.parent)
    attempted: list[object] = []
    monkeypatch.setattr("meta_webui_application_backend.evolver_edge.install.subprocess.run", lambda *args, **kwargs: attempted.append(args))

    result = repair_installation(
        state,
        native_root=native,
        bin_root=tmp_path / "bin",
        systemd_root=tmp_path / "units",
    )
    assert result["systemd_lifecycle"] == "temporary_or_external"
    assert attempted == []
    assert (tmp_path / "units" / "evolver-controller.service").exists()
