from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).parents[2]
LAUNCHER = ROOT / "tools" / "metactl"


def _sandbox(tmp_path: Path) -> tuple[Path, Path]:
    tools = tmp_path / "tools"
    tools.mkdir()
    launcher = tools / "metactl"
    shutil.copy2(LAUNCHER, launcher)
    launcher.chmod(0o755)
    adapter = tools / "evolver-edge"
    adapter.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > \"$CAPTURE\"\n", encoding="utf-8")
    adapter.chmod(0o755)
    return launcher, adapter


def _run(launcher: Path, capture: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ | {"CAPTURE": str(capture), "PATH": os.environ["PATH"]}
    return subprocess.run([str(launcher), *arguments], text=True, capture_output=True,
                          env=environment, check=False)


def test_server_lifecycle_routes_only_allowlisted_commands_to_canonical_adapter(tmp_path: Path) -> None:
    launcher, _ = _sandbox(tmp_path)
    capture = tmp_path / "capture"

    result = _run(launcher, capture, "server", "restart", "controller")

    assert result.returncode == 0
    assert capture.read_text(encoding="utf-8").splitlines() == ["restart", "controller"]


def test_server_lifecycle_rejects_arbitrary_arguments_before_adapter(tmp_path: Path) -> None:
    launcher, _ = _sandbox(tmp_path)
    capture = tmp_path / "capture"

    result = _run(launcher, capture, "server", "logs", "controller", "--project", "evil")

    assert result.returncode == 2
    assert not capture.exists()
    assert "usage: tools/metactl" in result.stderr


def test_server_down_is_distinct_and_upgrade_is_truthfully_unavailable(tmp_path: Path) -> None:
    launcher, _ = _sandbox(tmp_path)
    capture = tmp_path / "capture"

    down = _run(launcher, capture, "server", "down")
    assert down.returncode == 0
    assert capture.read_text(encoding="utf-8").splitlines() == ["down"]

    capture.unlink()
    upgrade = _run(launcher, capture, "server", "upgrade")
    assert upgrade.returncode == 2
    assert "no governed production release selector" in upgrade.stderr
    assert not capture.exists()


def test_non_server_commands_still_use_managed_metactl_runtime(tmp_path: Path) -> None:
    launcher, _ = _sandbox(tmp_path)
    fake_rtk = tmp_path / "rtk"
    capture = tmp_path / "capture"
    fake_rtk.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > \"$CAPTURE\"\n", encoding="utf-8")
    fake_rtk.chmod(0o755)

    environment = os.environ | {"CAPTURE": str(capture), "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    result = subprocess.run([str(launcher), "doctor"], text=True, capture_output=True,
                            env=environment, check=False)

    assert result.returncode == 0
    assert capture.read_text(encoding="utf-8").splitlines() == [
        "tools/dev-env", "server", "exec", "metactl", "doctor"
    ]
