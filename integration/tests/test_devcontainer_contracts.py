import json
from pathlib import Path


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
    for member in ("evolver-controller", "evolver-hardware", "evolver-server"):
        assert member in pyproject
    assert "metactl/tests" not in pyproject
    for script in ("tools/dev-env", "tools/test", "tools/test-fast", "tools/test-serial"):
        assert (ROOT / script).is_file()
