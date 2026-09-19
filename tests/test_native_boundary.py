from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]
SRC = ROOT / "src"


def test_controller_has_native_package_and_no_copied_central_modules() -> None:
    package = SRC / "evolver_controller"
    assert package.is_dir()
    assert (SRC / "evolver_controller").is_dir()
    assert not (SRC / "meta_webui_application_backend").exists()


def test_controller_runtime_has_no_forbidden_implementation_imports() -> None:
    production = "\n".join(path.read_text() for path in SRC.rglob("*.py"))
    assert "meta_webui_application_backend" not in production
    assert "evolver_control" not in production
    assert "import psycopg" not in production
    assert "import serial" not in production


def test_controller_console_contract_excludes_hardware_daemon() -> None:
    manifest = (ROOT / "pyproject.toml").read_text()
    assert 'evoctl = "evolver_controller.cli:main"' in manifest
    assert 'evolver-controller = "evolver_controller.service:main"' in manifest
    assert "evolver-hardware" not in manifest
    assert "psycopg" not in manifest
    assert "pyserial" not in manifest


def test_controller_installer_owns_only_controller_runtime() -> None:
    installer = (SRC / "evolver_controller" / "install.py").read_text()
    assert "evolver-hardware" not in installer
    assert "hardware_systemd_unit" not in installer
