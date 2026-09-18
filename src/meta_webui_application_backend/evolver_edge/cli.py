"""Local operator CLI over the same durable edge domain store."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .bundle import resolve_bundle
from .domain import plan_calibrated_dispense, validate_bounded_operation
from .store import EdgeStore, EdgeStoreError, canonical_digest
from .sync import SyncClient
from .install import inspect_installation
from .lifecycle import plan_lifecycle
from .update import ComposeUpdateBackend, UpdateManager, UpdatePolicy, record_installed_release
from .doctor import doctor_report
from .operator import (DEFAULT_SOCKET as DEFAULT_OPERATOR_SOCKET, OperatorClient,
                       OperatorError, OperatorProtocolError, OperatorUnavailable,
                       request as operator_request)
from .workflow_cli import WorkflowCLI, ScenarioRegistry, parse_parameters, production_host, ScenarioHost
from .workflow_host import (ActionAvailability, Availability, HostContext,
                             ProcedureActionInvoker, TargetKind, operator_safe_stop_authority,
                             resolve_target, TRUSTED_ACTIONS)
from evolver_procedure_runtime import ActionRef


class CommandRegistryError(ValueError):
    """The CLI command is not part of the frozen controller contract."""


class CommandMode(str, Enum):
    LIVE = "LIVE"
    LOCAL = "LOCAL"
    MAINTENANCE = "MAINTENANCE"


@dataclass(frozen=True)
class CommandSpec:
    mode: CommandMode
    disposition: str = "execute"
    delegate: str | None = None


_COMMAND_REGISTRY: dict[str, CommandSpec] = {
    "status": CommandSpec(CommandMode.LIVE),
    "binding": CommandSpec(CommandMode.LIVE),
    "doctor": CommandSpec(CommandMode.LIVE),
    "runs": CommandSpec(CommandMode.LIVE),
    "controllers": CommandSpec(CommandMode.LIVE),
    "instruments": CommandSpec(CommandMode.LIVE),
    "instrument.show": CommandSpec(CommandMode.LIVE),
    "instrument.list": CommandSpec(CommandMode.LIVE),
    "instrument.status": CommandSpec(CommandMode.LIVE),
    "instrument.capabilities": CommandSpec(CommandMode.LIVE),
    "instrument.components": CommandSpec(CommandMode.LIVE),
    "instrument.sensors.list": CommandSpec(CommandMode.LIVE),
    "instrument.sensors.read": CommandSpec(CommandMode.LIVE),
    "instrument.telemetry.latest": CommandSpec(CommandMode.LIVE),
    "instrument.telemetry.list": CommandSpec(CommandMode.LIVE),
    "capabilities": CommandSpec(CommandMode.LIVE),
    "action.list": CommandSpec(CommandMode.LIVE),
    "action.show": CommandSpec(CommandMode.LIVE),
    "action.availability": CommandSpec(CommandMode.LIVE),
    "action.preflight": CommandSpec(CommandMode.LIVE),
    "action.run": CommandSpec(CommandMode.LIVE),
    "run.show": CommandSpec(CommandMode.LIVE),
    "run.events": CommandSpec(CommandMode.LIVE),
    "run.telemetry": CommandSpec(CommandMode.LIVE),
    "run.pause": CommandSpec(CommandMode.LIVE),
    "run.resume": CommandSpec(CommandMode.LIVE),
    "run.stop": CommandSpec(CommandMode.LIVE),
    "calibration.artifacts": CommandSpec(CommandMode.LIVE),
    "calibration.preflight": CommandSpec(CommandMode.LIVE),
    "hardware.lease.acquire": CommandSpec(CommandMode.LIVE),
    "hardware.lease.status": CommandSpec(CommandMode.LIVE),
    "hardware.lease.release": CommandSpec(CommandMode.LIVE),
    "hardware.layout": CommandSpec(CommandMode.LIVE),
    "hardware.provision-identity": CommandSpec(CommandMode.LIVE),
    "hardware.discover": CommandSpec(CommandMode.LIVE),
    "hardware.protocol-test": CommandSpec(CommandMode.LIVE),
    "hardware.safe-stop": CommandSpec(CommandMode.LIVE),
    "hardware.actuate": CommandSpec(CommandMode.LIVE),
    "hardware.quarantine-command": CommandSpec(CommandMode.MAINTENANCE, "rejected"),
    "update.status": CommandSpec(CommandMode.MAINTENANCE, "delegated", "controller-service"),
    "update.check": CommandSpec(CommandMode.MAINTENANCE, "delegated", "controller-service"),
    "update.apply": CommandSpec(CommandMode.MAINTENANCE, "delegated", "controller-service"),
    "enroll": CommandSpec(CommandMode.LOCAL),
    "lifecycle-plan": CommandSpec(CommandMode.LOCAL),
    "record-installed-release": CommandSpec(CommandMode.MAINTENANCE, "rejected"),
    "export-state": CommandSpec(CommandMode.LOCAL),
    "import-state": CommandSpec(CommandMode.LOCAL),
    "recovery": CommandSpec(CommandMode.LOCAL),
    "sync": CommandSpec(CommandMode.LOCAL),
    "tui": CommandSpec(CommandMode.LOCAL),
    "simulator": CommandSpec(CommandMode.LOCAL),
    "firmware": CommandSpec(CommandMode.MAINTENANCE, "delegated", "hardware-service"),
    "validation": CommandSpec(CommandMode.LOCAL),
    "dispense": CommandSpec(CommandMode.LOCAL),
}


def command_spec(command: str) -> CommandSpec:
    try:
        return _COMMAND_REGISTRY[command]
    except KeyError as error:
        raise CommandRegistryError(f"command is not in the frozen registry: {command}") from error


def maintenance_disposition(command: str) -> dict[str, str]:
    spec = command_spec(command)
    if spec.mode is not CommandMode.MAINTENANCE:
        raise CommandRegistryError(f"command is not maintenance: {command}")
    result = {"mode": spec.mode.value, "disposition": spec.disposition}
    if spec.delegate is not None:
        result["delegate"] = spec.delegate
    return result


def _live_request(args: argparse.Namespace) -> tuple[str, dict[str, Any]] | None:
    """Translate a frozen LIVE CLI spelling into one typed operator request."""
    key = args.command
    if args.command == "run":
        key = f"run.{args.run_command}"
    elif args.command == "instrument":
        key = _instrument_command_key(args)
    elif args.command == "calibration":
        key = f"calibration.{args.calibration_command}"
    elif args.command == "hardware":
        key = f"hardware.{args.hardware_command}"
        if args.hardware_command == "lease":
            key = f"hardware.lease.{args.lease_command}"
    elif args.command == "update":
        key = f"update.{args.update_command}"
    spec = command_spec(key)
    if spec.mode is not CommandMode.LIVE:
        return None
    if args.command in {"status", "binding", "runs", "instruments", "doctor"}:
        return args.command, {}
    if args.command == "controllers":
        return "status", {"view": "controllers"}
    if args.command == "capabilities":
        return "capabilities", {}
    if args.command == "instrument":
        if args.instrument_command == "list":
            return "instruments", {}
        if args.instrument_command in {"show", "capabilities", "components"}:
            return "instrument", {"instrument_id": args.instrument_id}
        if args.instrument_command == "status":
            return "instrument", {"action": "status", "instrument_id": args.instrument_id}
        if args.instrument_command == "telemetry":
            params = {"action": f"telemetry_{args.telemetry_command}", "instrument_id": args.instrument_id}
            if args.limit is not None:
                params["limit"] = args.limit
            return "instrument", params
        if args.instrument_command == "sensors" and args.sensors_command == "read":
            return "instrument", {"action": "sensor_read", "instrument_id": args.instrument_id,
                                   "sensor": args.sensor, "channel": args.channel}
        return "instrument", {"instrument_id": args.instrument_id}
    if args.command == "calibration":
        if args.calibration_command == "artifacts":
            return "calibration", {"action": "artifacts", "instrument_id": args.instrument_id}
        return "calibration", {"action": "preflight", "references": json.loads(args.references),
                                "requirements": json.loads(args.requirements)}
    if args.command == "run":
        params: dict[str, Any] = {"action": args.run_command, "run_id": args.run_id}
        if args.run_command in {"pause", "resume", "stop"}:
            params["based_on_revision"] = args.based_on_revision
        return "run", params
    if args.command == "hardware":
        if args.hardware_command == "lease":
            params = {"action": args.lease_command, "operator": getattr(args, "operator", None)}
            if args.lease_command == "acquire":
                params["ttl_seconds"] = args.ttl_seconds
            return "hardware_lease", params
        if args.hardware_command == "layout":
            return "hardware_layout", {"target_identity": args.target, "operator": args.operator,
                                        "positions": {str(args.channel): {"physical_side": args.physical_side,
                                                                            "method": args.method}}}
        if args.hardware_command == "provision-identity":
            return "hardware_provision_identity", {"device_id": args.device_id, "owner_id": args.owner_id,
                                                     "operator": args.operator, "physical": args.physical}
        if args.hardware_command == "discover":
            return "hardware", {"operation": "discover"}
        if args.hardware_command == "protocol-test":
            return "hardware", {"operation": "protocol_test"}
        if args.hardware_command == "safe-stop":
            return "hardware", {"operation": "safe_stop", "physical": args.physical,
                                 "operator": args.operator}
        if args.hardware_command == "actuate":
            parameters = {"channel": args.channel}
            if args.operation == "set_output":
                parameters.update(output="od_led", level=args.level)
            elif args.operation == "pulse_pump":
                parameters.update(duration_ms=args.duration_ms)
            else:
                parameters.update(duration_ms=args.duration_ms, level=args.level)
            return "hardware", {"operation": "hardware_command", "operation_name": args.operation,
                                 "target_identity": args.target, "parameters": parameters,
                                 "physical": args.physical, "operator": args.operator,
                                 "lease_token": args.lease_token, "lease_owner": args.operator,
                                 "controller_generation": args.controller_generation}
    raise CommandRegistryError(f"LIVE command has no operator translation: {key}")


def _root(value: str | None) -> Path:
    return Path(value or os.environ.get("EVOLVER_STATE_ROOT", "/var/lib/evolver-controller"))


def _instrument_command_key(args: argparse.Namespace) -> str:
    command = args.instrument_command
    if command == "sensors":
        return f"instrument.sensors.{args.sensors_command}"
    if command == "telemetry":
        return f"instrument.telemetry.{args.telemetry_command}"
    return f"instrument.{command}"


_ACTION_DESCRIPTIONS = {
    "set_temperature": "Set a temperature controller target.",
    "set_stirring": "Set a stirring controller target.",
    "pulse_pump": "Dispense a bounded pump pulse.",
    "run_pump": "Run a pump for a bounded duration.",
    "stop_actuator": "Stop an actuator through safe-stop authority.",
    "capture_measurement": "Capture a read-only measurement.",
    "request_observation": "Request a read-only observation.",
    "wait": "Wait in the local workflow runtime.",
    "evaluate_criteria": "Evaluate local workflow criteria.",
    "emit_marker": "Emit a local workflow marker.",
    "start_activity": "Start a workflow activity.",
    "stop_activity": "Stop a workflow activity.",
    "complete_run": "Complete a workflow run.",
    "fail_run": "Fail a workflow run.",
}


def _availability_json(availability: ActionAvailability) -> dict[str, Any]:
    return {"action": availability.action, "version": availability.version,
            "classification": availability.classification.value, "reason": availability.reason,
            "provenance": dict(availability.provenance), "route": availability.route}


def _action_cli(args: argparse.Namespace) -> int:
    action_id = getattr(args, "action_id", None)
    if args.action_command == "list" and args.target is None:
        _emit({"actions": [{"id": item, "version": "1", "description": _ACTION_DESCRIPTIONS[item]}
                            for item in TRUSTED_ACTIONS]})
        return 0
    if action_id is None:
        action_id = ""
    if action_id not in TRUSTED_ACTIONS:
        _emit({"error": f"unknown trusted action: {action_id}"})
        return 2
    if args.action_command == "show" and args.target is None:
        _emit({"id": action_id, "version": "1", "description": _ACTION_DESCRIPTIONS[action_id]})
        return 0
    if args.target is None:
        _emit({"error": "--target is required for action availability"})
        return 2
    client = OperatorClient(args.operator_socket)
    target = resolve_target(client, args.target, kind=TargetKind.SIMULATOR if args.simulator else TargetKind.PHYSICAL)
    operator = getattr(args, "operator", None)
    context = HostContext(operator=operator, lease_token=getattr(args, "lease_token", None),
                          lease_owner=operator, controller_generation=getattr(args, "controller_generation", None),
                          physical=getattr(args, "physical", False), target_identity=args.target)
    invoker = ProcedureActionInvoker(client, target, context=context,
                                     safe_stop_authority=operator_safe_stop_authority(client))
    action = ActionRef(action_id, 1)
    availability = invoker.availability(action)
    if args.action_command == "list":
        _emit({"target": args.target, "actions": [
            {"id": item, "version": "1", "description": _ACTION_DESCRIPTIONS[item],
             "availability": _availability_json(invoker.availability(ActionRef(item, 1)))}
            for item in TRUSTED_ACTIONS]})
        return 0
    if args.action_command == "show":
        _emit({"id": action_id, "version": "1", "description": _ACTION_DESCRIPTIONS[action_id],
               "availability": _availability_json(availability)})
        return 0
    if args.action_command == "availability":
        _emit(_availability_json(availability))
        return 0
    try:
        parameters = json.loads(args.parameters)
        if not isinstance(parameters, dict):
            raise ValueError("--parameters must be a JSON object")
        if args.action_command == "preflight":
            invoker.preflight(action, parameters)
            _emit({"action": action_id, "target": args.target, "state": "preflighted",
                   "actions_invoked": 0, "availability": _availability_json(availability)})
            return 0
        invocation = invoker.invoke(action, parameters)
        result = invoker.poll(invocation)
        _emit({"action": action_id, "target": args.target, "invocation_id": invocation.token,
               "state": "succeeded" if result.succeeded else "failed",
               "result": result.value if result.succeeded else {"error": result.error},
               "availability": _availability_json(availability)})
        return 0 if result.succeeded else 2
    except (OperatorError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        _emit({"action": action_id, "target": args.target, "state": "failed", "error": str(error),
               "availability": _availability_json(availability)})
        return 2


_SENSITIVE_KEY_PARTS = ("credential", "password", "secret", "token", "private_key", "api_key", "authorization")


def _redact(value: Any) -> Any:
    """Redact sensitive fields structurally before operator serialization."""
    if isinstance(value, dict):
        return {key: ("<redacted>" if any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS)
                      else _redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


def _emit(value: Any) -> None:
    print(json.dumps(_redact(value), indent=2, sort_keys=True, default=str))


def _operator_exit_code(error: Exception) -> int:
    return 69 if isinstance(error, OperatorUnavailable) else 64


def _offline_state_path(state_root: Path) -> Path:
    database = state_root / "edge.sqlite3"
    if not database.is_file():
        raise EdgeStoreError(f"offline state is missing at {database}; provide a valid --state-root")
    return database


def _compatibility_argv(argv: list[str]) -> list[str]:
    """Translate grouped operator spellings to the existing local actions.

    The edge CLI's flat commands are the implementation contract.  These
    aliases are presentation compatibility only: they never add a transport,
    central action, or physical operation.  Longest prefixes must be checked
    first so ``local run list`` does not become ``run list`` accidentally.
    """
    aliases: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
        (("local", "run", "list"), ("runs",)),
        (("local", "instrument", "list"), ("instruments",)),
        (("local", "instrument", "show"), ("instrument", "show")),
        (("local", "runs"), ("runs",)),
        (("local", "run"), ("run",)),
        (("local", "diagnostics"), ("doctor",)),
        (("local", "diagnostic"), ("doctor",)),
        (("control",), ("hardware",)),
        (("local", "status"), ("status",)),
        (("local", "server"), ("status",)),
        (("local", "binding"), ("binding",)),
        (("local", "recovery"), ("recovery",)),
        (("local", "release"), ("update",)),
        (("server", "status"), ("status",)),
        (("server", "binding"), ("binding",)),
        (("server",), ("status",)),
        (("binding", "show"), ("binding",)),
        (("binding", "status"), ("binding",)),
        (("recovery", "show"), ("recovery",)),
        (("recovery", "status"), ("recovery",)),
        (("release", "status"), ("update", "status")),
        (("release", "check"), ("update", "check")),
        (("release", "apply"), ("update", "apply")),
        (("diagnostics",), ("doctor",)),
        (("diagnostic",), ("doctor",)),
        (("read-only", "diagnostics"), ("doctor",)),
        (("runs", "list"), ("runs",)),
        (("run", "list"), ("runs",)),
    )
    for source, target in aliases:
        if tuple(argv[:len(source)]) == source:
            return [*target, *argv[len(source):]]
    return argv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evoctl", description="eVOLVER controller local operator CLI")
    parser.add_argument("--state-root", help="persistent controller state directory")
    parser.add_argument("--offline", action="store_true",
                        help="read directly from the durable store without contacting the operator service")
    parser.add_argument("--operator-socket", default=os.environ.get("EVOLVER_OPERATOR_SOCKET", DEFAULT_OPERATOR_SOCKET),
                        help="private Unix socket for the local read-only operator service")
    commands = parser.add_subparsers(dest="command", required=True)
    enroll = commands.add_parser("enroll"); enroll.add_argument("--server", required=True); enroll.add_argument("--token", required=True)
    enroll.add_argument("--mode", choices=("repair", "live_handoff", "forced_adoption"),
                        help="required when this controller already has a binding")
    enroll.add_argument("--confirm-forced-adoption", action="store_true",
                        help="explicit operator acknowledgement for recovery takeover")
    commands.add_parser("status"); commands.add_parser("runs"); commands.add_parser("binding"); commands.add_parser("recovery")
    commands.add_parser("capabilities", help="inspect typed operator protocol capabilities")
    release = commands.add_parser("record-installed-release", help=argparse.SUPPRESS)
    release.add_argument("release")
    lifecycle = commands.add_parser("lifecycle-plan", help="inspect and plan a lifecycle operation without mutating the host")
    lifecycle.add_argument("--operation", choices=("install", "repair", "update", "clean-reinstall", "uninstall", "handoff", "forced-adoption", "factory-reset"), required=True)
    lifecycle.add_argument("--server")
    lifecycle.add_argument("--release")
    lifecycle.add_argument("--current-state", type=Path,
                           help="JSON inspection snapshot supplied by an installer")
    lifecycle.add_argument("--confirmed", action="store_true")
    export_state = commands.add_parser("export-state", help="export credential-free recovery data to recovery.tar.zst")
    export_state.add_argument("archive", nargs="?", default="recovery.tar.zst")
    import_state = commands.add_parser("import-state", help="import recovery data into a fresh local state root")
    import_state.add_argument("archive")
    commands.add_parser("doctor", help="run read-only local controller and central health checks")
    sync = commands.add_parser("sync"); sync.add_argument("--loop", action="store_true"); sync.add_argument("--interval", type=float, default=10.0)
    run = commands.add_parser("run"); run_sub = run.add_subparsers(dest="run_command", required=True)
    for action in ("show", "pause", "resume", "stop", "events", "telemetry"):
        item = run_sub.add_parser(action); item.add_argument("run_id")
        if action in {"pause", "resume", "stop"}: item.add_argument("--based-on-revision", type=int)
    # Inventory is durable edge-domain data; simulator and hardware adapters
    # merely populate the same contract.
    commands.add_parser("controllers"); commands.add_parser("instruments")
    workflow = commands.add_parser("workflow", help="browse and run trusted workflows")
    workflow_sub = workflow.add_subparsers(dest="workflow_command", required=True)
    workflow_list = workflow_sub.add_parser("list")
    workflow_list.add_argument("--search", default="")
    workflow_show = workflow_sub.add_parser("show")
    workflow_show.add_argument("workflow_id")
    for name in ("preflight", "run"):
        item = workflow_sub.add_parser(name)
        item.add_argument("workflow_id")
        item.add_argument("--parameter", action="append", default=[], metavar="NAME=VALUE")
        item.add_argument("--target", default="scenario-1")
        item.add_argument("--simulator", action="store_true")
        item.add_argument("--jsonl", action="store_true")
        item.add_argument("--scenario", choices=ScenarioRegistry().names())
        item.add_argument("--operator")
        item.add_argument("--lease-token")
        item.add_argument("--physical", action="store_true")
    instrument = commands.add_parser("instrument", help="inspect and operate one instrument")
    instrument_sub = instrument.add_subparsers(dest="instrument_command", required=True)
    item = instrument_sub.add_parser("list")
    for name in ("show", "status", "capabilities", "components"):
        item = instrument_sub.add_parser(name); item.add_argument("instrument_id")
    sensors = instrument_sub.add_parser("sensors")
    sensors_sub = sensors.add_subparsers(dest="sensors_command", required=True)
    sensor_list = sensors_sub.add_parser("list"); sensor_list.add_argument("instrument_id")
    sensor_read = sensors_sub.add_parser("read")
    sensor_read.add_argument("instrument_id"); sensor_read.add_argument("sensor", choices=("temperature", "od"))
    sensor_read.add_argument("--channel", type=int, required=True)
    telemetry = instrument_sub.add_parser("telemetry")
    telemetry_sub = telemetry.add_subparsers(dest="telemetry_command", required=True)
    for name in ("latest", "list"):
        item = telemetry_sub.add_parser(name); item.add_argument("instrument_id"); item.add_argument("--limit", type=int)
    action = commands.add_parser("action", help="inspect or invoke trusted workflow actions")
    action_sub = action.add_subparsers(dest="action_command", required=True)
    action_list = action_sub.add_parser("list"); action_list.add_argument("--target")
    action_list.add_argument("--simulator", action="store_true")
    action_show = action_sub.add_parser("show"); action_show.add_argument("action_id"); action_show.add_argument("--target")
    action_show.add_argument("--simulator", action="store_true")
    for name in ("availability", "preflight", "run"):
        item = action_sub.add_parser(name)
        item.add_argument("action_id"); item.add_argument("--target", required=True)
        item.add_argument("--parameters", default="{}", help="bounded action parameters as a JSON object")
        item.add_argument("--operator"); item.add_argument("--lease-token")
        item.add_argument("--controller-generation", type=int); item.add_argument("--physical", action="store_true")
        item.add_argument("--simulator", action="store_true")
    calibration = commands.add_parser("calibration", help="inspect stored calibration evidence")
    calibration_sub = calibration.add_subparsers(dest="calibration_command", required=True)
    artifacts = calibration_sub.add_parser("artifacts")
    artifacts.add_argument("--instrument-id")
    preflight = calibration_sub.add_parser("preflight")
    preflight.add_argument("references", help="JSON calibration references")
    preflight.add_argument("--requirements", default="[]", help="JSON calibration requirements")
    dispense = commands.add_parser("dispense", help="plan a calibrated dispense without actuating hardware")
    dispense.add_argument("--artifact", required=True, type=Path, help="JSON pump calibration artifact")
    dispense.add_argument("--volume-ul", required=True, type=float)
    dispense.add_argument("--channel", required=True, type=int)
    dispense.add_argument("--maximum-duration-ms", type=int, default=1000)
    validation = commands.add_parser("validation", help="validate a bounded operator operation")
    validation.add_argument("operation", choices=("safe_stop", "pulse_pump", "set_stir", "pulse_heater"))
    validation.add_argument("--parameters", default="{}", help="JSON operation parameters")
    tui = commands.add_parser("tui", help="run the local configured Textual operator UI")
    tui.add_argument("--page", choices=("overview", "controllers", "instruments", "runs", "recovery", "maintenance"), default="overview")
    tui.add_argument("--workflow", action="store_true", help="open the multi-tab Workflow workspace")
    update = commands.add_parser("update", help="inspect or apply a local controller software release")
    update_sub = update.add_subparsers(dest="update_command", required=True)
    update_sub.add_parser("status")
    check = update_sub.add_parser("check"); check.add_argument("release")
    apply = update_sub.add_parser("apply"); apply.add_argument("release")
    simulator = commands.add_parser("simulator"); sim_sub = simulator.add_subparsers(dest="simulator_command", required=True)
    start = sim_sub.add_parser("start"); start.add_argument("--instruments", type=int, default=1)
    create = sim_sub.add_parser("create-run", help="create a safe simulated run from a declarative plan")
    create.add_argument("run_id")
    create.add_argument("--bundle-id", required=True)
    create.add_argument("--execution-plan", required=True,
                        help="JSON declarative state-machine plan; it is stored in an immutable ExperimentBundle")
    create.add_argument("--instruments", type=int, default=1)
    tick = sim_sub.add_parser("tick", help="advance a durable simulated run without network or hardware")
    tick.add_argument("run_id")
    tick.add_argument("--ticks", type=int, default=1)
    tick.add_argument("--instruments", type=int, default=1)
    firmware = commands.add_parser("firmware", help="verify or developer-build the pinned firmware")
    firmware.add_argument("action", choices=("build", "upload", "verify", "preflight"))
    firmware.add_argument("--port")
    firmware.add_argument("--artifact", type=Path)
    firmware.add_argument("--physical", action="store_true")
    firmware.add_argument("--operator")
    firmware.add_argument("--sha256")
    hardware = commands.add_parser("hardware", help="safe hardware-service diagnostics and gated maintenance")
    hardware_sub = hardware.add_subparsers(dest="hardware_command", required=True)
    hardware_sub.add_parser("discover")
    hardware_sub.add_parser("protocol-test")
    quarantine = hardware_sub.add_parser("quarantine-command", help="DB-only resolution of one interrupted command")
    quarantine.add_argument("command_id"); quarantine.add_argument("--operator", required=True)
    quarantine.add_argument("--reason-kind", required=True)
    quarantine.add_argument("--requested-device"); quarantine.add_argument("--requested-owner")
    quarantine.add_argument("--observed-device"); quarantine.add_argument("--observed-owner")
    provision = hardware_sub.add_parser("provision-identity", help="provision a blank device identity")
    provision.add_argument("--device-id", required=True); provision.add_argument("--owner-id", required=True)
    provision.add_argument("--operator", required=True); provision.add_argument("--physical", action="store_true")
    actuator = hardware_sub.add_parser("actuate", help="one bounded maintenance command; physical opt-in required")
    actuator.add_argument("operation", choices=("set_output", "pulse_pump", "set_stir", "pulse_heater"))
    actuator.add_argument("--target", required=True)
    actuator.add_argument("--channel", type=int, default=0)
    actuator.add_argument("--duration-ms", type=int)
    actuator.add_argument("--level", type=int)
    actuator.add_argument("--physical", action="store_true")
    actuator.add_argument("--operator", help="audited operator attribution")
    actuator.add_argument("--lease-token")
    actuator.add_argument("--controller-generation", type=int,
                          help="controller generation asserted by the active lease")
    safe_stop = hardware_sub.add_parser("safe-stop", help="stop all registered physical outputs")
    safe_stop.add_argument("--physical", action="store_true", required=True)
    safe_stop.add_argument("--operator", required=True, help="audited operator attribution")
    lease = hardware_sub.add_parser("lease", help="bounded local commissioning lease")
    lease_sub = lease.add_subparsers(dest="lease_command", required=True)
    acquire = lease_sub.add_parser("acquire"); acquire.add_argument("--operator", required=True); acquire.add_argument("--ttl-seconds", type=int, default=900)
    lease_sub.add_parser("status")
    release = lease_sub.add_parser("release"); release.add_argument("--operator", required=True)
    layout = hardware_sub.add_parser("layout", help="record physical vial orientation evidence")
    layout.add_argument("--target", required=True); layout.add_argument("--operator", required=True)
    layout.add_argument("--channel", type=int, required=True); layout.add_argument("--physical-side", choices=("left", "right", "unconfirmed"), required=True)
    layout.add_argument("--method", choices=("operator_observed", "inferred_two_position_profile"), required=True)
    hardware.add_argument("--socket", default=os.environ.get("EVOLVER_HARDWARE_SOCKET", "/run/evolver-controller/hardware.sock"))
    hardware.add_argument("--timeout", type=float, help="bounded hardware IPC timeout in seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_arguments = sys.argv[1:] if argv is None else list(argv)
    # Global options precede grouped aliases in the documented shell syntax.
    # Normalize only the command portion so ``--state-root PATH server`` is
    # equivalent to ``server --state-root PATH`` without changing parsing.
    prefix: list[str] = []
    while raw_arguments:
        if raw_arguments[0] == "--offline":
            prefix.append(raw_arguments.pop(0))
        elif raw_arguments[0] in {"--state-root", "--operator-socket"} and len(raw_arguments) > 1:
            prefix.extend(raw_arguments[:2])
            raw_arguments = raw_arguments[2:]
        else:
            break
    arguments = [*prefix, *_compatibility_argv(raw_arguments)]
    args = build_parser().parse_args(arguments)
    if args.command == "workflow":
        try:
            parameters = parse_parameters(args.parameter) if args.workflow_command in {"preflight", "run"} else {}
            if args.workflow_command == "list" or args.workflow_command == "show":
                # Metadata commands intentionally require no operator socket.
                root = Path(__file__).resolve().parents[5]
                from evolver_procedure_runtime import WorkflowLibrary
                library = WorkflowLibrary.from_directories([root / "workflows" / "calibration"])
                host = ScenarioHost(tuple(library.list()))
                if args.workflow_command == "list" and args.search:
                    host.workflows = WorkflowLibrary(host.search_workflows(args.search))
                renderer = WorkflowCLI(host, output=sys.stdout)
                return renderer.list_workflows() if args.workflow_command == "list" else renderer.show_workflow(args.workflow_id)
            if args.scenario:
                host = ScenarioRegistry().host(args.scenario)
            else:
                context = HostContext(operator=args.operator, lease_token=args.lease_token, lease_owner=args.operator,
                                      physical=args.physical, target_identity=args.target)
                host = production_host(OperatorClient(args.operator_socket), target=args.target,
                                        simulator=args.simulator, context=context)
            cli = WorkflowCLI(host, output=sys.stdout, jsonl=args.jsonl)
            if args.workflow_command == "preflight":
                return cli.preflight(args.workflow_id, parameters)
            return cli.run(args.workflow_id, parameters)
        except (KeyError, OSError, TypeError, ValueError, OperatorError, json.JSONDecodeError) as error:
            print(f"workflow_error: {error}", file=sys.stderr)
            return 2
    if args.command == "action":
        try:
            return _action_cli(args)
        except (OperatorUnavailable, OperatorProtocolError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            if isinstance(error, OperatorError):
                print(f"{error.kind}: {error}", file=sys.stderr)
                return _operator_exit_code(error)
            print(f"action_error: {error}", file=sys.stderr)
            return 2
    live_request = None if args.offline else _live_request(args)
    if live_request is not None:
        operation, params = live_request
        try:
            result = operator_request(operation, args.operator_socket, params=params)
            if args.command == "controllers":
                result = [{**result["controller"], "binding": result["binding"],
                           "inventory": operator_request("instruments", args.operator_socket, params={})}]
            elif args.command == "instrument":
                if args.instrument_command == "capabilities":
                    result = {"instrument_id": args.instrument_id, "capabilities": result.get("capabilities", {})}
                elif args.instrument_command == "components":
                    result = {"instrument_id": args.instrument_id,
                              "components": result.get("components", result.get("vial_positions", []))}
                elif args.instrument_command == "sensors" and args.sensors_command == "list":
                    capabilities = result.get("capabilities", {})
                    result = {"instrument_id": args.instrument_id,
                              "sensors": result.get("sensors", capabilities.get("sensors", []))}
            _emit(result)
            if (args.command == "hardware" and args.hardware_command == "safe-stop"
                    and isinstance(result, dict) and result.get("request_accepted") is False):
                return 2
            return 0
        except (OperatorUnavailable, OperatorProtocolError, EdgeStoreError, ValueError, TypeError, json.JSONDecodeError) as error:
            print(f"{getattr(error, 'kind', 'operator_error')}: {error}", file=sys.stderr)
            return _operator_exit_code(error) if isinstance(error, OperatorError) else 64
    # Every non-LIVE operation must declare its local or maintenance behavior
    # before the local store context is entered.  This prevents new commands
    # from silently inheriting the old EdgeStore fallback.
    command_key = args.command
    if args.command == "run":
        command_key = f"run.{args.run_command}"
    elif args.command == "instrument":
        command_key = _instrument_command_key(args)
    elif args.command == "calibration":
        command_key = f"calibration.{args.calibration_command}"
    elif args.command == "update":
        command_key = f"update.{args.update_command}"
    elif args.command == "hardware":
        command_key = f"hardware.{args.hardware_command}"
        if args.hardware_command == "lease":
            command_key = f"hardware.lease.{args.lease_command}"
    spec = command_spec(command_key)
    if spec.mode is CommandMode.MAINTENANCE and not (
            args.command == "hardware" and args.hardware_command in {"discover", "protocol-test", "safe-stop", "actuate"}):
        _emit(maintenance_disposition(command_key))
        return 2 if spec.disposition == "rejected" else 0
    live_operations = {"status", "binding", "runs", "instruments", "doctor"}
    offline_read = args.offline
    # Live read models have one control plane. A failed socket is reported to
    # the operator; it is never converted into a direct SQLite read.
    if not args.offline and args.command in live_operations:
        try:
            result = operator_request(args.command, args.operator_socket, params={})
            _emit(result)
            if args.command == "doctor" and result.get("summary", {}).get("FAIL"):
                return 2
            return 0
        except (OperatorUnavailable, OperatorProtocolError) as error:
            print(f"{error.kind}: {error}", file=sys.stderr)
            return _operator_exit_code(error)
    if not args.offline and args.command == "hardware":
        if args.hardware_command == "discover":
            params = {"operation": "discover"}
        elif args.hardware_command == "protocol-test":
            params = {"operation": "protocol_test"}
        elif args.hardware_command == "safe-stop":
            params = {"operation": "safe_stop", "physical": args.physical,
                      "operator": args.operator}
        elif args.hardware_command == "actuate":
            parameters = {"channel": args.channel}
            if args.operation == "set_output":
                parameters.update(output="od_led", level=args.level)
            elif args.operation == "pulse_pump":
                parameters.update(duration_ms=args.duration_ms)
            else:
                parameters.update(duration_ms=args.duration_ms, level=args.level)
            params = {"operation": "hardware_command", "operation_name": args.operation,
                      "target_identity": args.target, "parameters": parameters,
                      "physical": args.physical, "operator": args.operator,
                      "lease_token": args.lease_token, "lease_owner": args.operator,
                      "controller_generation": args.controller_generation}
        else:
            params = {"operation": args.hardware_command}
        try:
            _emit(operator_request("hardware", args.operator_socket, params=params))
            return 0
        except (OperatorUnavailable, OperatorProtocolError) as error:
            print(f"{error.kind}: {error}", file=sys.stderr)
            return _operator_exit_code(error)
    if args.offline and args.command in live_operations:
        try:
            _offline_state_path(_root(args.state_root))
        except EdgeStoreError as error:
            print(f"offline state unavailable: {error}; --offline requires existing controller state", file=sys.stderr)
            return 66
    if args.command == "lifecycle-plan":
        if args.current_state is not None:
            snapshot = json.loads(args.current_state.read_text(encoding="utf-8"))
            controller = snapshot.get("controller")
            binding = snapshot.get("binding")
            active_runs = snapshot.get("active_runs", snapshot.get("runs", []))
            current_release = snapshot.get("installed_release")
            runtime_installed = snapshot.get("runtime_installed", snapshot.get("controller") is not None)
            durable_state_present = snapshot.get("durable_state_present", snapshot.get("controller") is not None or snapshot.get("binding") is not None)
        else:
            status = inspect_installation(_root(args.state_root))
            controller, binding, active_runs, current_release = (status.controller, status.binding,
                                                                  status.active_runs, status.installed_release)
            runtime_installed, durable_state_present = status.runtime_installed, status.durable_state_present
        plan = plan_lifecycle(operation=args.operation, current_installation=runtime_installed,
                              current_release=current_release, target_release=args.release,
                              current_binding=binding, target_server=args.server,
                              connectivity=(controller or {}).get("connection_state") if controller else None,
                              active_runs=active_runs, confirmed=args.confirmed,
                              durable_state_present=durable_state_present)
        _emit(plan.__dict__)
        return 2 if plan.blocked_reasons else 0
    if args.command == "dispense":
        try:
            artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
            _emit(plan_calibrated_dispense(artifact=artifact, volume_ul=args.volume_ul,
                                           channel=args.channel, maximum_duration_ms=args.maximum_duration_ms))
            return 0
        except (EdgeStoreError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            _emit({"error": str(error)}); return 2
    if args.command == "validation":
        try:
            _emit({"operation": args.operation,
                   "parameters": validate_bounded_operation(args.operation, json.loads(args.parameters))})
            return 0
        except (EdgeStoreError, TypeError, ValueError, json.JSONDecodeError) as error:
            _emit({"error": str(error)}); return 2
    if args.command == "tui" and not args.offline:
        from .tui import TUIUnavailableError, run
        try:
            return run(OperatorClient(args.operator_socket), page=args.page, workflow=args.workflow)
        except TUIUnavailableError as error:
            print(str(error), file=sys.stderr)
            return 2
        except OperatorUnavailable as error:
            print(f"{error}; use --offline tui for local durable state", file=sys.stderr)
            return 69
    with EdgeStore(_root(args.state_root)) as store:
        if args.command == "record-installed-release":
            try:
                _emit({"installed_release": record_installed_release(store, args.release)})
                return 0
            except Exception as error:
                _emit({"error": str(error)}); return 2
        if args.command == "enroll":
            client = SyncClient(store)
            # Keep the decision auditable in CLI output.  It intentionally
            # does not infer a replacement merely because the server changed.
            plan = client.enrollment_plan(server=args.server)
            try:
                result = client.enroll(server=args.server, token=args.token, mode=args.mode,
                                       operator_confirmed=args.confirm_forced_adoption)
            except (RuntimeError, ValueError) as error:
                _emit({"enrollment": plan, "error": str(error)}); return 2
            _emit({"enrollment": plan, "result": result}); return 0
        if args.command == "status":
            _emit({"controller": store.identity(), "binding": store.binding(), "runs": store.list_runs()}); return 0
        if args.command == "doctor":
            central_health = (lambda _url: (False, "offline mode; central health not probed")) if offline_read else None
            report = doctor_report(store, **({"central_health": central_health} if central_health else {}))
            _emit(report)
            return 2 if report["summary"]["FAIL"] else 0
        if args.command == "runs": _emit(store.list_runs()); return 0
        if args.command == "binding": _emit(store.binding()); return 0
        if args.command == "install-status":
            _emit(status_json(store.root)); return 0
        if args.command == "update":
            manager = UpdateManager(store, _update_backend(), policy=_update_policy())
            if args.update_command == "status":
                _emit({"installed_release": store.meta("controller_software_release"),
                       "desired_release": store.meta("desired_controller_software_release"),
                       "policy": manager.policy.value, "backend": manager.backend.name,
                       "active_runs": [run["id"] for run in manager.active_runs()]})
                return 0
            try:
                if args.update_command == "check":
                    _emit(manager.plan(args.release).__dict__); return 0
                # Applying from evoctl is a local, explicit maintenance
                # action.  The manager still records the release durably.
                _emit(manager.request(args.release, explicit=True).__dict__); return 0
            except Exception as error:
                _emit({"error": str(error)}); return 2
        if args.command == "recovery": _emit(store.recovery_manifest()); return 0
        if args.command == "export-state":
            from .recovery import export_state
            _emit(export_state(store, args.archive)); return 0
        if args.command == "import-state":
            from .recovery import import_state
            try:
                _emit(import_state(store, args.archive)); return 0
            except (EdgeStoreError, OSError) as error:
                _emit({"error": str(error)}); return 2
        if args.command == "sync":
            client = SyncClient(store)
            if args.loop: client.run_loop(interval=args.interval)
            else: _emit(client.sync_once().__dict__)
            return 0
        if args.command == "controllers": _emit([store.identity()]); return 0
        if args.command == "instruments": _emit(store.list_instruments()); return 0
        if args.command == "calibration":
            try:
                if args.calibration_command == "artifacts":
                    _emit(store.calibration_artifacts(instrument_id=args.instrument_id)); return 0
                references = json.loads(args.references)
                requirements = json.loads(args.requirements)
                _emit(store.calibration_preflight(references, requirements=requirements)); return 0
            except (EdgeStoreError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                _emit({"error": str(error)}); return 2
        if args.command == "instrument":
            try:
                _emit(store.instrument(args.instrument_id)); return 0
            except KeyError:
                _emit({"id": args.instrument_id, "error": "instrument not found"}); return 1
        if args.command == "tui":
            from .tui import TUIUnavailableError, run_offline
            try:
                return run_offline(store, page=args.page)
            except TUIUnavailableError as error:
                print(str(error), file=sys.stderr)
                return 2
        if args.command == "simulator":
            # Simulator support is part of this distribution.  Constructing it
            # also derives stable inventory from the durable controller id, so
            # repeated operator invocations report the same instruments.
            from .simulator import EvolverSimulator
            simulator = EvolverSimulator(store, instruments=args.instruments)
            if args.simulator_command == "start":
                _emit({"controller": store.identity(), "instruments": simulator.inventory()}); return 0
            if args.simulator_command == "create-run":
                try:
                    plan = json.loads(args.execution_plan)
                except json.JSONDecodeError as error:
                    _emit({"error": f"execution plan must be JSON: {error}"}); return 2
                bundle = resolve_bundle({"id": args.bundle_id, "purpose": "test_fixture",
                                         "execution_mode": "declarative_state_machine", "execution_plan": plan,
                                         "calibration_requirements": []}, [])
                store.put_bundle(bundle)
                _emit(simulator.start_run(run_id=args.run_id, bundle_id=args.bundle_id)); return 0
            _emit({"run_id": args.run_id, "records": simulator.tick(run_ids=[args.run_id], ticks=args.ticks)})
            return 0
        if args.command == "firmware":
            from .firmware import main as firmware_main
            firmware_args = [args.action]
            if args.port: firmware_args += ["--port", args.port]
            if args.artifact: firmware_args += ["--artifact", str(args.artifact)]
            if args.physical: firmware_args += ["--physical"]
            if args.operator: firmware_args += ["--operator", args.operator]
            if args.sha256: firmware_args += ["--sha256", args.sha256]
            return firmware_main(firmware_args)
        if args.command == "hardware":
            if args.hardware_command == "quarantine-command":
                try:
                    _emit(store.quarantine_command(
                        args.command_id, operator=args.operator, reason_kind=args.reason_kind,
                        requested_identity={"device_id": args.requested_device, "owner_id": args.requested_owner},
                        observed_identity={"device_id": args.observed_device, "owner_id": args.observed_owner}))
                    return 0
                except (RuntimeError, ValueError, OSError) as error:
                    _emit({"error": str(error)}); return 2
            from .hardware_ipc import request
            socket_path = args.socket
            if args.hardware_command == "discover":
                _emit(request(socket_path, {"operation": "discover"}, args.timeout)); return 0
            if args.hardware_command == "protocol-test":
                _emit(request(socket_path, {"operation": "protocol_test"}, args.timeout)); return 0
            if args.hardware_command == "provision-identity":
                _emit(request(socket_path, {"operation": "provision_identity", "device_id": args.device_id,
                                            "owner_id": args.owner_id, "operator": args.operator,
                                            "physical": args.physical}, args.timeout)); return 0
            if args.hardware_command == "lease":
                if args.lease_command == "acquire":
                    binding = store.binding() or {}
                    payload = {"operation": "lease_acquire", "operator": args.operator,
                               "ttl_seconds": args.ttl_seconds,
                               "controller_generation": int(binding.get("generation", 0))}
                elif args.lease_command == "status": payload = {"operation": "lease_status"}
                else: payload = {"operation": "lease_release", "operator": args.operator}
                _emit(request(socket_path, payload, args.timeout)); return 0
            if args.hardware_command == "layout":
                _emit(request(socket_path, {"operation": "layout_record", "target_identity": args.target,
                                            "operator": args.operator, "positions": {str(args.channel): {
                                                "physical_side": args.physical_side, "method": args.method}}}, args.timeout)); return 0
            params = {"channel": args.channel}
            if args.operation == "set_output": params.update(output="od_led", level=args.level)
            elif args.operation == "pulse_pump": params.update(duration_ms=args.duration_ms)
            elif args.operation in {"set_stir", "pulse_heater"}: params.update(duration_ms=args.duration_ms, level=args.level)
            generation = int((store.binding() or {}).get("generation", 0))
            _emit(request(socket_path, {"operation": args.operation, "target_identity": args.target,
                                        "parameters": params, "physical": args.physical, "operator": args.operator,
                                        "lease_token": args.lease_token, "controller_generation": generation}, args.timeout)); return 0
        if args.command == "run":
            if args.run_command == "show": _emit(store.run(args.run_id)); return 0
            if args.run_command == "events": _emit(store.events_after(args.run_id)); return 0
            if args.run_command == "telemetry":
                _emit([record for item in store.recovery_manifest()["telemetry_ranges"] for record in store.telemetry_after(item["stream_id"]) if args.run_id in item["stream_id"]]); return 0
            run = store.run(args.run_id)
            revision = args.based_on_revision if args.based_on_revision is not None else run["current_revision"]
            state = {"pause": "paused", "resume": "running", "stop": "stopped"}[args.run_command]
            _emit(store.transition_run(run_id=args.run_id, state=state, based_on_revision=revision)); return 0
    return 1


def _update_policy() -> UpdatePolicy:
    try:
        return UpdatePolicy(os.environ.get("EVOLVER_UPDATE_POLICY", UpdatePolicy.WHEN_IDLE))
    except ValueError as exc:
        raise ValueError("EVOLVER_UPDATE_POLICY must be manual, when_idle, or automatic") from exc


def _update_backend():
    return ComposeUpdateBackend(compose_file=os.environ.get("EVOLVER_COMPOSE_FILE"))


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
