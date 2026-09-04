from pathlib import Path


ROOT = Path(__file__).parents[1]


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
