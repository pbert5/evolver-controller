"""Small deterministic compiler boundary for schema-defined experiment bundles."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "registry" / "trusted_actions.yaml"
SCHEMA_VERSION = "0.1.0"


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
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def load_trusted_action_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    registry = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(registry, dict) or not isinstance(registry.get("actions"), dict):
        raise DefinitionError("action_registry", "must contain an actions mapping")
    if not registry.get("version") or not registry.get("revision"):
        raise DefinitionError("action_registry", "version and revision are required")
    for action_id, record in registry["actions"].items():
        if not isinstance(action_id, str) or not isinstance(record, dict) or not isinstance(record.get("versions"), list) or not record["versions"]:
            raise DefinitionError(f"action_registry.actions[{action_id!r}]", "requires a non-empty versions list")
    return registry


def _registry_records(action_registry: Any) -> tuple[dict[str, Any], str]:
    if action_registry is None:
        registry = load_trusted_action_registry()
        return registry["actions"], registry["revision"]
    if isinstance(action_registry, set):  # backwards-compatible test/integration seam
        return {action_id: {"versions": ["1"]} for action_id in action_registry}, "custom"
    if isinstance(action_registry, dict) and "actions" in action_registry:
        return action_registry["actions"], str(action_registry.get("revision", "custom"))
    if isinstance(action_registry, dict):
        return action_registry, "custom"
    raise DefinitionError("action_registry", "must be a registry mapping or set of action IDs")


def _actions(program: dict[str, Any]):
    for si, step in enumerate(program.get("steps", [])):
        entry_actions = step.get("entry_actions", [])
        periodic_actions = step.get("periodic_actions", [])
        if not isinstance(entry_actions, list):
            raise DefinitionError(f"program.steps[{si}].entry_actions", "must be a list")
        if not isinstance(periodic_actions, list):
            raise DefinitionError(f"program.steps[{si}].periodic_actions", "must be a list")
        for ai, action in enumerate(entry_actions):
            yield f"program.steps[{si}].entry_actions[{ai}]", action
        for ai, scheduled in enumerate(periodic_actions):
            if not isinstance(scheduled, dict):
                raise DefinitionError(f"program.steps[{si}].periodic_actions[{ai}]", "must be a mapping")
            yield f"program.steps[{si}].periodic_actions[{ai}].action", scheduled.get("action", {})


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DefinitionError(path, "must be a mapping")
    return value


def _validate_condition(condition: Any, path: str) -> None:
    condition = _mapping(condition, path)
    if condition.get("operator") not in {"eq", "ne", "lt", "lte", "gt", "gte", "and", "or", "not", "between"}:
        raise DefinitionError(path + ".operator", "unknown condition operator")
    operands = condition.get("operands")
    if not isinstance(operands, list) or not operands:
        raise DefinitionError(path + ".operands", "requires a non-empty list")
    for index, operand in enumerate(operands):
        operand = _mapping(operand, f"{path}.operands[{index}]")
        if operand.get("kind") not in {"measurement", "state", "literal", "parameter", "elapsed_time", "activity_setting", "activity_state"}:
            raise DefinitionError(f"{path}.operands[{index}].kind", "unknown operand kind")
        if sum(key in operand for key in ("reference", "literal", "parameter")) != 1:
            raise DefinitionError(f"{path}.operands[{index}]", "requires exactly one operand value")


def _validate(definition: dict[str, Any], action_registry: Any) -> str:
    for field in ("id", "purpose", "program"):
        if field not in definition:
            raise DefinitionError(field, "is required")
    program = definition["program"]
    if not isinstance(program, dict):
        raise DefinitionError("program", "must be a mapping")
    if not isinstance(program.get("version"), str) or not program.get("version") or not program.get("entry_step_id"):
        raise DefinitionError("program", "version and entry_step_id are required")
    steps = program.get("steps", [])
    if not isinstance(steps, list) or not steps:
        raise DefinitionError("program.steps", "requires a non-empty list")
    if any(not isinstance(step, dict) or not isinstance(step.get("id"), str) or not step["id"] for step in steps):
        raise DefinitionError("program.steps", "each step requires an id")
    ids = [step["id"] for step in steps]
    if len(set(ids)) != len(ids):
        raise DefinitionError("program.steps", "each step requires a unique id")
    ids = set(ids)
    if program["entry_step_id"] not in ids:
        raise DefinitionError("program.entry_step_id", "does not name a step")
    records, registry_revision = _registry_records(action_registry)
    if not isinstance(program.get("completion_policy"), dict) or not isinstance(program.get("failure_policy"), dict):
        raise DefinitionError("program", "completion_policy and failure_policy are required mappings")
    if program["completion_policy"].get("mode") not in {"all_steps", "explicit_action", "condition"}:
        raise DefinitionError("program.completion_policy.mode", "unknown completion mode")
    if program["failure_policy"].get("mode") not in {"stop_run", "request_intervention", "continue"}:
        raise DefinitionError("program.failure_policy.mode", "unknown failure mode")
    parameters = program.get("parameters", [])
    if not isinstance(parameters, list):
        raise DefinitionError("program.parameters", "must be a list")
    parameter_ids = [p.get("id") for p in parameters if isinstance(p, dict)]
    if len(parameter_ids) != len(parameters) or len(set(parameter_ids)) != len(parameter_ids):
        raise DefinitionError("program.parameters", "each parameter requires a unique id")
    for index, parameter in enumerate(parameters):
        if parameter.get("minimum") is not None and parameter.get("maximum") is not None and parameter["minimum"] > parameter["maximum"]:
            raise DefinitionError(f"program.parameters[{index}]", "minimum cannot exceed maximum")
    for si, step in enumerate(steps):
        for ci, condition in enumerate(step.get("exit_conditions", [])):
            _validate_condition(condition, f"program.steps[{si}].exit_conditions[{ci}]")
    for path, action in _actions(program):
        if not isinstance(action, dict) or not action.get("action_id"):
            raise DefinitionError(path, "trusted action_id is required")
        if not isinstance(action.get("action_id"), str) or not action.get("action_id"):
            raise DefinitionError(path, "trusted action_id is required")
        if not isinstance(action.get("action_version"), str) or not action.get("action_version"):
            raise DefinitionError(path, "action_version is required")
        record = records.get(action["action_id"])
        if record is None:
            raise DefinitionError(path + ".action_id", f"unknown trusted action {action['action_id']!r}")
        if action["action_version"] not in record.get("versions", []):
            raise DefinitionError(path + ".action_version", "version is not trusted for this action")
        if "parameters" in action and not isinstance(action["parameters"], dict):
            raise DefinitionError(path + ".parameters", "must be a mapping")
        forbidden = {"python", "module", "import", "shell", "source", "url", "expression"} & action.keys()
        if forbidden:
            raise DefinitionError(path, f"arbitrary execution field is forbidden: {sorted(forbidden)[0]}")
    for si, step in enumerate(steps):
        for ai, scheduled in enumerate(step.get("periodic_actions", [])):
            scheduled = _mapping(scheduled, f"program.steps[{si}].periodic_actions[{ai}]")
            trigger = _mapping(scheduled.get("trigger"), f"program.steps[{si}].periodic_actions[{ai}].trigger")
            kind = trigger.get("kind")
            if kind not in {"immediate", "elapsed_time", "fixed_interval", "absolute_time", "condition", "step_completion", "random_window", "on_demand"}:
                raise DefinitionError(f"program.steps[{si}].periodic_actions[{ai}].trigger.kind", "unknown trigger kind")
            if kind == "random_window":
                window = _mapping(trigger.get("random_window"), f"program.steps[{si}].periodic_actions[{ai}].trigger.random_window")
                if not isinstance(window.get("seed"), int) or not isinstance(window.get("algorithm_version"), str):
                    raise DefinitionError(f"program.steps[{si}].periodic_actions[{ai}].trigger.random_window", "requires integer seed and algorithm_version")
                earliest = _mapping(window.get("earliest"), f"program.steps[{si}].periodic_actions[{ai}].trigger.random_window.earliest")
                latest = _mapping(window.get("latest"), f"program.steps[{si}].periodic_actions[{ai}].trigger.random_window.latest")
                if not isinstance(earliest.get("value"), (int, float)) or not isinstance(latest.get("value"), (int, float)):
                    raise DefinitionError(f"program.steps[{si}].periodic_actions[{ai}].trigger.random_window", "earliest and latest require numeric values")
                if float(earliest["value"]) > float(latest["value"]):
                    raise DefinitionError(f"program.steps[{si}].periodic_actions[{ai}].trigger.random_window", "earliest cannot exceed latest")
            if kind == "condition":
                _validate_condition(trigger.get("condition"), f"program.steps[{si}].periodic_actions[{ai}].trigger.condition")
        for ti, transition in enumerate(step.get("transitions", [])):
            transition = _mapping(transition, f"program.steps[{si}].transitions[{ti}]")
            target = transition.get("target_step_id")
            if target not in ids:
                raise DefinitionError(f"program.steps[{si}].transitions[{ti}].target_step_id", "unknown step")
            _validate_condition(transition.get("condition"), f"program.steps[{si}].transitions[{ti}].condition")
    plan = definition.get("validation_plan")
    if plan is not None:
        plan = _mapping(plan, "validation_plan")
        if not isinstance(plan.get("criteria"), list) or not plan["criteria"]:
            raise DefinitionError("validation_plan.criteria", "requires a non-empty list")
        for index, criterion in enumerate(plan["criteria"]):
            criterion = _mapping(criterion, f"validation_plan.criteria[{index}]")
            if criterion.get("comparator") not in {"eq", "lt", "lte", "gt", "gte", "between"}:
                raise DefinitionError(f"validation_plan.criteria[{index}].comparator", "unknown comparator")
            if not isinstance(criterion.get("metric"), str) or not criterion.get("metric"):
                raise DefinitionError(f"validation_plan.criteria[{index}].metric", "is required")
            if criterion["comparator"] == "between" and (criterion.get("lower_bound") is None or criterion.get("upper_bound") is None):
                raise DefinitionError(f"validation_plan.criteria[{index}]", "between requires lower_bound and upper_bound")
    return registry_revision


def compile_program(program: dict[str, Any], *, action_registry: Any = None) -> dict[str, Any]:
    """Compile an :class:`ExperimentProgram` into the edge state-machine plan.

    The plan deliberately contains only declarative action invocations.  The
    edge may schedule and journal these identities, but it cannot resolve an
    import path or execute source supplied by a definition.
    """
    wrapper = {
        "id": "program",
        "purpose": "research",
        "program": program,
    }
    _validate(wrapper, action_registry)
    states: dict[str, Any] = {}
    for step in program["steps"]:
        state = {"entry_actions": deepcopy(step.get("entry_actions", [])),
                 "periodic_actions": deepcopy(step.get("periodic_actions", [])),
                 "exit_conditions": deepcopy(step.get("exit_conditions", [])),
                 "transitions": deepcopy(step.get("transitions", []))}
        for field in ("timeout", "intervention_policy"):
            if field in step:
                state[field] = deepcopy(step[field])
        states[step["id"]] = state
    return {
        "version": program["version"],
        "initial_state": program["entry_step_id"],
        "states": states,
        "completion_policy": deepcopy(program["completion_policy"]),
        "failure_policy": deepcopy(program["failure_policy"]),
        "parameters": deepcopy(program.get("parameters", [])),
    }


def compile_definition(definition: dict[str, Any], *, action_registry: Any = None) -> dict[str, Any]:
    """Return a canonical :class:`ExperimentBundle` representation.

    ``resolved_definition`` is the immutable source snapshot; ``execution_plan``
    is the separate edge-facing projection compiled from its program.
    """
    document = deepcopy(definition)
    registry_revision = _validate(document, action_registry)
    program = document["program"]
    # Resolve random windows without wall-clock data. The seed and constraints
    # remain in the bundle, and the resolved offset is reproducible.
    for step in program.get("steps", []):
        for scheduled in step.get("periodic_actions", []):
            trigger = scheduled.get("trigger", {})
            if trigger.get("kind") == "random_window":
                window = trigger.get("random_window", trigger)
                seed = window["seed"]
                earliest = float(window["earliest"]["value"])
                latest = float(window["latest"]["value"])
                # Integer arithmetic avoids platform-dependent random floats.
                scheduled["resolved_offset"] = earliest + (latest - earliest) * int(_digest({"seed": seed, "algorithm_version": window["algorithm_version"]})[:16], 16) / 0xFFFFFFFFFFFFFFFF
    execution_plan = compile_program(program, action_registry=action_registry)
    bundle = {
        "definition_id": document["id"],
        "definition_revision": document.get("revision"),
        "purpose": document["purpose"],
        "resolved_definition": document,
        "execution_plan": execution_plan,
        "action_registry_revision": registry_revision,
        "schema_version": SCHEMA_VERSION,
        "execution_mode": "declarative_state_machine",
    }
    bundle["digest"] = _digest(bundle)
    return bundle
