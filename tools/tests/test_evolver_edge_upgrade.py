from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "tools/evolver-edge"


def _sandbox(tmp_path: Path, *, dirty: bool = False, merge_failure: bool = False,
             docker_failure: bool = False, unhealthy: bool = False) -> tuple[Path, Path, Path]:
    checkout = tmp_path / "checkout"
    (checkout / "tools").mkdir(parents=True)
    (checkout / "deploy/evolver-edge").mkdir(parents=True)
    shutil.copy2(SCRIPT, checkout / "tools/evolver-edge")
    (checkout / "tools/evolver-edge").chmod(0o755)
    (checkout / "deploy/evolver-edge/compose.yaml").touch()
    (checkout / "deploy/evolver-edge/compose.dev.yaml").touch()
    if dirty:
        (checkout / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    git_log = tmp_path / "git.jsonl"
    docker_log = tmp_path / "docker.jsonl"
    git = fake_bin / "git"
    git.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"log = {str(git_log)!r}\n"
        f"state = {str(tmp_path / 'git-state')!r}\n"
        "args = sys.argv[1:]\n"
        "with open(log, 'a', encoding='utf-8') as stream:\n"
        "    stream.write(json.dumps(args) + '\\n')\n"
        "if args[-2:] == ['status', '--porcelain']:\n"
        f"    print({' M dirty.txt' if dirty else ''!r}, end='')\n"
        "elif 'symbolic-ref' in args and '--short' in args:\n"
        "    print('hardware-testing')\n"
        "elif 'rev-parse' in args and '--symbolic-full-name' in args:\n"
        "    print('origin/hardware-testing')\n"
        "elif args[-2:] == ['rev-parse', 'HEAD']:\n"
        "    print('new-parent-sha' if os.path.exists(state) else 'old-parent-sha')\n"
        "elif 'fetch' in args:\n"
        "    pass\n"
        "elif 'merge' in args and os.environ.get('FAKE_GIT_MERGE_FAIL') == '1':\n"
        "    raise SystemExit(1)\n"
        "elif 'merge' in args:\n"
        "    open(state, 'w', encoding='utf-8').close()\n"
        "elif 'submodule' in args and 'sync' in args:\n"
        "    pass\n"
        "elif 'submodule' in args and 'update' in args:\n"
        "    pass\n",
        encoding="utf-8",
    )
    docker = fake_bin / "docker"
    health = "unhealthy" if unhealthy else "healthy"
    docker.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"log = {str(docker_log)!r}\n"
        "args = sys.argv[1:]\n"
        "with open(log, 'a', encoding='utf-8') as stream:\n"
        "    stream.write(json.dumps(args) + '\\n')\n"
        "if args[:1] == ['info'] or 'version' in args:\n"
        "    raise SystemExit(0)\n"
        "if os.environ.get('FAKE_DOCKER_FAIL') == '1' and 'up' in args:\n"
        "    raise SystemExit(1)\n"
        "if 'ps' in args:\n"
        f"    print('evolver-controller\\tUp\\t{health}\\nevolver-hardware\\tUp\\t{health}\\n', end='')\n",
        encoding="utf-8",
    )
    for executable in (git, docker):
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return checkout, git_log, docker_log


def _run(tmp_path: Path, *options: str, **flags: bool) -> subprocess.CompletedProcess[str]:
    checkout, git_log, docker_log = _sandbox(tmp_path, **flags)
    env = os.environ | {"PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}"}
    if flags.get("merge_failure"):
        env["FAKE_GIT_MERGE_FAIL"] = "1"
    if flags.get("docker_failure"):
        env["FAKE_DOCKER_FAIL"] = "1"
    result = subprocess.run(
        [str(checkout / "tools/evolver-edge"), *options],
        cwd=checkout,
        env=env,
        text=True,
        capture_output=True,
    )
    result.git_calls = [json.loads(line) for line in git_log.read_text().splitlines()] if git_log.exists() else []
    result.docker_calls = [json.loads(line) for line in docker_log.read_text().splitlines()] if docker_log.exists() else []
    return result


def test_upgrade_fast_forwards_submodules_rebuilds_and_reports_parent_shas(tmp_path: Path) -> None:
    result = _run(tmp_path, "upgrade")

    assert result.returncode == 0, result.stderr
    assert "old-parent-sha" in result.stdout
    assert "new-parent-sha" in result.stdout
    assert any(call[-3:] == ["fetch", "--prune", "origin"] for call in result.git_calls)
    assert any("merge" in call and "--ff-only" in call for call in result.git_calls)
    assert any("submodule" in call and "sync" in call for call in result.git_calls)
    assert any("submodule" in call and "update" in call for call in result.git_calls)
    compose_up = next(call for call in result.docker_calls if "up" in call)
    assert "--build" in compose_up
    assert "--volumes" not in compose_up


def test_upgrade_refuses_dirty_checkout_before_fetch(tmp_path: Path) -> None:
    result = _run(tmp_path, "upgrade", dirty=True)

    assert result.returncode != 0
    assert "clean checkout" in result.stderr
    assert not result.git_calls or not any("fetch" in call for call in result.git_calls)


def test_upgrade_refuses_non_fast_forward_without_rebuilding(tmp_path: Path) -> None:
    result = _run(tmp_path, "upgrade", merge_failure=True)

    assert result.returncode != 0
    assert "fast-forward" in result.stderr
    assert not any("up" in call for call in result.docker_calls)


def test_upgrade_reports_build_failure_without_success(tmp_path: Path) -> None:
    result = _run(tmp_path, "upgrade", docker_failure=True)

    assert result.returncode == 1
    assert "success" not in result.stdout.lower()


def test_upgrade_reports_unhealthy_runtime_without_success(tmp_path: Path) -> None:
    result = _run(tmp_path, "upgrade", unhealthy=True)

    assert result.returncode == 1
    assert "unhealthy" in result.stderr
    assert "success" not in result.stdout.lower()
