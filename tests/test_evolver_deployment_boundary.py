from __future__ import annotations

from pathlib import Path

import pytest

from meta_webui_application_backend.evolver_edge.cli import _update_backend
from meta_webui_application_backend.evolver_edge.install import detect_backend, installer_script
from meta_webui_application_backend.evolver_edge.store import EdgeStoreError
from meta_webui_application_backend.evolver_edge.update import ComposeUpdateBackend


ROOT = Path(__file__).parents[3]


def test_compose_is_the_only_runtime_backend(monkeypatch):
    monkeypatch.delenv("EVOLVER_COMPOSE_FILE", raising=False)
    assert detect_backend() == "compose"
    assert _update_backend().name == "compose"


def test_compose_update_requires_explicit_host_boundary():
    with pytest.raises(EdgeStoreError, match="host-owned"):
        ComposeUpdateBackend().install("release-a")


def test_compose_update_has_no_native_or_systemd_command():
    commands: list[list[str]] = []
    ComposeUpdateBackend(compose_file="deploy/evolver-edge/compose.yaml",
                         runner=lambda command: commands.append(list(command))).install("release-a")
    assert commands == [["docker", "compose", "-f", "deploy/evolver-edge/compose.yaml", "up", "-d", "--build"]]
    assert all(part not in {"systemctl", "nix", "apt-get", "dnf"} for command in commands for part in command)


def test_compose_stack_preserves_isolated_hardware_and_controller_boundaries():
    compose = (ROOT / "deploy" / "evolver-edge" / "compose.yaml").read_text(encoding="utf-8")
    assert "network_mode: none" in compose
    assert "target: /dev" in compose
    assert "target: /run/evolver-controller" in compose
    assert "EVOLVER_STATE_ROOT: /var/lib/evolver-controller" in compose
    assert "EVOLVER_STATE_ROOT: /var/lib/evolver-hardware" in compose
    assert "depends_on:" in compose


def test_installer_script_does_not_silently_select_a_native_backend():
    script = installer_script(default_server_url="https://edge.example")
    # The server-hosted legacy payload remains available for recovery, but it
    # must not use environment-controlled Nix/native selection.
    assert "EVOLVER_NIX_INSTALL_REF" not in script
    assert "EVOLVER_NATIVE_PACKAGE" not in script
