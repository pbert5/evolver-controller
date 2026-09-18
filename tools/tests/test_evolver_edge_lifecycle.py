import json
import os
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "tools/evolver-edge"


def fake_runtime(tmp_path: Path, *, ps_output: str = "evolver-controller\tUp\thealthy\nevolver-hardware\tUp\thealthy\n") -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    calls = tmp_path / "calls.jsonl"
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"calls = {str(calls)!r}\n"
        f"ps_output = {ps_output!r}\n"
        "with open(calls, 'a', encoding='utf-8') as stream:\n"
        "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if 'ps' in sys.argv[1:]:\n"
        "    print(ps_output, end='')\n"
        "elif 'version' in sys.argv[1:]:\n"
        "    print('Docker Compose version v2.0.0')\n"
        "elif sys.argv[1:2] == ['info']:\n"
        "    print('Server: fake')\n"
        "elif os.environ.get('FAKE_DOCKER_FAIL') == '1':\n"
        "    raise SystemExit(1)\n",
        encoding="utf-8",
    )
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    return bin_dir, calls


def run_adapter(tmp_path: Path, *args: str, **kwargs: str) -> subprocess.CompletedProcess[str]:
    bin_dir, calls = fake_runtime(tmp_path, **kwargs)
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "EVOLVER_EDGE_HOST_RUNTIME": "1",
    }
    result = subprocess.run(
        [str(SCRIPT), *args], cwd=ROOT, env=env, text=True, capture_output=True
    )
    result.calls = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
    return result


def test_up_uses_fixed_compose_project_and_reports_healthy_final_state(tmp_path: Path) -> None:
    result = run_adapter(tmp_path, "up")

    assert result.returncode == 0, result.stderr
    compose_up = next(call for call in result.calls if "up" in call)
    assert compose_up[:2] == ["compose", "-f"]
    assert compose_up[2].endswith("/deploy/evolver-edge/compose.yaml")
    assert compose_up[4].endswith("/deploy/evolver-edge/compose.dev.yaml")
    assert compose_up[5:][-3:] == ["evolver-edge", "up", "-d"]
    assert "healthy" in result.stdout


def test_stop_and_down_are_distinct_and_down_preserves_volumes(tmp_path: Path) -> None:
    stop = run_adapter(
        tmp_path / "stop",
        "stop",
        ps_output="evolver-controller\tExited\tnone\nevolver-hardware\tExited\tnone\n",
    )
    down = run_adapter(tmp_path / "down", "down", ps_output="")

    assert stop.returncode == 0, stop.stderr
    assert down.returncode == 0, down.stderr
    stop_command = next(call for call in stop.calls if "stop" in call)
    down_command = next(call for call in down.calls if "down" in call)
    assert stop_command[-1] == "stop"
    assert down_command[-1] == "down"
    assert "--volumes" not in down_command


def test_stop_can_target_one_allowlisted_service_without_stopping_the_other(tmp_path: Path) -> None:
    result = run_adapter(
        tmp_path,
        "stop",
        "controller",
        ps_output="evolver-controller\tExited\tnone\nevolver-hardware\tUp\thealthy\n",
    )

    assert result.returncode == 0, result.stderr
    stop_command = next(call for call in result.calls if "stop" in call)
    assert stop_command[-2:] == ["stop", "evolver-controller"]


def test_unknown_service_fails_closed_without_invoking_compose(tmp_path: Path) -> None:
    result = run_adapter(tmp_path, "restart", "database")

    assert result.returncode == 2
    assert "unknown service" in result.stderr
    assert result.calls == []


def test_denied_host_runtime_fails_closed(tmp_path: Path) -> None:
    bin_dir, calls = fake_runtime(tmp_path)
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "EVOLVER_EDGE_HOST_RUNTIME": "0",
    }

    result = subprocess.run([str(SCRIPT), "status"], cwd=ROOT, env=env, text=True, capture_output=True)

    assert result.returncode == 2
    assert "host runtime" in result.stderr
    assert not calls.exists()


def test_unhealthy_final_state_is_not_reported_as_success(tmp_path: Path) -> None:
    result = run_adapter(
        tmp_path,
        "up",
        ps_output="evolver-controller\tUp\tunhealthy\nevolver-hardware\tUp\thealthy\n",
    )

    assert result.returncode == 1
    assert "unhealthy" in result.stderr


def test_running_without_explicit_healthy_health_is_not_success(tmp_path: Path) -> None:
    result = run_adapter(
        tmp_path,
        "up",
        ps_output="evolver-controller\tUp\nevolver-hardware\tUp\thealthy\n",
    )

    assert result.returncode == 1
    assert "not running" in result.stderr


def test_stop_does_not_accept_a_transitional_restarting_state(tmp_path: Path) -> None:
    result = run_adapter(
        tmp_path,
        "stop",
        ps_output="evolver-controller\trestarting\tnone\nevolver-hardware\tExited\tnone\n",
    )

    assert result.returncode == 1
    assert "still running" in result.stderr


def test_down_does_not_report_success_while_a_service_is_restarting(tmp_path: Path) -> None:
    result = run_adapter(
        tmp_path,
        "down",
        ps_output="evolver-controller\trestarting\tnone\n",
    )

    assert result.returncode == 1


def test_restart_and_logs_use_only_the_canonical_service_name(tmp_path: Path) -> None:
    restart = run_adapter(tmp_path / "restart", "restart", "hardware")
    logs = run_adapter(tmp_path / "logs", "logs", "controller")

    assert restart.returncode == 0, restart.stderr
    assert logs.returncode == 0, logs.stderr
    restart_command = next(call for call in restart.calls if "restart" in call)
    logs_command = next(call for call in logs.calls if "logs" in call)
    assert restart_command[-2:] == ["restart", "evolver-hardware"]
    assert logs_command[-2:] == ["-f", "evolver-controller"]
