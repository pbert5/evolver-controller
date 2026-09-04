import json
import subprocess
from pathlib import Path

import pytest


pytestmark = pytest.mark.integration


ROOT = Path(__file__).parents[2]


def test_common_container_is_meta_ball_and_safe():
    config = json.loads((ROOT / ".devcontainer/common/devcontainer.json").read_text())
    assert config["name"] == "Meta Ball Common Toolchain"
    assert config["forwardPorts"] == [18086]
    assert config["containerEnv"]["META_BAL_DEV_BIND_ADDRESS"].endswith("127.0.0.1}")
    assert any("docker-outside-of-docker" in feature for feature in config["features"])
    mounts = "\n".join(config["mounts"])
    assert "uv-cache" in mounts and "npm-cache" not in mounts
    assert "workspaceFolder}/.venv" not in mounts


def test_stale_webui_and_browser_tooling_are_absent():
    text = "\n".join(
        p.read_text() for p in [ROOT / ".devcontainer/common/Dockerfile", ROOT / ".devcontainer/common/devcontainer.json"]
    )
    for stale in ("meta-webui", "META_WEBUI", "PLAYWRIGHT", "npm", "nodejs", "chromium"):
        assert stale.lower() not in text.lower()


def test_workspace_members_and_contract_scripts_exist():
    pyproject = (ROOT / "pyproject.toml").read_text()
    for member in ("evolver/evolver-controller", "evolver/evolver-hardware", "evolver/evolver-server"):
        assert member in pyproject
    assert "metactl/tests" not in pyproject
    for script in ("tools/dev-env", "tools/check-locks", "tools/test", "tools/test-fast", "tools/test-serial"):
        assert (ROOT / script).is_file()
        assert (ROOT / script).stat().st_mode & 0o111


@pytest.mark.parametrize("argv", [("common", "check"), ("check", "common")])
def test_dev_env_accepts_canonical_and_legacy_profile_order(argv):
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
