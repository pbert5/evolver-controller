import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[2]


def _fake_command(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def test_edge_evoctl_launcher_reports_unavailable_operator_without_falling_back(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "invoked"
    _fake_command(bin_dir, "uv", f"touch '{marker}'")

    result = subprocess.run(
        [str(ROOT / ".devcontainer/evolver-edge/scripts/evoctl"), "status"],
        cwd=ROOT,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
             "EVOLVER_OPERATOR_SOCKET": str(tmp_path / "missing.sock")},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 69
    assert not marker.exists()
    assert "operator service is unavailable" in result.stderr
    assert "tools/evolver-edge up" in result.stderr
    assert "tools/evolver-edge status" in result.stderr
    assert "tools/evolver-edge logs controller" in result.stderr


def test_edge_evoctl_launcher_rescue_is_explicitly_offline(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    arguments = tmp_path / "arguments"
    _fake_command(bin_dir, "uv", f"printf '%s\\n' \"$@\" > '{arguments}'")

    result = subprocess.run(
        [str(ROOT / ".devcontainer/evolver-edge/scripts/evoctl"), "rescue", "recovery"],
        cwd=ROOT,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
             "EVOLVER_OPERATOR_SOCKET": str(tmp_path / "missing.sock")},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert arguments.read_text(encoding="utf-8").splitlines()[-2:] == ["--offline", "recovery"]


def test_edge_helper_diagnose_preserves_compose_commands_and_gives_recovery_route(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    arguments = tmp_path / "arguments"
    _fake_command(bin_dir, "docker", f"printf '%s\\n' \"$@\" > '{arguments}'")

    result = subprocess.run(
        [str(ROOT / "tools/evolver-edge"), "diagnose"],
        cwd=ROOT,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "ps" in arguments.read_text(encoding="utf-8").splitlines()
    assert "--all" in arguments.read_text(encoding="utf-8").splitlines()
    assert "tools/evolver-edge up" in result.stdout
    assert "tools/evolver-edge status" in result.stdout
    assert "tools/evolver-edge logs controller" in result.stdout


def test_edge_helper_status_identifies_a_stopped_controller(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_command(bin_dir, "docker", "echo 'evolver-controller Exited (1)'")

    result = subprocess.run(
        [str(ROOT / "tools/evolver-edge"), "status"],
        cwd=ROOT,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Controller is stopped" in result.stderr
    assert "tools/evolver-edge up" in result.stderr


def test_edge_docs_define_live_offline_topology_and_rescue_route():
    docs = "\n".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in ("docs/operator.md", "docs/development.md", ".devcontainer/README.md")
    )

    for phrase in (
        "live",
        "offline",
        "evoctl -> operator.sock -> controller -> hardware.sock -> hardware -> serial",
        "tools/evolver-edge rescue recovery",
        "does not silently fall back",
    ):
        assert phrase in docs
