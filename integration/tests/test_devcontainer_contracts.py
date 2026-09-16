import json
import shutil
import subprocess
from pathlib import Path

import pytest


pytestmark = pytest.mark.integration


ROOT = Path(__file__).parents[2]


def test_server_container_is_canonical_and_safe():
    config = json.loads((ROOT / ".devcontainer/server/devcontainer.json").read_text())
    assert config["name"] == "Meta Ball Server"
    assert config["build"]["target"] == "server"
    assert config["forwardPorts"] == [18086]
    assert config["containerEnv"]["META_BAL_DEV_BIND_ADDRESS"].endswith("127.0.0.1}")
    assert any("docker-outside-of-docker" in feature for feature in config["features"])
    mounts = "\n".join(config["mounts"])
    assert "uv-cache" in mounts and "npm-cache" not in mounts
    assert "workspaceFolder}/.venv" not in mounts


def test_server_container_bootstraps_shared_metactl_target_and_server_first_imports():
    config = json.loads((ROOT / ".devcontainer/server/devcontainer.json").read_text())
    assert config["containerEnv"]["META_WEBUI_METACTL_CENTRAL_URL"] == "http://127.0.0.1:18087"
    assert config["containerEnv"]["PYTHONPATH"].startswith(
        "/workspaces/meta_bal/evolver/evolver-server/src"
    )


def test_server_metactl_wrapper_is_source_backed_and_preserves_arguments():
    launcher = (ROOT / ".devcontainer/server/scripts/metactl").read_text()
    assert "evolver/evolver-server/src" in launcher
    assert "uv run --project /workspaces/meta_bal/metactl" in launcher
    assert 'metactl "$@"' in launcher
    assert "exec " in launcher


def test_server_bootstrap_manages_the_source_backed_control_service():
    bootstrap = (ROOT / ".devcontainer/server/scripts/bootstrap-devcontainer").read_text()
    assert "META_WEBUI_EVOLVER_CONTROL_HOST" in bootstrap
    assert 'META_WEBUI_EVOLVER_CONTROL_PORT:-18087' in bootstrap
    assert "evolver-control" in bootstrap
    assert "evolver/evolver-server" in bootstrap
    assert "PYTHONPATH" in bootstrap
    assert "/api/actions" in bootstrap


def test_host_metactl_launcher_is_executable():
    assert (ROOT / "tools/metactl").stat().st_mode & 0o111


def test_host_metactl_launcher_forwards_arguments_and_exit_status(tmp_path):
    fake_rtk = tmp_path / "rtk"
    fake_rtk.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$@\" > \"$LAUNCHER_ARGS\"\n"
        "exit \"${LAUNCHER_STATUS}\"\n"
    )
    fake_rtk.chmod(0o755)
    args_file = tmp_path / "args"
    launcher = ROOT / "tools/metactl"
    result = subprocess.run(
        [str(launcher), "doctor", "--format", "json"],
        cwd=ROOT,
        env={
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "LAUNCHER_ARGS": str(args_file),
            "LAUNCHER_STATUS": "23",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 23
    assert args_file.read_text().splitlines() == [
        "tools/dev-env", "server", "exec", "metactl", "doctor", "--format", "json"
    ]


def test_stale_webui_and_browser_tooling_are_absent():
    text = "\n".join(
        p.read_text() for p in [ROOT / ".devcontainer/Dockerfile", ROOT / ".devcontainer/server/devcontainer.json"]
    )
    assert "META_WEBUI_METACTL_CENTRAL_URL" in text
    for stale in ("meta-webui", "PLAYWRIGHT", "npm", "nodejs", "chromium"):
        assert stale.lower() not in text.lower()


def test_workspace_members_and_contract_scripts_exist():
    pyproject = (ROOT / "pyproject.toml").read_text()
    for member in ("evolver/evolver-controller", "evolver/evolver-hardware", "evolver/evolver-server"):
        assert member in pyproject
    assert "metactl/tests" not in pyproject
    for script in ("tools/dev-env", "tools/check-locks", "tools/test", "tools/test-fast", "tools/test-serial"):
        assert (ROOT / script).is_file()
        assert (ROOT / script).stat().st_mode & 0o111


@pytest.mark.parametrize("argv", [("server", "check"), ("check", "server")])
def test_dev_env_accepts_canonical_and_legacy_server_order(argv):
    result = subprocess.run([str(ROOT / "tools/dev-env"), *argv], cwd=ROOT,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "configuration valid:" in result.stdout


def test_environment_lock_checker_has_explicit_relock_mode():
    result = subprocess.run([str(ROOT / "tools/check-locks"), "--help"], cwd=ROOT,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "[--relock]" in result.stdout


def test_dev_env_smoke_covers_shared_and_edge_contracts():
    source = (ROOT / "tools/dev-env").read_text()
    for command in ("rtk", "uv", "python", "pytest", "navi", "codex", "docker", "evoctl", "metactl"):
        assert f"{command}" in source
    assert 'import yaml' in source
    assert 'test -d /run/evolver-controller' in source


def test_dev_env_check_validates_the_managed_metactl_target():
    source = (ROOT / "tools/dev-env").read_text()
    assert "META_WEBUI_METACTL_CENTRAL_URL" in source
    assert "http://127.0.0.1:18087" in source


@pytest.mark.parametrize("variable_name", [
    "META_WEBUI_METACTL_CENTRAL_URL_SUFFIX",
    "PREFIX_META_WEBUI_METACTL_CENTRAL_URL",
    "meta_webui_metactl_central_url",
])
def test_dev_env_check_rejects_meta_webui_names_that_are_not_exact(tmp_path, variable_name):
    checkout = tmp_path / "checkout"
    (checkout / "tools").mkdir(parents=True)
    (checkout / ".devcontainer/server").mkdir(parents=True)
    shutil.copy2(ROOT / "tools/dev-env", checkout / "tools/dev-env")
    shutil.copy2(ROOT / ".devcontainer/server/devcontainer.json",
                 checkout / ".devcontainer/server/devcontainer.json")
    shutil.copy2(ROOT / ".devcontainer/Dockerfile", checkout / ".devcontainer/Dockerfile")
    if (ROOT / ".vscode").exists():
        shutil.copytree(ROOT / ".vscode", checkout / ".vscode")

    config_path = checkout / ".devcontainer/server/devcontainer.json"
    config = json.loads(config_path.read_text())
    config["containerEnv"][variable_name] = "unexpected"
    config_path.write_text(json.dumps(config))

    result = subprocess.run([str(checkout / "tools/dev-env"), "server", "check"],
                            cwd=checkout, capture_output=True, text=True, check=False)

    assert result.returncode != 0


def test_dev_env_identity_is_worktree_scoped_when_invoked_from_linked_worktree():
    result = subprocess.run([str(ROOT / "tools/dev-env"), "server", "identity"],
                            cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    identity = result.stdout.strip()
    assert identity.startswith("fix-documentation-")
    assert len(identity.rsplit("-", 1)[-1]) == 10
    assert all(character in "0123456789abcdef" for character in identity.rsplit("-", 1)[-1])


def test_shared_dockerfile_owns_stages_and_tool_versions():
    dockerfile = (ROOT / ".devcontainer/Dockerfile").read_text()
    assert "FROM mcr.microsoft.com/vscode/devcontainers/python:1-3.12-bookworm AS base" in dockerfile
    assert "FROM base AS server" in dockerfile
    assert "FROM base AS evolver-edge" in dockerfile
    for arg in ("UV_VERSION=0.8.14", "RTK_VERSION=v0.47.0", "NAVI_VERSION=v2.24.0", "ZOXIDE_VERSION=0.9.8"):
        assert dockerfile.count(f"ARG {arg}") == 1
    assert not (ROOT / ".devcontainer/common").exists()


def test_interactive_shell_layers_on_base_zsh_and_keeps_bash_available():
    dockerfile = (ROOT / ".devcontainer/Dockerfile").read_text()
    fragment = (ROOT / ".devcontainer/dotfiles/meta-ball.zsh").read_text()
    dev_env = (ROOT / "tools/dev-env").read_text()
    assert "meta-ball.zsh" in dockerfile
    assert "install -o vscode -g vscode -m 0644 /tmp/.zshrc" not in dockerfile
    assert "usermod --shell /usr/bin/zsh vscode" in dockerfile
    assert "SHELL=/usr/bin/zsh" in dockerfile
    assert "tools/dev-env" in dev_env and "shell)" in dev_env and "zsh -l -i" in dev_env
    assert "tools/navi-widget.zsh" in fragment
    assert "zoxide init zsh" in fragment


def test_cache_contract_is_worktree_scoped_and_edge_runtime_is_stable():
    server = json.loads((ROOT / ".devcontainer/server/devcontainer.json").read_text())
    edge = json.loads((ROOT / ".devcontainer/evolver-edge/devcontainer.json").read_text())
    server_mounts = "\n".join(server["mounts"])
    edge_mounts = "\n".join(edge["mounts"])
    assert "meta-ball-${localEnv:META_BALL_WORKTREE_ID}-uv-cache" in server_mounts
    assert "meta-ball-${localEnv:META_BALL_WORKTREE_ID}-uv-cache" in edge_mounts
    assert "evolver-edge-runtime,target=/run/evolver-controller" in edge_mounts
    assert "evolver-edge-runtime,target=/run/evolver-controller" not in server_mounts


def test_evolver_edge_persists_state_and_bootstraps_non_root_storage():
    edge = json.loads((ROOT / ".devcontainer/evolver-edge/devcontainer.json").read_text())
    edge_mounts = "\n".join(edge["mounts"])
    bootstrap = (ROOT / ".devcontainer/evolver-edge/scripts/bootstrap-evolver-edge").read_text()

    assert "source=evolver-edge-state,target=/var/lib/evolver-controller" in edge_mounts
    assert "source=evolver-edge-runtime,target=/run/evolver-controller" in edge_mounts
    assert "sudo install -d" in bootstrap
    assert "sudo chown vscode:vscode" in bootstrap
    assert "/var/lib/evolver-controller" in bootstrap
    assert "/run/evolver-controller" in bootstrap


def test_evolver_edge_state_volume_is_named_for_recreate_persistence():
    config = json.loads((ROOT / ".devcontainer/evolver-edge/devcontainer.json").read_text())
    edge_mounts = "\n".join(config["mounts"])

    assert "source=evolver-edge-state,target=/var/lib/evolver-controller" in edge_mounts


def test_evolver_edge_devcontainer_is_source_backed_and_has_docker_without_serial():
    config = json.loads((ROOT / ".devcontainer/evolver-edge/devcontainer.json").read_text())
    assert config["name"] == "Meta Ball eVOLVER Edge"
    assert any("docker-outside-of-docker" in feature for feature in config["features"])
    mounts = "\n".join(config["mounts"])
    assert "/var/run/docker.sock" in mounts
    assert "/dev" not in mounts
    launcher = ROOT / ".devcontainer/evolver-edge/scripts/evoctl"
    assert "uv run --project /workspaces/meta_bal/evolver/evolver-controller evoctl" in launcher.read_text()
    # The launcher deliberately points at the checkout, not an installed
    # wheel. A changed CLI module is therefore visible on the next invocation.
    assert "/workspaces/meta_bal/evolver/evolver-controller" in launcher.read_text()


def test_edge_compose_keeps_hardware_as_the_only_device_owner():
    compose = (ROOT / "deploy/evolver-edge/compose.yaml").read_text()
    assert "evolver-controller:" in compose and "evolver-hardware:" in compose
    controller = compose.split("  evolver-controller:", 1)[1]
    hardware = compose.split("  evolver-hardware:", 1)[1].split("  evolver-controller:", 1)[0]
    assert "/dev" not in controller
    assert "/var/run/docker.sock" not in controller and "/var/run/docker.sock" not in hardware
    assert "source: /dev" in hardware
    assert "restart: unless-stopped" in controller and "restart: unless-stopped" in hardware
    assert "network_mode: none" in hardware
    assert "network_mode: host" in controller


def test_edge_has_no_database_service_or_required_database_dependency():
    compose = (ROOT / "deploy/evolver-edge/compose.yaml").read_text().lower()
    for forbidden in ("postgres", "mysql", "redis"):
        assert forbidden not in compose


def test_edge_runtime_volume_is_stable_and_shared_with_edge_devcontainer():
    compose = (ROOT / "deploy/evolver-edge/compose.yaml").read_text()
    config = json.loads((ROOT / ".devcontainer/evolver-edge/devcontainer.json").read_text())
    assert "evolver-edge-runtime:\n    name: evolver-edge-runtime" in compose
    assert any("source=evolver-edge-runtime,target=/run/evolver-controller" in mount
               for mount in config["mounts"])
