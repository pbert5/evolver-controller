"""Deterministic, dependency-light checks for the checked-in schema package."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "registry" / "trusted_actions.yaml"
REQUIRED_MODULES = {
    "base.yaml", "hardware.yaml", "experiment.yaml", "calibration.yaml",
    "protocol.yaml", "experiment_program.yaml", "requirements.yaml",
    "measurement.yaml", "validation.yaml", "fixture.yaml",
}
FORBIDDEN_ACTION_KEYS = {"python", "source", "module", "import", "shell", "url", "expression"}


def load_modules(root: Path) -> dict[str, dict]:
    directory = root / "instrument"
    modules = {}
    for path in sorted(directory.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or not document.get("name"):
            raise ValueError(f"{path}: expected a schema document with name")
        modules[path.name] = document
    missing = REQUIRED_MODULES - modules.keys()
    if missing:
        raise ValueError(f"missing schema modules: {', '.join(sorted(missing))}")
    return modules


def validate_imports(root: Path, modules: dict[str, dict]) -> None:
    names = {p.stem for p in (root / "instrument").glob("*.yaml")}
    for filename, document in modules.items():
        for imported in document.get("imports", []):
            if isinstance(imported, str) and not imported.startswith("linkml:") and imported not in names:
                raise ValueError(f"{filename}: unresolved import {imported!r}")


def _walk(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield path + (str(key),), child
            yield from _walk(child, path + (str(key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, path + (str(index),))


def validate_contract(modules: dict[str, dict]) -> None:
    experiment = modules["experiment.yaml"]
    purposes = experiment["enums"]["ExperimentPurpose"]["permissible_values"]
    expected = {"research", "test_fixture", "commissioning", "calibration", "validation", "verification", "endurance", "diagnostic"}
    if set(purposes) != expected:
        raise ValueError("ExperimentPurpose must contain exactly the supported purpose values")
    execution_modes = experiment["enums"]["BundleExecutionMode"]["permissible_values"]
    if set(execution_modes) != {"declarative_state_machine"}:
        raise ValueError("BundleExecutionMode must contain exactly declarative_state_machine")
    protocol = modules["protocol.yaml"]
    if any(name in protocol.get("classes", {}) for name in ("ExperimentProgram", "ConditionExpression", "AcceptanceCriterion")):
        raise ValueError("protocol.yaml must remain transport-only")
    actions = modules["experiment_program.yaml"]["classes"]["ActionInvocation"]["attributes"]
    if FORBIDDEN_ACTION_KEYS & set(actions):
        raise ValueError("ActionInvocation contains an arbitrary-execution field")


def validate_action_registry(root: Path) -> None:
    path = root / "registry" / "trusted_actions.yaml"
    registry = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(registry, dict) or not registry.get("version") or not registry.get("revision"):
        raise ValueError("trusted action registry requires version and revision")
    actions = registry.get("actions")
    if not isinstance(actions, dict) or not actions:
        raise ValueError("trusted action registry requires actions")
    for action_id, record in actions.items():
        if not isinstance(action_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", action_id):
            raise ValueError(f"invalid trusted action ID: {action_id!r}")
        if not isinstance(record, dict) or not record.get("versions"):
            raise ValueError(f"{action_id}: trusted action requires versions")
        if any(not isinstance(version, str) for version in record["versions"]):
            raise ValueError(f"{action_id}: action versions must be strings")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        modules = load_modules(args.root)
        validate_imports(args.root, modules)
        validate_contract(modules)
        validate_action_registry(args.root)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"schema validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"validated {len(modules)} schema modules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
