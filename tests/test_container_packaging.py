from pathlib import Path
import shutil
import subprocess
import tomllib

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
        subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "evoctl", image, "--help"],
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
                    "import evolver_procedure_runtime; "
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

    dependencies = (
        "pyserial==3.5",
        "zstandard==0.25.0",
        "psycopg[binary]>=3.1",
        "PyYAML>=6",
        "evolver-procedure-runtime @ https://github.com/pbert5/evolver-procedure-runtime/archive/e82b2a2a54004540e5de6418e07670b8e8b5b30c.tar.gz",
    )
    assert tuple(requirements) == dependencies
    for dependency in dependencies[:-1]:
        assert dependency in project
    assert "evolver-procedure-runtime==0.1.0" in project


def test_tui_extra_declares_immutable_standalone_webui_packages() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["optional-dependencies"]["tui"] == [
        "textual>=0.89,<2",
        "jsonschema>=4.18,<5",
        "meta-webui-config-compiler @ git+https://github.com/pbert5/meta-webui-config-compiler.git@f72b70fe227857a2b0584ed54204446f47f4c894",
        "meta-webui-ui-runtime-textual @ git+https://github.com/pbert5/meta-webui-ui-runtime-textual.git@d5c4119371db927f3db823caa4ed8d9823edd372",
    ]


def test_dockerignore_keeps_packaging_inputs_and_excludes_non_runtime_files() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "tests/" in dockerignore
    assert "README.md" in dockerignore
    assert "pyproject.toml" not in dockerignore
    assert "requirements.txt" not in dockerignore
    assert "src/" not in dockerignore
