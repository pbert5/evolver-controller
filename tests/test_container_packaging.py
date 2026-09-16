from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).parents[1]


def test_clean_controller_image_imports_yaml_and_live_operator_path() -> None:
    if shutil.which("docker") is None:
        pytest.fail("docker is required for the clean controller image smoke test")

    image = f"evolver-controller-packaging-test:{__import__('os').getpid()}"
    try:
        subprocess.run(
            ["docker", "build", "--no-cache", "--tag", image, str(ROOT)],
            check=True,
            capture_output=True,
            text=True,
        )
        smoke = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "python",
                image,
                "-c",
                (
                    "import yaml; "
                    "import meta_webui_application_backend.evolver_edge.service"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert smoke.returncode == 0, smoke.stderr
    finally:
        subprocess.run(["docker", "image", "rm", "--force", image], check=False)


def test_dockerfile_installs_dependencies_before_application_source() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    requirements_copy = dockerfile.index("COPY requirements.txt")
    dependency_install = dockerfile.index("pip install --no-cache-dir -r requirements.txt")
    source_copy = dockerfile.index("COPY src ./src")
    application_install = dockerfile.index("pip install --no-cache-dir --no-deps .")

    assert requirements_copy < dependency_install < source_copy < application_install
    assert "COPY . /app" not in dockerfile


def test_dependency_manifest_matches_runtime_project_dependencies() -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()

    dependencies = ("pyserial==3.5", "zstandard==0.25.0", "psycopg[binary]>=3.1")
    assert tuple(requirements) == dependencies
    for dependency in dependencies:
        assert dependency in project


def test_dockerignore_keeps_packaging_inputs_and_excludes_non_runtime_files() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "tests/" in dockerignore
    assert "README.md" in dockerignore
    assert "pyproject.toml" not in dockerignore
    assert "requirements.txt" not in dockerignore
    assert "src/" not in dockerignore
