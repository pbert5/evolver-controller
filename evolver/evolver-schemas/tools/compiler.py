"""Small deterministic compiler boundary for schema-defined experiment bundles."""
from __future__ import annotations

import hashlib
import json
import random
from copy import deepcopy
from typing import Any

import yaml

TRUSTED_ACTIONS = {
    "set_temperature", "set_stirring", "pulse_pump", "run_pump", "stop_actuator",
    "capture_measurement", "wait", "start_activity", "stop_activity",
    "request_observation", "evaluate_criteria", "emit_marker", "complete_run", "fail_run",
}


class DefinitionError(ValueError):
    def __init__(self, path: str, message: str):
        self.path = path
        super().__init__(f"{path}: {message}")


def load_definition(source: str | bytes) -> dict[str, Any]:
    value = yaml.safe_load(source)
    if not isinstance(value, dict):
        raise DefinitionError("$", "definition must be a mapping")
    return value


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _actions(program: dict[str, Any]):
    for si, step in enumerate(program.get("steps", [])):
        for ai, action in enumerate(step.get("entry_actions", [])):
            yield f"program.steps[{si}].entry_actions[{ai}]", action
        for ai, scheduled in enumerate(step.get("periodic_actions", [])):
            yield f"program.steps[{si}].periodic_actions[{ai}].action", scheduled.get("action", {})


def _validate(definition: dict[str, Any], action_registry: set[str]) -> None:
    for field in ("id", "purpose", "program"):
        if field not in definition:
            raise DefinitionError(field, "is required")
    program = definition["program"]
    if not isinstance(program, dict):
        raise DefinitionError("program", "must be a mapping")
    if not program.get("version") or not program.get("entry_step_id"):
        raise DefinitionError("program", "version and entry_step_id are required")
    steps = program.get("steps", [])
    ids = {step.get("id") for step in steps if isinstance(step, dict)}
    if len(ids) != len(steps):
        raise DefinitionError("program.steps", "each step requires a unique id")
    if program["entry_step_id"] not in ids:
        raise DefinitionError("program.entry_step_id", "does not name a step")
    for path, action in _actions(program):
        if not isinstance(action, dict) or not action.get("action_id"):
            raise DefinitionError(path, "trusted action_id is required")
        if not action.get("action_version"):
            raise DefinitionError(path, "action_version is required")
        if action["action_id"] not in action_registry:
            raise DefinitionError(path + ".action_id", f"unknown trusted action {action['action_id']!r}")
        forbidden = {"python", "module", "import", "shell", "source", "url", "expression"} & action.keys()
        if forbidden:
            raise DefinitionError(path, f"arbitrary execution field is forbidden: {sorted(forbidden)[0]}")
    for si, step in enumerate(steps):
        for ti, transition in enumerate(step.get("transitions", [])):
            target = transition.get("target_step_id")
            if target not in ids:
                raise DefinitionError(f"program.steps[{si}].transitions[{ti}].target_step_id", "unknown step")


def compile_definition(definition: dict[str, Any], *, action_registry: set[str] | None = None) -> dict[str, Any]:
    """Return a canonical immutable bundle representation with a stable digest."""
    document = deepcopy(definition)
    _validate(document, action_registry or TRUSTED_ACTIONS)
    program = document["program"]
    # Resolve random windows without wall-clock data. The seed and constraints
    # remain in the bundle, and the resolved offset is reproducible.
    for step in program.get("steps", []):
        for scheduled in step.get("periodic_actions", []):
            trigger = scheduled.get("trigger", {})
            if trigger.get("kind") == "random_window":
                window = trigger.get("random_window", trigger)
                seed = int(window["seed"])
                earliest = float(window["earliest"]["value"])
                latest = float(window["latest"]["value"])
                scheduled["resolved_offset"] = random.Random(seed).uniform(earliest, latest)
    bundle = {
        "definition_id": document["id"],
        "definition_revision": document.get("revision"),
        "purpose": document["purpose"],
        "resolved_definition": document,
        "action_registry_revision": document.get("action_registry_revision", "builtin-1"),
        "schema_version": "0.1.0",
        "execution_mode": "declarative_state_machine",
    }
    bundle["digest"] = hashlib.sha256(_canonical(bundle).encode()).hexdigest()
    return bundle
