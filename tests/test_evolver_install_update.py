from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
import pytest
from http.client import HTTPConnection
from threading import Thread
from urllib.parse import urlsplit

from meta_webui_application_backend.evolver_edge import EdgeStore, UpdateManager, UpdatePolicy, canonical_digest
from meta_webui_application_backend.evolver_edge.install import (hardware_systemd_unit, inspect_installation,
    installer_script, ownership_inventory, repair_installation, systemd_unit, uninstall_installation,
    uninstaller_script, persistent_systemd_root)
from meta_webui_application_backend.evolver_edge.update import NativePackageBackend, NixUpdateBackend, OCIUpdateBackend
from meta_webui_application_backend.evolver_edge.lifecycle import plan_lifecycle

ROOT = Path(__file__).resolve().parents[1]


def test_installer_release_falls_back_without_controller_selection(monkeypatch, tmp_path):
    from meta_webui_application_backend import app as app_module
    from meta_webui_application_backend import evolver_controller

    fallback = {"release": "fallback", "manifest": {}, "manifest_sha256": "digest"}
    monkeypatch.setattr(app_module, "ROOT", tmp_path)
    monkeypatch.setenv(evolver_controller.STATE_ROOT_ENV, str(tmp_path))
    monkeypatch.setattr(app_module.evolver_release, "selected_release_readiness", lambda root: fallback)

    assert app_module.installer_release() == fallback


def test_installer_release_uses_selected_controller_release(monkeypatch, tmp_path):
    from meta_webui_application_backend import evolver_controller

    selected = {"release_id": "selected", "manifest_digest": "a" * 64}
    monkeypatch.setenv(evolver_controller.STATE_ROOT_ENV, str(tmp_path))
    evolver_controller._write(evolver_controller.state_path(tmp_path), {"controller_release_selection": selected})

    assert evolver_controller.controller_release_selection() == selected


def test_release_readiness_accepts_immutable_manifest_and_source_binding(tmp_path, monkeypatch):
    from meta_webui_application_backend import evolver_release

    _publish_ready_release(tmp_path, monkeypatch)
    manifest_path = tmp_path / "published" / "2026.08.31" / "manifest.json"
    manifest_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    result = evolver_release.release_readiness(
        tmp_path, "2026.08.31", expected_manifest_digest=manifest_digest,
        expected_source_revision="a" * 40,
    )
    assert result["release"] == "2026.08.31"
    assert result["manifest_sha256"] == manifest_digest

    with pytest.raises(evolver_release.ReleaseError, match="manifest digest"):
        evolver_release.release_readiness(tmp_path, "2026.08.31", expected_manifest_digest="0" * 64)
    with pytest.raises(evolver_release.ReleaseError, match="source revision"):
        evolver_release.release_readiness(tmp_path, "2026.08.31", expected_source_revision="b" * 40)


def test_release_readiness_rejects_payload_digest_and_size_mismatches(tmp_path, monkeypatch):
    from meta_webui_application_backend import evolver_release

    _publish_ready_release(tmp_path, monkeypatch)
    release_dir = tmp_path / "published" / "2026.08.31"
    manifest = json.loads((release_dir / "manifest.json").read_text(encoding="utf-8"))
    native_path = release_dir / Path(manifest["artifacts"]["linux-x86_64"]["url"]).name

    original = native_path.read_bytes()
    native_path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    with pytest.raises(evolver_release.ReleaseError, match="checksum failed"):
        evolver_release.release_readiness(tmp_path, "2026.08.31")

    native_path.write_bytes(b"x86 native wheelhouse+")
    with pytest.raises(evolver_release.ReleaseError, match="size does not match"):
        evolver_release.release_readiness(tmp_path, "2026.08.31")


def test_lifecycle_planner_is_side_effect_free_and_keeps_software_binding_orthogonal():
    binding = {"server_url": "http://old:18086", "webui_controller_id": "central-a", "generation": 1}
    plan = plan_lifecycle(operation="handoff", current_installation=True, current_release="r1",
                          target_release="r2", current_binding=binding, target_server="http://new:18086",
                          connectivity="orphaned")
    assert plan.software_actions == ()
    assert plan.binding_actions == ("release old generation", "enroll new server")
    assert plan.requires_confirmation
    assert not plan.blocked_reasons


def test_lifecycle_planner_blocks_forced_adoption_with_active_runs_and_clean_reinstall_preserves_state():
    binding = {"server_url": "http://old:18086", "generation": 3}
    blocked = plan_lifecycle(operation="forced-adoption", current_installation=True,
                             current_binding=binding, target_server="http://new:18086",
                             active_runs=[{"id": "run-1", "state": "running"}], confirmed=True)
    assert any("active" in reason for reason in blocked.blocked_reasons)
    clean = plan_lifecycle(operation="clean-reinstall", current_installation=True,
                            current_release="r1", target_release="r2", current_binding=binding)
    assert clean.state_actions == ("keep durable state",)
    assert "preserved" in clean.warnings[0]


def test_lifecycle_planner_distinguishes_runtime_from_preserved_state():
    binding = {"server_url": "http://old:18086", "generation": 1}
    preserved = plan_lifecycle(operation="clean-reinstall", current_installation=False,
                               durable_state_present=True, current_binding=binding,
                               target_release="r2")
    assert not preserved.blocked_reasons
    assert plan_lifecycle(operation="repair", current_installation=False,
                          durable_state_present=True, current_binding=binding).blocked_reasons
    fresh = plan_lifecycle(operation="install", current_installation=False)
    assert not fresh.blocked_reasons


def _publish_ready_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str = "2026.08.31") -> None:
    x86, arm, firmware = (tmp_path / name for name in ("x86.tar.gz", "arm.tar.gz", "firmware.bin"))
    x86.write_bytes(b"x86 native wheelhouse")
    arm.write_bytes(b"arm native wheelhouse")
    firmware.write_bytes(b"SAMD21 image")
    release_root = tmp_path / "published"
    subprocess.run([sys.executable, "tools/build_evolver_release.py", "--output", str(release_root),
                    "--version", version, "--git-revision", "a" * 40,
                    "--x86_64", str(x86), "--aarch64", str(arm), "--firmware", str(firmware)], check=True)
    monkeypatch.setenv("META_WEBUI_EVOLVER_RELEASE_ROOT", str(release_root))
    monkeypatch.setenv("META_WEBUI_EVOLVER_RELEASE", version)


def _bundle() -> dict[str, object]:
    bundle: dict[str, object] = {"id": "bundle", "name": "bundle", "purpose": "test_fixture", "schema_version": "1", "execution_mode": "declarative_state_machine",
                                 "source": {}, "resolved_definition": {}, "execution_plan": {}, "runtime_parameters": [], "source_metadata": []}
    bundle["digest"] = canonical_digest(bundle)
    return bundle


class RecordingBackend:
    name = "recording"

    def __init__(self) -> None: self.installed: list[str] = []
    def install(self, release: str) -> None: self.installed.append(release)


def test_when_idle_update_defers_without_replacing_runtime_under_active_run(tmp_path):
    backend = RecordingBackend()
    with EdgeStore(tmp_path) as store:
        store.put_bundle(_bundle())
        store.create_run(run_id="active", bundle_id="bundle", instrument_ids=["i"], state="running")
        decision = UpdateManager(store, backend).request("2026.08.19")
        assert decision.action == "deferred"
        assert backend.installed == []
        assert UpdateManager(store, backend).request("2026.08.19", explicit=True).action == "installed"
        assert store.meta("controller_software_release") == "2026.08.19"


def test_manual_policy_requires_local_explicit_action(tmp_path):
    backend = RecordingBackend()
    with EdgeStore(tmp_path) as store:
        manager = UpdateManager(store, backend, policy=UpdatePolicy.MANUAL)
        assert manager.request("release").reason == "manual policy"
        assert manager.request("release", explicit=True).action == "installed"


def test_update_plan_is_side_effect_free_and_rejects_non_release_identifiers(tmp_path):
    backend = RecordingBackend()
    with EdgeStore(tmp_path) as store:
        manager = UpdateManager(store, backend)
        assert manager.plan("2026.08.19").action == "ready"
        assert backend.installed == []
        with pytest.raises(Exception, match="pinned release"):
            manager.plan("v1?ref=main")


def test_backends_use_fixed_argument_vectors():
    commands: list[list[str]] = []
    runner = lambda command: commands.append(list(command))
    NixUpdateBackend(flake="github:pbert5/meta_webui_demo", runner=runner).install("v1")
    NativePackageBackend(manager="dnf", runner=runner).install("v2")
    assert commands == [["nix", "profile", "install", "github:pbert5/meta_webui_demo?ref=v1"],
                        ["dnf", "install", "--assumeyes", "evolver-controller-v2"]]


def test_oci_backend_is_explicitly_unsupported_until_it_can_replace_and_rollback_services():
    with pytest.raises(Exception, match="planned/unsupported"):
        OCIUpdateBackend(image="example/evolver").install("v3")


def test_detect_backend_does_not_advertise_an_oci_installation_path(monkeypatch):
    from meta_webui_application_backend.evolver_edge.install import detect_backend

    monkeypatch.setattr("meta_webui_application_backend.evolver_edge.install.shutil.which",
                        lambda name: "/usr/bin/podman" if name == "podman" else None)
    assert detect_backend() == "native"


def test_cli_update_backend_has_no_public_source_fallback(monkeypatch):
    from meta_webui_application_backend.evolver_edge import cli

    monkeypatch.setattr(cli, "detect_backend", lambda: "nix")
    monkeypatch.delenv("EVOLVER_DEVELOPER_MODE", raising=False)
    monkeypatch.delenv("EVOLVER_NIX_FLAKE", raising=False)
    assert cli._update_backend().name == "native"


def test_install_inspection_and_systemd_unit_do_not_require_or_destroy_state(tmp_path):
    absent = inspect_installation(tmp_path, native_root=tmp_path / "native")
    assert absent.controller is None
    with EdgeStore(tmp_path) as store:
        controller_id = store.identity()["id"]
        store._connection.execute("INSERT INTO binding(singleton, controller_id, webui_controller_id, generation, server_url, credential, status, bound_at) VALUES (1, ?, ?, 1, ?, NULL, 'active', 'now')", (controller_id, "central-a", "http://old:18086"))
        store._connection.commit()
    present = inspect_installation(tmp_path, native_root=tmp_path / "native")
    assert present.controller and present.controller["id"] == controller_id
    assert present.runtime_installed is False
    assert present.durable_state_present is True
    assert present.identity_present is True
    assert present.binding_present is True
    unit = systemd_unit()
    assert "Restart=on-failure" in unit
    assert "StateDirectory=evolver-controller" in unit
    assert "UMask=0077" in unit
    assert "--state-root /var/lib/evolver-controller" in unit
    assert "After=network-online.target evolver-hardware.service" in unit
    assert "Wants=network-online.target evolver-hardware.service" in unit
    hardware = hardware_systemd_unit(state_root="/srv/evolver-state")
    assert "Before=evolver-controller.service" in hardware
    assert "--state-root /srv/evolver-state" in hardware


def test_evolver_vm_waits_for_edge_network_before_controller_use():
    flake = (ROOT / "flake.nix").read_text(encoding="utf-8")
    network_wait = flake.index('edge.wait_until_succeeds("getent hosts central")')
    controller_wait = flake.index('edge.wait_for_unit("evolver-controller.service")', network_wait)
    health_wait = flake.index('edge.wait_until_succeeds("curl -4 -fsS http://192.168.1.1:18086/healthz")', controller_wait)
    enrollment = flake.index('edge.succeed("evolverctl --state-root /var/lib/evolver-controller enroll', controller_wait)
    assert network_wait < controller_wait < health_wait < enrollment
    assert 'environment.systemPackages = [ pkgs.curl pkgs.jq ];' in flake


def test_installer_script_is_origin_bound_and_has_no_silent_reset():
    script = installer_script(default_server_url="https://webui.example/")
    assert 'SERVER_URL="https://webui.example"' in script
    assert "--server" in script
    assert "factory-reset" in script
    assert "intentionally not performed" in script
    assert "echo \"$TOKEN\"" not in script
    assert "--mode live_handoff" in script
    assert "--mode forced_adoption --confirm-forced-adoption" in script
    assert "recover requires --confirm-forced-adoption" in script
    assert "nix profile install" not in script
    assert "github.com/pbert5/evolver_code" not in script
    assert "github.com/pbert5/evolver-arduino" not in script
    assert "git -C" not in script
    assert "github.com" not in script
    assert "EVOLVER_DEVELOPER_MODE=true" in script
    assert "EVOLVER_NIX_INSTALL_REF" in script
    assert "RELEASE_MANIFEST_URL" in script
    assert "releases/evolver-controller.json" in script
    assert "sha256sum --check --status" in script
    assert "--no-index --find-links \"$STAGE/wheels\"" not in script
    assert 'cp -a "$STAGE/python" "$STAGE/site-packages" "$STAGE/bin"' in script
    assert '"$RELEASE_STAGE/bin/pip"' not in script
    assert '"$PYTHON3" -m venv' not in script
    assert "release manifest is incompatible with this installer lifecycle protocol" in script
    assert "release manifest lacks valid native and firmware artifacts" not in script
    assert '"$PYTHON3" - "$STAGE/manifest.json"' in script
    assert "jq -e --arg target" not in script
    assert 'command -v jq' not in script
    assert '"$PYTHON3" - "$STAGE/install-status.json"' in script
    assert "firmware artifact digest mismatch" in script
    assert "rm -rf \"$NATIVE_ROOT" not in script
    assert "systemctl enable --now evolver-hardware.service evolver-controller.service" in script
    assert "/etc/systemd/system.control" in script
    assert "no writable persistent systemd unit directory" in script
    assert "systemctl enable --runtime --now" in script
    assert "SYSTEMD_UNIT_DIR=/run/systemd/system" not in script
    assert '"$STAGE/python/bin/python"' in script
    assert "systemctl enable --runtime --now evolver-hardware.service evolver-controller.service" in script
    assert "evolverctl must be installed" not in script
    assert '"$CURRENT_CTL" --state-root "$STATE_ROOT" lifecycle-plan' not in script
    assert 'lifecycle-plan --current-state "$CURRENT_STATE_FILE"' in script
    assert 'TARGET_CTL="$RELEASE_ROOT/bin/evolverctl"' in script
    assert 'mv -Tf "$NATIVE_ROOT/.current.new" "$NATIVE_ROOT/current"' in script
    assert 'Accept this lifecycle plan?' in script
    assert "command -v jq" not in script
    assert script.index('curl --fail --silent --show-error --location "$ARTIFACT_URL"') < script.index('PYTHON3=')


def test_installer_uses_old_cli_only_for_legacy_inspection_and_target_for_planning():
    script = installer_script(default_server_url="http://100.110.27.100:18086", release="2026.08.31")
    assert '"$CURRENT_CTL" --state-root "$STATE_ROOT" install-status' in script
    assert script.index('curl --fail --silent --show-error --location "$ARTIFACT_URL"') < script.index('"$CURRENT_CTL" --state-root "$STATE_ROOT" install-status')
    assert '"$CURRENT_CTL" --state-root "$STATE_ROOT" lifecycle-plan' not in script
    assert '--current-state "$CURRENT_STATE_FILE"' in script
    assert "install|update|clean-reinstall|handoff|recover) install_software ;;" in script
    assert "esac\ncheck_existing_plan" in script


def test_installer_detects_preserved_state_without_old_runtime_and_preflights_target():
    script = installer_script(default_server_url="http://100.110.27.100:18086", release="2026.08.31")
    assert '[ -f "$STATE_ROOT/edge.sqlite3" ] && DURABLE_STATE_PRESENT=true' in script
    assert "Existing controller state detected; controller software is not currently installed." in script
    assert "[3] Repair current installation" in script
    assert 'if [ -n "$CURRENT_CTL" ]; then' in script
    assert 'lifecycle-plan --current-state "$CURRENT_STATE_FILE" --operation install' in script
    assert "release manifest is incompatible with this installer lifecycle protocol" in script
    assert 'required_cli_capabilities' in script


def test_target_planner_accepts_snapshot_from_legacy_runtime(tmp_path, capsys):
    from meta_webui_application_backend.evolver_edge.cli import main

    snapshot = tmp_path / "legacy-installation.json"
    snapshot.write_text(json.dumps({
        "controller": {"id": "edge-legacy", "connection_state": "orphaned"},
        "binding": {"server_url": "http://old:18086", "generation": 4},
        "active_runs": [], "installed_release": "release-n",
    }), encoding="utf-8")
    assert main(["--state-root", str(tmp_path / "unused"), "lifecycle-plan",
                 "--current-state", str(snapshot), "--operation", "clean-reinstall",
                 "--release", "release-n-plus-one"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["current_release"] == "release-n"
    assert output["state_actions"] == ["keep durable state"]
    assert output["blocked_reasons"] == []


def test_native_installer_switches_releases_atomically_and_rolls_back_failed_health():
    script = installer_script(default_server_url="https://webui.example/", release="2026.08.19")
    assert 'RELEASE_ID="2026.08.19"' in script
    assert 'RELEASE_ROOT="$NATIVE_ROOT/releases/$RELEASE_ID"' in script
    assert 'mv -Tf "$NATIVE_ROOT/.current.new" "$NATIVE_ROOT/current"' in script
    assert 'mv -Tf "$NATIVE_ROOT/.previous.new" "$NATIVE_ROOT/previous"' in script
    assert "--indirect" not in script
    published_release = script.index('mv -T "$RELEASE_STAGE" "$RELEASE_ROOT"')
    gc_root = script.index('nix-store --add-root "$RELEASE_ROOT/firmware-toolchain/nix-roots/bossac" --realise "$BOSSA_ROOT"')
    assert 'BOSSAC_WRAPPER="$RELEASE_STAGE/firmware-toolchain/arduino-data/packages/arduino/tools/bossac/1.7.0-arduino3/bossac"' in script
    current_switch = script.index('mv -Tf "$NATIVE_ROOT/.current.new" "$NATIVE_ROOT/current"')
    assert published_release < gc_root < current_switch
    assert 'CONTROLLER="$NATIVE_ROOT/current/bin/evolver-controller"' in script
    assert "systemctl restart evolver-hardware.service evolver-controller.service" in script
    assert "new native release failed service health; rolling back to previous release" in script
    assert 'mv -Tf "$NATIVE_ROOT/.current.rollback" "$NATIVE_ROOT/current"' in script


def test_native_installer_preflight_is_transactional_and_runtime_paths_are_final():
    script = installer_script(default_server_url="https://webui.example/", release="release-c")
    preflight = script.index('lifecycle-plan --current-state "$CURRENT_STATE_FILE" --operation install')
    publish = script.index('mv -T "$RELEASE_STAGE" "$RELEASE_ROOT"')
    closure_import = script.index('nix-store --import < "$RELEASE_STAGE/firmware-toolchain/nix-closures/bossac.closure"')
    gc_root = script.index('nix-store --add-root "$RELEASE_ROOT/firmware-toolchain/nix-roots/bossac" --realise "$BOSSA_ROOT"')
    native_marker = script.index('install -m 0644 /dev/null "$NATIVE_ROOT/.evolver-owned"')
    assert preflight < native_marker < closure_import < publish < gc_root
    assert 'RELEASE_STAGE="$STAGE/release.new"' in script
    assert 'data: $RELEASE_ROOT/firmware-toolchain/arduino-data' in script
    assert 'user: $RELEASE_ROOT/firmware-toolchain/arduino-libraries' in script
    assert 'downloads: $RELEASE_ROOT/firmware-toolchain/arduino-data/staging' in script
    assert 'sed -i "s|$RELEASE_STAGE|$RELEASE_ROOT|g"' not in script
    assert 'if ! nix-store --add-root' in script
    assert 'rm -rf "$RELEASE_ROOT"' in script


def test_native_installer_cleans_only_uncommitted_published_candidate():
    script = installer_script(default_server_url="https://webui.example/", release="release-cleanup")

    publication = script.index('mv -T "$RELEASE_STAGE" "$RELEASE_ROOT"')
    published_flag = script.index('RELEASE_PUBLISHED=true', publication)
    enrollment = script.index('enroll --server "$SERVER_URL"')
    committed_flag = script.index('INSTALL_COMMITTED=true')
    cleanup = script.index('cleanup_install()')

    assert 'RELEASE_PUBLISHED=false' in script
    assert 'INSTALL_COMMITTED=false' in script
    assert published_flag < enrollment < committed_flag
    assert 'if [ -L "$NATIVE_ROOT/current" ]' in script
    assert 'mv -Tf "$NATIVE_ROOT/.current.cleanup" "$NATIVE_ROOT/current"' in script
    assert 'rm -f "$NATIVE_ROOT/current"' in script
    assert 'rm -rf "$RELEASE_ROOT"' in script[cleanup:]
    # Cleanup can remove the candidate only after it is no longer current;
    # immutable release IDs are still rejected before publication.
    assert script.index('release ID already exists and is immutable') < publication
    assert script.index('!= "$RELEASE_ROOT"', cleanup) < script.index('rm -rf "$RELEASE_ROOT"', cleanup)


def test_release_owned_firmware_toolchain_is_used_by_active_services_and_rollback():
    unit = systemd_unit(executable="/opt/evolver-controller/current/bin/evolver-controller",
                        firmware_toolchain_root="/opt/evolver-controller/current/firmware-toolchain")
    assert "PATH=/opt/evolver-controller/current/firmware-toolchain/bin" in unit
    assert "ARDUINO_DIRECTORIES_DATA=/opt/evolver-controller/current/firmware-toolchain/arduino-data" in unit
    assert "ARDUINO_DIRECTORIES_USER=/opt/evolver-controller/current/firmware-toolchain/arduino-libraries" in unit
    assert "ARDUINO_CONFIG_FILE=/opt/evolver-controller/current/firmware-toolchain/arduino-cli.yaml" in unit
    assert "EVOLVER_FIRMWARE_ARTIFACT=/opt/evolver-controller/current/firmware/firmware.bin" in unit

    script = installer_script(default_server_url="https://webui.example/", release="release-b")
    # Every release gets its own toolchain and firmware before current moves;
    # the failed-health path restores the complete A release wiring.
    assert 'RELEASE_STAGE/firmware-toolchain' in script
    assert 'RELEASE_STAGE/firmware/firmware.bin' in script
    assert 'release ID already exists and is immutable' in script
    assert 'sed -i "1s|$RELEASE_STAGE|$RELEASE_ROOT|"' in script
    assert 'tarfile' in script
    assert 'if [ "$MODE" = update ] || [ "$MODE" = clean-reinstall ] || [ "$MODE" = install ]; then' in script
    assert 'TOOLCHAIN_ROOT="$NATIVE_ROOT/current/firmware-toolchain"' in script
    assert 'ln -sfn "$EVOLVERCTL" /usr/local/bin/evolverctl' in script
    assert 'systemctl restart evolver-hardware.service evolver-controller.service' in script
    assert 'native artifact firmware toolchain provenance does not match manifest' in script
    assert 'native artifact firmware toolchain CLI digest mismatch' in script


def test_uninstall_inventory_and_bootstrap_are_explicitly_server_bound():
    inventory = ownership_inventory()
    assert "evolver-controller.service" in inventory["systemd_units"][1]
    assert inventory["durable_state"] == "/var/lib/evolver-controller"
    assert uninstaller_script(default_server_url="https://webui.example/").startswith("#!/bin/sh")
    assert "github.com" not in uninstaller_script(default_server_url="https://webui.example/")
    assert "evolverctl uninstall" in uninstaller_script(default_server_url="https://webui.example/")
    assert "/opt/evolver-controller/current/bin/evolverctl" in uninstaller_script(default_server_url="https://webui.example/")
    script = installer_script(default_server_url="https://webui.example/")
    assert "ln -sfn \"$EVOLVERCTL\" /usr/local/bin/evolverctl" in script


def test_uninstall_preserves_state_and_refuses_active_run(tmp_path):
    state = tmp_path / "var" / "lib" / "evolver-controller"
    native = tmp_path / "opt" / "evolver-controller"
    systemd = tmp_path / "etc" / "systemd"
    cache = tmp_path / "var" / "cache" / "evolver-controller"
    bin_root = tmp_path / "usr" / "local" / "bin"
    with EdgeStore(state) as store:
        store.put_bundle(_bundle())
        store.create_run(run_id="active", bundle_id="bundle", instrument_ids=["i"], state="running")
        identity = store.identity()
    releases = native / "releases" / "2026.08.24"
    releases.mkdir(parents=True)
    (native / ".evolver-owned").write_text("installer\n")
    (native / "current").symlink_to(releases)
    (native / "previous").symlink_to(releases)
    cache.mkdir(parents=True)
    (cache / ".evolver-owned").write_text("installer\n")
    calls = []
    def runner(command, **kwargs): calls.append(command)
    with pytest.raises(RuntimeError, match="active/non-terminal"):
        uninstall_installation(state, native_root=native, bin_root=bin_root, systemd_root=systemd,
                               cache_root=cache, runner=runner)
    result = uninstall_installation(state, native_root=native, bin_root=bin_root, systemd_root=systemd,
                                    cache_root=cache, runner=runner, force_active=True)
    assert result["action"] == "uninstalled"
    assert state.joinpath("edge.sqlite3").exists()
    with EdgeStore(state) as store:
        assert store.identity()["id"] == identity["id"]
        assert store.run("active")["state"] == "running"
    assert not (native / "releases").exists()
    assert calls[-1] == ["systemctl", "daemon-reload"]


def test_repair_recreates_only_owned_services_from_current_release(tmp_path):
    state = tmp_path / "state"
    native = tmp_path / "opt" / "evolver-controller"
    current = native / "releases" / "r1"
    (current / "bin").mkdir(parents=True)
    for name in ("evolverctl", "evolver-controller", "evolver-hardware"):
        path = current / "bin" / name; path.write_text("#!/bin/sh\n"); path.chmod(0o755)
    (native / "current").symlink_to(current)
    systemd = tmp_path / "etc" / "systemd"
    bin_root = tmp_path / "usr" / "local" / "bin"
    calls = []
    result = repair_installation(state, native_root=native, bin_root=bin_root, systemd_root=systemd,
                                 runner=lambda command, **kwargs: calls.append(command))
    assert result["action"] == "repaired"
    assert result["systemd_lifecycle"] == "temporary_or_external"
    assert (systemd / "evolver-controller.service").exists()
    assert "controller identity" not in (systemd / "evolver-controller.service").read_text().lower()
    assert (bin_root / "evolverctl").is_symlink()
    assert calls == [["systemctl", "daemon-reload"], ["systemctl", "enable", "--now", "evolver-hardware.service", "evolver-controller.service"]]


def test_temporary_systemd_roots_are_filesystem_only_without_a_runner(tmp_path, monkeypatch):
    """A test/developer root must never control the host systemd manager."""
    import meta_webui_application_backend.evolver_edge.install as install_module

    state = tmp_path / "state"
    native = tmp_path / "native"
    current = native / "releases" / "r1" / "bin"
    current.mkdir(parents=True)
    for name in ("evolverctl", "evolver-controller", "evolver-hardware"):
        path = current / name; path.write_text("#!/bin/sh\n"); path.chmod(0o755)
    (native / "current").symlink_to(current.parent)
    attempted: list[object] = []
    monkeypatch.setattr(install_module.subprocess, "run", lambda *args, **kwargs: attempted.append(args))
    result = repair_installation(state, native_root=native, bin_root=tmp_path / "bin", systemd_root=tmp_path / "units")
    assert result["systemd_lifecycle"] == "temporary_or_external"
    assert attempted == []
    assert (tmp_path / "units" / "evolver-controller.service").exists()


def test_fake_systemd_runner_receives_the_explicit_repair_sequence(tmp_path):
    state = tmp_path / "state"
    native = tmp_path / "native"
    current = native / "releases" / "r1" / "bin"
    current.mkdir(parents=True)
    for name in ("evolverctl", "evolver-controller", "evolver-hardware"):
        path = current / name; path.write_text("#!/bin/sh\n"); path.chmod(0o755)
    (native / "current").symlink_to(current.parent)
    calls: list[list[str]] = []
    repair_installation(state, native_root=native, bin_root=tmp_path / "bin", systemd_root=tmp_path / "units",
                        runner=lambda command, **_kwargs: calls.append(command))
    assert calls == [["systemctl", "daemon-reload"],
                     ["systemctl", "enable", "--now", "evolver-hardware.service", "evolver-controller.service"]]


def test_nixos_control_units_are_persistent_and_boot_wired(tmp_path):
    state = tmp_path / "state"
    native = tmp_path / "opt" / "evolver-controller"
    current = native / "releases" / "r1"
    (current / "bin").mkdir(parents=True)
    for name in ("evolverctl", "evolver-controller", "evolver-hardware"):
        path = current / "bin" / name; path.write_text("#!/bin/sh\n"); path.chmod(0o755)
    (native / "current").symlink_to(current)
    systemd = tmp_path / "etc" / "systemd" / "system.control"
    result = repair_installation(state, native_root=native, bin_root=tmp_path / "bin", systemd_root=systemd,
                                 runner=lambda *_args, **_kwargs: None)
    assert result["action"] == "repaired"
    assert result["systemd_lifecycle"] == "temporary_or_external"
    assert "/run" not in str(systemd)
    assert "[Install]" not in (systemd / "evolver-controller.service").read_text()
    assert (systemd / "multi-user.target.d" / "evolver-controller.conf").exists()
    assert (systemd / "multi-user.target.d" / "evolver-hardware.conf").exists()


def test_persistent_systemd_root_rejects_runtime_override(monkeypatch):
    monkeypatch.setenv("EVOLVER_SYSTEMD_UNIT_DIR", "/run/systemd/system")
    with pytest.raises(RuntimeError, match="persistent"):
        persistent_systemd_root()


def test_operator_cli_defaults_to_production_state_root(monkeypatch):
    from meta_webui_application_backend.evolver_edge.cli import _root
    monkeypatch.delenv("EVOLVER_STATE_ROOT", raising=False)
    assert _root(None) == Path("/var/lib/evolver-controller")


def test_purge_requires_confirmation_and_preserves_firmware(tmp_path):
    state = tmp_path / "state"
    with EdgeStore(state) as store:
        store.put_bundle(_bundle())
    (state / "firmware").mkdir()
    (state / "firmware" / "samd21.bin").write_bytes(b"firmware")
    with pytest.raises(ValueError, match="explicit confirmation"):
        uninstall_installation(state, purge=True, native_root=tmp_path / "native", cache_root=tmp_path / "cache",
                               systemd_root=tmp_path / "systemd", bin_root=tmp_path / "bin")
    result = uninstall_installation(state, purge=True, confirm=True, native_root=tmp_path / "native",
                                    cache_root=tmp_path / "cache", systemd_root=tmp_path / "systemd", bin_root=tmp_path / "bin")
    assert result["action"] == "purged"
    assert (state / "firmware" / "samd21.bin").read_bytes() == b"firmware"
    assert not (state / "edge.sqlite3").exists()


def test_install_route_returns_origin_and_base_path_aware_shell_script(monkeypatch):
    """The public installer route preserves the reverse-proxy mount prefix."""
    from meta_webui_application_backend import app as app_module

    monkeypatch.setattr(app_module, "BASE_PATH", "/meta-webui-interface")
    monkeypatch.delenv("META_WEBUI_EVOLVER_RELEASE", raising=False)
    monkeypatch.delenv("META_WEBUI_EVOLVER_RELEASE_ROOT", raising=False)
    server = app_module.ThreadingHTTPServer(("127.0.0.1", 0), app_module.MetaWebUIHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_address[1])
        connection.request("GET", "/meta-webui-interface/install/evolver", headers={
            "Host": "server.example.org",
            "X-Forwarded-Proto": "https",
        })
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        assert response.status == 503
        assert __import__("json").loads(body)["kind"] == "ReleaseUnavailable"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_uninstall_route_is_server_hosted_and_does_not_require_repository(monkeypatch):
    from meta_webui_application_backend import app as app_module
    monkeypatch.setattr(app_module, "BASE_PATH", "/meta-webui-interface")
    server = app_module.ThreadingHTTPServer(("127.0.0.1", 0), app_module.MetaWebUIHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_address[1])
        connection.request("GET", "/meta-webui-interface/install/evolver/uninstall", headers={
            "Host": "server.example.org", "X-Forwarded-Proto": "https"})
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        assert response.status == 200
        assert response.getheader("Content-Type") == "text/x-shellscript; charset=utf-8"
        assert "evolverctl uninstall" in body
        assert "github.com" not in body
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_install_route_rejects_a_host_header_with_a_path(monkeypatch):
    from meta_webui_application_backend import app as app_module

    monkeypatch.setattr(app_module, "BASE_PATH", "")
    server = app_module.ThreadingHTTPServer(("127.0.0.1", 0), app_module.MetaWebUIHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_address[1])
        connection.request("GET", "/install/evolver", headers={"Host": "server.example/attacker"})
        response = connection.getresponse()
        assert response.status == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(("base_path", "expected_path"), [("", "/"), ("/meta-webui-interface", "/meta-webui-interface")])
def test_development_session_cookie_is_http_only_and_scoped_to_the_mount(monkeypatch, base_path, expected_path):
    from meta_webui_application_backend import app as app_module

    monkeypatch.setattr(app_module, "BASE_PATH", base_path)
    cookie = app_module.MetaWebUIHandler._session_cookie(object.__new__(app_module.MetaWebUIHandler), "opaque-session")
    assert cookie.startswith("meta_webui_session=opaque-session;")
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert f"Path={expected_path}" in cookie


def test_generated_versioned_release_is_served_only_after_manifest_and_artifact_validation(monkeypatch, tmp_path):
    """The installer consumes a real, immutable route rather than a repo clone."""
    from meta_webui_application_backend import app as app_module

    x86, arm, firmware = tmp_path / "x86.tar.gz", tmp_path / "arm.tar.gz", tmp_path / "firmware.bin"
    x86.write_bytes(b"x86 native wheelhouse")
    arm.write_bytes(b"arm native wheelhouse")
    firmware_bytes = bytes(range(256)) + b"\x00\xff\x80"
    firmware.write_bytes(firmware_bytes)
    release_root = tmp_path / "published"
    subprocess.run([sys.executable, "tools/build_evolver_release.py", "--output", str(release_root),
                    "--version", "2026.08.19", "--git-revision", "a" * 40,
                    "--x86_64", str(x86), "--aarch64", str(arm), "--firmware", str(firmware)], check=True)
    monkeypatch.setenv("META_WEBUI_EVOLVER_RELEASE_ROOT", str(release_root))
    monkeypatch.setenv("META_WEBUI_EVOLVER_RELEASE", "2026.08.19")
    manifest_path = release_root / "2026.08.19" / "manifest.json"
    manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")
    monkeypatch.setattr(app_module, "BASE_PATH", "")
    server = app_module.ThreadingHTTPServer(("127.0.0.1", 0), app_module.MetaWebUIHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_address[1])
        connection.request("GET", "/releases/evolver/2026.08.19/manifest.json")
        response = connection.getresponse()
        served_manifest = response.read()
        manifest = __import__("json").loads(served_manifest)
        assert response.status == 200
        assert served_manifest == manifest_path.read_bytes()
        assert hashlib.sha256(served_manifest).digest() == hashlib.sha256(manifest_path.read_bytes()).digest()
        assert len(served_manifest) == manifest_path.stat().st_size
        assert response.getheader("Content-Length") == str(manifest_path.stat().st_size)
        assert manifest["git_revision"] == "a" * 40
        assert manifest["install_type"] == "native-wheelhouse"
        assert manifest["required_controller_schema_version"] == "1"
        assert manifest["artifacts"]["linux-x86_64"]["size"] == x86.stat().st_size
        assert manifest["artifacts"]["linux-x86_64"]["url"].endswith("linux-x86_64-2026.08.19.tar.gz")
        connection.request("GET", manifest["artifacts"]["linux-x86_64"]["url"])
        response = connection.getresponse()
        artifact = response.read()
        assert response.status == 200
        assert artifact == x86.read_bytes()
        assert hashlib.sha256(artifact).hexdigest() == manifest["artifacts"]["linux-x86_64"]["sha256"]
        connection.request("GET", manifest["firmware"]["url"])
        response = connection.getresponse()
        served_firmware = response.read()
        assert response.status == 200
        assert served_firmware == firmware_bytes
        assert len(served_firmware) == firmware.stat().st_size
        connection.request("GET", "/releases/evolver/2026.08.19/../manifest.json")
        assert connection.getresponse().status == 404
        connection.request("GET", "/install/evolver", headers={"Host": "central.example", "X-Forwarded-Proto": "https"})
        script = connection.getresponse().read().decode()
        assert "/releases/evolver/2026.08.19/manifest.json" in script
        assert f'SOURCE_REVISION="{"a" * 40}"' in script
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_release_builder_records_verified_firmware_artifact(tmp_path):
    x86, arm, firmware = (tmp_path / name for name in ("x86.tar.gz", "arm.tar.gz", "firmware.bin"))
    x86.write_bytes(b"x86 native wheelhouse")
    arm.write_bytes(b"arm native wheelhouse")
    firmware.write_bytes(b"SAMD21 image")
    release_root = tmp_path / "published"
    subprocess.run([sys.executable, "tools/build_evolver_release.py", "--output", str(release_root),
                    "--version", "2026.08.24", "--git-revision", "b" * 40,
                    "--x86_64", str(x86), "--aarch64", str(arm), "--firmware", str(firmware),
                    "--firmware-version", "0.2"], check=True)
    manifest = __import__("json").loads((release_root / "2026.08.24" / "manifest.json").read_text())
    assert manifest["firmware"]["variant"] == "samd21-minievolver"
    assert manifest["firmware"]["url"].endswith("samd21-minievolver-0.2-2026.08.24.bin")
    assert manifest["firmware"]["sha256"] == hashlib.sha256(firmware.read_bytes()).hexdigest()


def test_versioned_firmware_route_serves_verified_binary(monkeypatch, tmp_path):
    from meta_webui_application_backend import app as app_module
    x86, firmware = tmp_path / "x86.tar.gz", tmp_path / "firmware.bin"
    x86.write_bytes(b"x86")
    firmware.write_bytes(b"SAMD21")
    release_root = tmp_path / "published"
    subprocess.run([sys.executable, "tools/build_evolver_release.py", "--output", str(release_root),
                    "--version", "firmware-route", "--git-revision", "f" * 40,
                    "--artifact", f"linux-x86_64={x86}", "--firmware", str(firmware)], check=True)
    monkeypatch.setenv("META_WEBUI_EVOLVER_RELEASE_ROOT", str(release_root))
    monkeypatch.setenv("META_WEBUI_EVOLVER_RELEASE", "firmware-route")
    monkeypatch.setattr(app_module, "BASE_PATH", "")
    server = app_module.ThreadingHTTPServer(("127.0.0.1", 0), app_module.MetaWebUIHandler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_address[1])
        connection.request("GET", "/releases/evolver/firmware-route/manifest.json")
        manifest = __import__("json").loads(connection.getresponse().read())
        connection.request("GET", manifest["firmware"]["url"])
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Length") == str(len(b"SAMD21"))
        assert response.read() == b"SAMD21"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_production_installer_and_release_manifest_have_no_old_checkout_dependency(tmp_path):
    firmware = tmp_path / "firmware.bin"
    firmware.write_bytes(b"SAMD21 image")
    x86, arm = tmp_path / "x86.tar.gz", tmp_path / "arm.tar.gz"
    x86.write_bytes(b"x86")
    arm.write_bytes(b"arm")
    subprocess.run([sys.executable, "tools/build_evolver_release.py", "--output", str(tmp_path / "published"),
                    "--version", "release", "--git-revision", "c" * 40, "--x86_64", str(x86),
                    "--aarch64", str(arm), "--firmware", str(firmware)], check=True)
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes((tmp_path / "published" / "release" / "manifest.json").read_bytes())
    installer = tmp_path / "installer.sh"
    installer.write_text(installer_script(default_server_url="https://edge.example", release="release"), encoding="utf-8")
    subprocess.run([sys.executable, "tools/check_evolver_release_self_contained.py", "--installer", str(installer),
                    "--manifest", str(manifest)], check=True)


def test_install_command_api_returns_one_time_copyable_command_for_authenticated_operator(monkeypatch, tmp_path):
    from meta_webui_application_backend import app as app_module
    from meta_webui_application_backend import evolver_controller
    from meta_webui_application_backend.evolver_control.service import EvolverControlHandler

    monkeypatch.setattr(app_module, "BASE_PATH", "/meta-webui-interface")
    _publish_ready_release(tmp_path, monkeypatch)
    monkeypatch.setenv(evolver_controller.STATE_ROOT_ENV, str(tmp_path))
    monkeypatch.setenv("META_WEBUI_EVOLVER_TRUSTED_OPERATOR_HEADER", "X-Verified-Operator")
    monkeypatch.setenv("META_WEBUI_EVOLVER_OPERATOR_ROLES", '{"operator": ["manage_controller"]}')
    monkeypatch.setenv("META_WEBUI_EVOLVER_CONTROL_SHARED_SECRET", "test-control-secret")
    monkeypatch.setenv("META_WEBUI_TRUSTED_PROXY_SECRET", "proxy-secret")
    control = app_module.ThreadingHTTPServer(("127.0.0.1", 0), EvolverControlHandler)
    control_thread = Thread(target=control.serve_forever, daemon=True)
    control_thread.start()
    monkeypatch.setenv("META_WEBUI_EVOLVER_CONTROL_URL", f"http://127.0.0.1:{control.server_address[1]}")
    server = app_module.ThreadingHTTPServer(("127.0.0.1", 0), app_module.MetaWebUIHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_address[1])
        connection.request("POST", "/meta-webui-interface/api/evolver/install-command", body="{}", headers={
                "Host": "server.example.org", "X-Forwarded-Proto": "https",
                "X-Verified-Operator": "operator", "X-Meta-Webui-Trusted-Proxy-Secret": "proxy-secret", "Content-Type": "application/json",
        })
        response = connection.getresponse()
        payload = __import__("json").loads(response.read())
        assert response.status == 201
        assert payload["single_use"] is True
        assert payload["server_url"] == "https://server.example.org/meta-webui-interface"
        assert payload["webui_controller"]["id"].startswith("webui-")
        assert "curl -fsSL https://server.example.org/meta-webui-interface/install/evolver" in payload["install_command"]
        command_url = shlex.split(payload["install_command"])[2]
        assert "binding=" in command_url
        assert "enrollment_token" not in payload
        state = evolver_controller._read(evolver_controller.state_path(tmp_path))
        record = next(iter(state["enrollment_tokens"].values()))
        assert "token" not in record
        assert record["used_at"] is None
        assert record["release_binding"] == {
            "release": "2026.08.31",
            "source_revision": "a" * 40,
            "manifest_sha256": payload["release_manifest_sha256"],
        }

        # The command's opaque binding remains release A even after central
        # changes its mutable default selector to release B.
        _publish_ready_release(tmp_path, monkeypatch, version="2026.09.01")
        bound = urlsplit(command_url)
        connection.request("GET", bound.path + "?" + bound.query, headers={
            "Host": "server.example.org", "X-Forwarded-Proto": "https",
        })
        bound_response = connection.getresponse()
        bound_script = bound_response.read().decode("utf-8")
        assert bound_response.status == 200
        assert 'RELEASE_ID="2026.08.31"' in bound_script
        assert 'SOURCE_REVISION="' + "a" * 40 + '"' in bound_script
        assert "/releases/evolver/2026.08.31/manifest.json" in bound_script
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        control.shutdown()
        control.server_close()
        control_thread.join(timeout=2)


def test_install_command_uses_selected_configured_controller_endpoint(monkeypatch, tmp_path):
    from meta_webui_application_backend import app as app_module
    from meta_webui_application_backend import evolver_controller
    from meta_webui_application_backend.evolver_control.service import EvolverControlHandler

    monkeypatch.setenv(evolver_controller.STATE_ROOT_ENV, str(tmp_path))
    _publish_ready_release(tmp_path, monkeypatch)
    monkeypatch.setenv("META_WEBUI_EVOLVER_TRUSTED_OPERATOR_HEADER", "X-Verified-Operator")
    monkeypatch.setenv("META_WEBUI_EVOLVER_OPERATOR_ROLES", '{"operator": ["manage_controller"]}')
    monkeypatch.setenv("META_WEBUI_EVOLVER_CONTROL_SHARED_SECRET", "test-control-secret")
    monkeypatch.setenv("META_WEBUI_TRUSTED_PROXY_SECRET", "proxy-secret")
    monkeypatch.setenv("META_WEBUI_EVOLVER_CONTROLLER_ENDPOINTS", '[{"id":"private","label":"Private","url":"https://controller.example","controller_reachable":true,"enabled":true,"priority":1}]')
    control = app_module.ThreadingHTTPServer(("127.0.0.1", 0), EvolverControlHandler)
    control_thread = Thread(target=control.serve_forever, daemon=True); control_thread.start()
    monkeypatch.setenv("META_WEBUI_EVOLVER_CONTROL_URL", f"http://127.0.0.1:{control.server_address[1]}")
    server = app_module.ThreadingHTTPServer(("127.0.0.1", 0), app_module.MetaWebUIHandler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_address[1])
        connection.request("POST", "/api/evolver/install-command", body='{"endpoint_id":"private"}', headers={"Host":"attacker.example", "X-Forwarded-Proto":"https", "X-Verified-Operator":"operator", "X-Meta-Webui-Trusted-Proxy-Secret":"proxy-secret", "Content-Type":"application/json"})
        response = connection.getresponse(); payload = __import__("json").loads(response.read())
        assert response.status == 201
        assert payload["server_url"] == "https://controller.example"
        assert "attacker.example" not in payload["install_command"]
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
        control.shutdown(); control.server_close(); control_thread.join(timeout=2)
