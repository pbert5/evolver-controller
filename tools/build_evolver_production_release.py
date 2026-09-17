#!/usr/bin/env python3
"""Build, validate, and stage one immutable eVOLVER production release."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ARDUINO_CLI_URL = "https://downloads.arduino.cc/arduino-cli/arduino-cli_1.1.1_Linux_64bit.tar.gz"
ARDUINO_CLI_SHA256 = "2b807add5c3a518861bfd4d3e78de9e02b0a2723df3d90386df2200a767349c4"
TARGETS = ("linux-x86_64-glibc", "linux-x86_64-nixos")


def ensure_executable(path: Path) -> None:
    """Preserve the cached tool but repair executable bits lost by staging."""
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("releases/evolver"))
    parser.add_argument("--version", help="immutable release ID; defaults to 0.2.0-GIT7")
    parser.add_argument("--git-revision", help="source Git revision to record in the release manifest")
    parser.add_argument("--build-timestamp")
    parser.add_argument("--offline", action="store_true",
                        help="use only explicitly supplied, pre-provisioned toolchain inputs")
    parser.add_argument("--skip-firmware", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--toolchain-variant", choices=TARGETS, help=argparse.SUPPRESS)
    parser.add_argument("--nixos-bossac", type=Path,
                        help="Nix-patched exact BOSSA executable when using the NixOS variant")
    parser.add_argument("--nixos-bossac-store-root", type=Path,
                        help="exact Nix store package root containing --nixos-bossac")
    parser.add_argument("--arduino-cli", "--nixos-arduino-cli", dest="arduino_cli", type=Path,
                        help="explicit pinned arduino-cli executable (required for NixOS builds)")
    parser.add_argument("--arduino-data", "--nixos-arduino-data", dest="arduino_data", type=Path,
                        help="pre-provisioned Arduino data directory (required for offline NixOS builds)")
    parser.add_argument("--arduino-libraries", "--nixos-arduino-libraries", dest="arduino_libraries", type=Path,
                        help="pre-provisioned Arduino user libraries (required for offline NixOS builds)")
    parser.add_argument("--wheelhouse", type=Path,
                        help="controlled offline wheelhouse for the native artifact dependencies")
    parser.add_argument("--python-runtime", type=Path,
                        help="release-owned glibc Python tree to embed in each native artifact")
    parser.add_argument("--validator-python", default=os.environ.get("EVOLVER_VALIDATOR_PYTHON", "python3"),
                        help="Python executable used to validate the packaged edge artifact")
    args = parser.parse_args()
    targets = (args.toolchain_variant,) if args.toolchain_variant else TARGETS
    root = Path(__file__).resolve().parents[1]
    revision = args.git_revision or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{7,64}", revision):
        parser.error("--git-revision must be a lowercase hexadecimal Git SHA (7-64 characters)")
    version = args.version or f"0.2.0-{revision[:7]}"
    timestamp = args.build_timestamp or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with tempfile.TemporaryDirectory(prefix="evolver-production-") as temp_name:
        temp = Path(temp_name)
        firmware = temp / "firmware"
        arduino_data = temp / "arduino-data"
        arduino_libraries = temp / "arduino-libraries"
        arduino_libraries.mkdir()
        arduino_config = temp / "arduino-cli.yaml"
        if not args.skip_firmware:
            offline_nixos = args.offline or "linux-x86_64-nixos" in targets
            if offline_nixos and (args.arduino_cli is None or args.arduino_data is None or args.arduino_libraries is None):
                raise SystemExit("NixOS production builds require --nixos-arduino-cli, --nixos-arduino-data, and --nixos-arduino-libraries; refusing PATH/download fallback")
            if args.arduino_cli is not None:
                cli_path = args.arduino_cli.resolve()
                if not cli_path.is_file() or not os.access(cli_path, os.X_OK):
                    raise SystemExit(f"pinned Arduino CLI is missing or not executable: {cli_path}")
                cli = str(cli_path)
            else:
                cli = shutil.which("arduino-cli")
            if not cli and not offline_nixos:
                cli_archive = temp / "arduino-cli.tar.gz"
                subprocess.run(["curl", "--fail", "--location", "--retry", "3", ARDUINO_CLI_URL, "-o", str(cli_archive)], check=True)
                if hashlib.sha256(cli_archive.read_bytes()).hexdigest() != ARDUINO_CLI_SHA256:
                    raise SystemExit("Arduino CLI archive checksum mismatch")
                subprocess.run(["tar", "-xzf", str(cli_archive), "-C", str(temp)], check=True)
                cli = str(temp / "arduino-cli")
            if not cli:
                raise SystemExit("pinned Arduino CLI is unavailable")
            if args.arduino_data is not None:
                supplied_data = args.arduino_data.resolve()
                if not supplied_data.is_dir():
                    raise SystemExit(f"pinned Arduino data directory is missing: {supplied_data}")
                # Keep the caller's pre-provisioned data immutable.  The
                # board validator needs the selected uploader at the exact
                # Arduino package path, so stage the data privately and place
                # the explicitly pinned NixOS BOSSA there before compiling.
                shutil.copytree(supplied_data, arduino_data, symlinks=True)
                staged_bossac = arduino_data / "packages/arduino/tools/bossac/1.7.0-arduino3/bin/bossac"
                if staged_bossac.is_file():
                    ensure_executable(staged_bossac)
                if offline_nixos and args.nixos_bossac is not None:
                    bossac = args.nixos_bossac.resolve()
                    if not bossac.is_file() or not os.access(bossac, os.X_OK):
                        raise SystemExit(f"pinned NixOS BOSSA is missing or not executable: {bossac}")
                    selected_bossac = arduino_data / "packages/arduino/tools/bossac/1.7.0-arduino3/bin/bossac"
                    selected_bossac.parent.mkdir(parents=True, exist_ok=True)
                    if selected_bossac.exists():
                        selected_bossac.chmod(0o755)
                    shutil.copy2(bossac, selected_bossac)
                    selected_bossac.chmod(0o755)
            if args.arduino_libraries is not None:
                supplied_libraries = args.arduino_libraries.resolve()
                if not supplied_libraries.is_dir():
                    raise SystemExit(f"pinned Arduino libraries directory is missing: {supplied_libraries}")
                shutil.copytree(supplied_libraries, arduino_libraries, dirs_exist_ok=True, symlinks=True)
            env = {**os.environ, "ARDUINO_DIRECTORIES_DATA": str(arduino_data), "ARDUINO_CONFIG_FILE": str(arduino_config),
                   "ARDUINO_DIRECTORIES_USER": str(arduino_libraries),
                   "PATH": str(Path(cli).parent) + os.pathsep + os.environ.get("PATH", "")}
            cli_args = ["--config-file", str(arduino_config)]
            subprocess.run([cli, *cli_args, "config", "init", "--overwrite", "--dest-file", str(arduino_config)], env=env, check=True)
            subprocess.run([cli, "config", "set", "directories.user", str(arduino_libraries), *cli_args], env=env, check=True)
            subprocess.run([cli, "config", "add", "board_manager.additional_urls",
                            "https://raw.githubusercontent.com/sparkfun/Arduino_Boards/main/IDE_Board_Manager/package_sparkfun_index.json",
                            *cli_args], env=env, check=True)
            if not offline_nixos:
                subprocess.run([cli, "core", "update-index", *cli_args], env=env, check=True)
                for core in ("arduino:samd@1.8.1", "SparkFun:samd@1.8.13"):
                    subprocess.run([cli, "core", "install", core, *cli_args], env=env, check=True)
                subprocess.run([cli, "lib", "install", "FlashStorage_SAMD@1.3.2", *cli_args], env=env, check=True)
            # Arduino CLI's downloaded 1.7.0-arduino3 archive currently
            # installs its executable at the package root, while the
            # release contract deliberately uses the canonical bin/ path
            # (and the Nix package already has that layout). Normalize the
            # private build staging tree; this does not alter the checked-in
            # firmware source or the release manifest by hand.
            selected_bossac = arduino_data / "packages/arduino/tools/bossac/1.7.0-arduino3"
            canonical_bossac = selected_bossac / "bin/bossac"
            root_bossac = selected_bossac / "bossac"
            if not canonical_bossac.is_file() and root_bossac.is_file():
                canonical_bossac.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root_bossac, canonical_bossac)
                canonical_bossac.chmod(0o755)
            if canonical_bossac.is_file():
                ensure_executable(canonical_bossac)
            subprocess.run([sys_executable(), "tools/build_evolver_firmware.py", "--output", str(firmware),
                            "--build-revision", revision, "--build-timestamp", timestamp], cwd=root, env=env, check=True)
        else:
            raise SystemExit("production release requires a clean firmware build")
        artifacts = []
        for target in targets:
            native = temp / f"{target}.tar.gz"
            native_command = [sys_executable(), "tools/build_evolver_native_artifact.py", "--output", str(native),
                              "--platform", target, "--source-revision", revision,
                              *( ["--python-runtime", str(args.python_runtime)] if args.python_runtime else []),
                              *(["--wheelhouse", str(args.wheelhouse)] if args.wheelhouse else []),
                              "--arduino-data", str(arduino_data), "--arduino-cli", str(cli),
                              "--arduino-libraries", str(temp / "arduino-libraries"),
                              "--toolchain-variant", target]
            if target == "linux-x86_64-nixos" and args.nixos_bossac:
                native_command.extend(["--bossac", str(args.nixos_bossac)])
                if args.nixos_bossac_store_root:
                    native_command.extend(["--bossac-store-root", str(args.nixos_bossac_store_root)])
            subprocess.run(native_command, cwd=root, check=True)
            subprocess.run([sys_executable(), "tools/check_evolver_native_artifact.py", str(native),
                            "--python", args.validator_python], cwd=root, check=True)
            artifacts.append(f"{target}={native}")
        subprocess.run([sys_executable(), "tools/build_evolver_release.py", "--output", str(args.output),
                        "--version", version, "--git-revision", revision, "--build-timestamp", timestamp,
                        *sum((["--artifact", item] for item in artifacts), []), "--firmware",
                        str(next(firmware.glob("samd21-minievolver-*.bin"))), "--firmware-manifest",
                        str(firmware / "firmware-manifest.json"), "--require-firmware-toolchain",
                        "--schema-root", str(root / "evolver/evolver-schemas")], cwd=root, check=True)
    release = args.output / version
    subprocess.run([args.validator_python, "tools/validate_evolver_release.py", str(release)], cwd=root, check=True)
    print(json.dumps({"release": version, "git_revision": revision, "path": str(release.resolve())}, sort_keys=True))
    return 0


def sys_executable() -> str:
    import sys
    return sys.executable


if __name__ == "__main__":
    raise SystemExit(main())
