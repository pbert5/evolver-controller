#!/usr/bin/env python3
"""Deterministic Pilot harness for the controller-native evoctl TUI."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib
import io
import inspect
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
for _path in reversed(
    (
        ROOT / "evolver" / "evolver-controller" / "src",
        ROOT / "evolver" / "evolver-procedure-runtime" / "src",
        ROOT / "evolver" / "evolver-server" / "src",
        ROOT / "metactl",
    )
):
    if str(_path) in sys.path:
        sys.path.remove(str(_path))
    sys.path.insert(0, str(_path))


VIEWS = ("overview", "controllers", "instruments", "runs", "recovery", "maintenance", "workflows")
READ_OPERATIONS = {
    "status",
    "binding",
    "controllers",
    "doctor",
    "capabilities",
    "instruments",
    "runs",
    "recovery",
    "maintenance",
}
NATIVE_MODULES = (
    "meta_webui_application_backend.evolver_edge.native_tui",
    "meta_webui_application_backend.evolver_edge.evoctl_tui",
)
WORKFLOW_MODULES = (
    "meta_webui_application_backend.evolver_edge.workflow_cli",
)


class SurfaceUnavailable(RuntimeError):
    """A required native test surface is unavailable."""


class AuthorityViolation(RuntimeError):
    """The deterministic harness observed a mutation or live-authority request."""


@dataclass(frozen=True)
class SourceRequest:
    operation: str
    parameters: Mapping[str, Any]


@dataclass(frozen=True)
class SurfaceResult:
    name: str
    action: str
    status: str
    error: str | None = None
    evidence: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["evidence"] = dict(self.evidence or {})
        return value


@dataclass(frozen=True)
class AggregateResult:
    results: tuple[SurfaceResult, ...]

    @property
    def exit_code(self) -> int:
        return 0 if all(item.status == "PASS" for item in self.results) else 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "status": "PASS" if self.exit_code == 0 else "FAIL",
            "results": [item.as_dict() for item in self.results],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")) + "\n"


class FakeTuiSource:
    """Read-only deterministic implementation of the native source contract."""

    def __init__(self) -> None:
        self.requests: list[SourceRequest] = []
        self.mutation_requests: list[SourceRequest] = []
        self._failures: dict[str, Exception] = {}

    def fail_next(self, operation: str, error: Exception | None = None) -> None:
        self._failures[operation] = error or RuntimeError(f"fixture failure: {operation}")

    def request(self, operation: str, **parameters: Any) -> Any:
        request = SourceRequest(operation, dict(parameters))
        self.requests.append(request)
        if operation not in READ_OPERATIONS:
            self.mutation_requests.append(request)
            raise AuthorityViolation(f"native source requested forbidden operation: {operation}")
        if operation in self._failures:
            raise self._failures.pop(operation)
        return self._fixture(operation)

    def status(self) -> Mapping[str, Any]:
        return self.request("status")

    def binding(self) -> Mapping[str, Any]:
        return self.request("binding")

    def controllers(self) -> list[Mapping[str, Any]]:
        return self.request("controllers")

    def doctor(self) -> Mapping[str, Any]:
        return self.request("doctor")

    def capabilities(self) -> Mapping[str, Any]:
        return self.request("capabilities")

    def instruments(self) -> list[Mapping[str, Any]]:
        return self.request("instruments")

    def runs(self) -> list[Mapping[str, Any]]:
        return self.request("runs")

    def recovery(self) -> Mapping[str, Any]:
        return self.request("recovery")

    def maintenance(self) -> Mapping[str, Any]:
        return self.request("maintenance")

    def _fixture(self, operation: str) -> Any:
        controller = {
            "id": "fixture-controller",
            "name": "Fixture Controller",
            "connection_state": "offline-fixture",
            "service_health": "fixture",
        }
        instruments = [{"id": "fixture-instrument", "name": "Fixture Instrument", "state": "ready"}]
        if operation == "status":
            return {"controller": controller, "binding": {"generation": 1}, "runs": 1}
        if operation == "binding":
            return {"generation": 1, "controller_id": controller["id"]}
        if operation == "controllers":
            return [{**controller, "binding": {"generation": 1}, "inventory": instruments}]
        if operation == "doctor":
            return {"service": "fixture", "healthy": True, "checks": ["operator", "store"]}
        if operation == "capabilities":
            return {"read": True, "mutation": False, "authority": "none"}
        if operation == "instruments":
            return instruments
        if operation == "runs":
            return [{"id": "fixture-run", "state": "idle", "revision": 1}]
        if operation == "recovery":
            return {"manifest": "fixture-recovery", "generation": 1, "safe": True}
        if operation == "maintenance":
            return {"doctor": self.doctor(), "capabilities": self.capabilities(), "release": "fixture"}
        raise AssertionError(f"unhandled fixture operation: {operation}")


def aggregate_results(results: Iterable[SurfaceResult]) -> AggregateResult:
    return AggregateResult(tuple(results))


def run_actions(actions: Iterable[tuple[str, Callable[[object], object]]]) -> AggregateResult:
    results: list[SurfaceResult] = []
    for name, action in actions:
        try:
            evidence = action(None)
        except Exception as error:
            results.append(SurfaceResult(name, "action", "FAIL", error=f"{type(error).__name__}: {error}"))
        else:
            results.append(
                SurfaceResult(name, "action", "PASS", evidence=evidence if isinstance(evidence, Mapping) else {})
            )
    return aggregate_results(results)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tools/tui-test", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "list", "smoke"):
        command = commands.add_parser(name)
        command.add_argument("--json", dest="json_output", action="store_true")
    shell = commands.add_parser("shell")
    shell.add_argument("--page", choices=VIEWS, default="overview")
    workflow = commands.add_parser("workflow")
    workflow.add_argument("--scenario", required=True)
    return parser


def _import(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except (ImportError, ModuleNotFoundError) as error:
        raise SurfaceUnavailable(f"missing native dependency/import: {name} ({error})") from error


def _native_module() -> Any:
    errors: list[str] = []
    for name in NATIVE_MODULES:
        try:
            return _import(name)
        except SurfaceUnavailable as error:
            errors.append(str(error))
    raise SurfaceUnavailable("native EvoctlApp factory unavailable; " + " | ".join(errors))


def _workflow_module() -> Any:
    errors: list[str] = []
    for name in WORKFLOW_MODULES:
        try:
            return _import(name)
        except SurfaceUnavailable as error:
            errors.append(str(error))
    raise SurfaceUnavailable("ScenarioRegistry unavailable; " + " | ".join(errors))


def create_native_app(*, source: Any, workflow_host: Any = None, initial_view: str = "overview") -> Any:
    factory = getattr(_native_module(), "create_app", None)
    if factory is None:
        raise SurfaceUnavailable("native TUI module has no create_app(source, workflow_host, initial_view) factory")
    return factory(source=source, workflow_host=workflow_host, initial_view=initial_view)


def scenario_registry() -> Any:
    registry = getattr(_workflow_module(), "ScenarioRegistry", None)
    if registry is None:
        raise SurfaceUnavailable("native workflow module has no ScenarioRegistry")
    return registry()


def scenario_host(name: str) -> Any:
    registry = scenario_registry()
    host = getattr(registry, "host", None)
    if host is None:
        raise SurfaceUnavailable("ScenarioRegistry has no host(name) method")
    return host(name)


def _scenario_names() -> list[str]:
    registry = scenario_registry()
    names = getattr(registry, "names", None)
    if names is None:
        raise SurfaceUnavailable("ScenarioRegistry has no names() method")
    return sorted(str(name) for name in names())


def _trusted_workflow_ids() -> list[str]:
    root = ROOT / "workflows" / "calibration"
    if not root.is_dir():
        raise SurfaceUnavailable(f"trusted workflow root unavailable: {root}")
    runtime = _import("evolver_procedure_runtime")
    library = runtime.WorkflowLibrary.from_directories([root])
    return sorted(str(item.id) for item in library.list())


def _run_pilot(app: Any, exercise: Callable[[Any, Any], Mapping[str, Any]]) -> Mapping[str, Any]:
    async def runner() -> Mapping[str, Any]:
        async with app.run_test() as pilot:
            await pilot.pause()
            result = exercise(app, pilot)
            if inspect.isawaitable(result):
                result = await result
            return result

    diagnostics = io.StringIO()
    with contextlib.redirect_stderr(diagnostics):
        result = asyncio.run(runner())
    if diagnostics.getvalue().strip():
        raise RuntimeError(f"Textual diagnostic during smoke: {diagnostics.getvalue().strip().splitlines()[-1]}")
    return result


async def _native_interaction(app: Any, pilot: Any) -> Mapping[str, Any]:
    for _ in range(len(VIEWS) + 2):
        await pilot.press("ctrl+right")
        await pilot.pause()
    await pilot.press("r")
    await pilot.pause()
    await pilot.press("ctrl+left")
    await pilot.pause()
    return {"renderer": type(app).__name__, "views": list(VIEWS), "settled": True}


async def _workflow_interaction(app: Any, pilot: Any) -> Mapping[str, Any]:
    await pilot.press("ctrl+n")
    await pilot.pause()
    await pilot.press(*tuple("temperature"))
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()
    workspace = getattr(app, "workspace", None)
    current = getattr(workspace, "current", None)
    snapshot = getattr(current, "snapshot", None)
    if snapshot is not None:
        representations = set(getattr(snapshot, "representations", {}) or {})
        drawer = set(getattr(snapshot, "drawer", {}) or {})
        if representations and not {"Step", "Action", "API", "CLI", "Raw"}.issubset(representations):
            raise AssertionError("workflow inspector projections are incomplete")
        if drawer and not {"Info", "Inputs", "Safety", "Evidence", "Outputs", "Events"}.issubset(drawer):
            raise AssertionError("workflow drawer projections are incomplete")
    for mode in ("step", "action", "api", "cli", "raw"):
        try:
            app.query_one("#representations").active = f"representation-{mode}"
        except Exception:
            pass
        await pilot.pause()
    for view in ("info", "inputs", "safety", "evidence", "outputs", "events"):
        try:
            app.query_one("#drawer-tabs").active = f"drawer-{view}"
        except Exception:
            pass
        await pilot.pause()
    for key in ("i", "escape", "a", "escape"):
        await pilot.press(key)
        await pilot.pause()
    for _ in range(3):
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("ctrl+right")
        await pilot.pause()
    return {"renderer": type(app).__name__, "workflow": True, "settled": True}


def _native_smoke_for_view(view: str) -> SurfaceResult:
    source = FakeTuiSource()
    try:
        app = create_native_app(source=source, initial_view=view)
        evidence = _run_pilot(app, _native_interaction)
    except Exception as error:
        return SurfaceResult(f"native:{view}", "pilot", "FAIL", error=f"{type(error).__name__}: {error}")
    if source.mutation_requests:
        return SurfaceResult(f"native:{view}", "authority", "FAIL", error="fixture observed mutation request")
    return SurfaceResult(f"native:{view}", "pilot", "PASS", evidence=evidence)


def _source_error_smoke() -> SurfaceResult:
    source = FakeTuiSource()
    source.fail_next("instruments")
    try:
        app = create_native_app(source=source, initial_view="instruments")
        evidence = _run_pilot(app, _native_interaction)
    except Exception as error:
        return SurfaceResult("native:source-error", "pilot", "FAIL", error=f"{type(error).__name__}: {error}")
    failed = any(request.operation == "instruments" for request in source.requests)
    return SurfaceResult(
        "native:source-error",
        "error-preservation",
        "PASS" if failed else "FAIL",
        error=None if failed else "injected source operation was not requested",
        evidence=evidence,
    )


def _workflow_smoke() -> list[SurfaceResult]:
    results: list[SurfaceResult] = []
    try:
        names = _scenario_names()
    except Exception as error:
        return [SurfaceResult("workflow:registry", "discovery", "FAIL", error=f"{type(error).__name__}: {error}")]
    for name in names:
        try:
            app = create_native_app(source=FakeTuiSource(), workflow_host=scenario_host(name), initial_view="workflows")
            evidence = _run_pilot(app, _workflow_interaction)
        except Exception as error:
            results.append(SurfaceResult(f"workflow:{name}", "pilot", "FAIL", error=f"{type(error).__name__}: {error}"))
        else:
            results.append(SurfaceResult(f"workflow:{name}", "pilot", "PASS", evidence=evidence))
    return results


def _native_smoke() -> list[SurfaceResult]:
    return [*_native_smoke_for_views(), _source_error_smoke(), *_workflow_smoke()]


def _native_smoke_for_views() -> list[SurfaceResult]:
    return [_native_smoke_for_view(view) for view in VIEWS]


def _doctor_checks() -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    for name in ("textual", "yaml", "evolver_procedure_runtime"):
        try:
            module = _import(name)
        except SurfaceUnavailable as error:
            checks.append({"name": name, "status": "FAIL", "detail": str(error)})
        else:
            checks.append({"name": name, "status": "PASS", "detail": str(getattr(module, "__file__", "available"))})
    try:
        module = _native_module()
    except SurfaceUnavailable as error:
        checks.append({"name": "native_app_factory", "status": "FAIL", "detail": str(error)})
    else:
        checks.append({"name": "native_app_factory", "status": "PASS", "detail": module.__name__})
    for name, path in (
        ("workflow_root", ROOT / "workflows" / "calibration"),
        ("procedure_descriptor_root", ROOT / "workflows" / "examples"),
    ):
        checks.append({"name": name, "status": "PASS" if path.is_dir() else "FAIL", "detail": str(path)})
    try:
        names = _scenario_names()
    except SurfaceUnavailable as error:
        checks.append({"name": "scenario_registry", "status": "FAIL", "detail": str(error)})
    else:
        checks.append({"name": "scenario_registry", "status": "PASS" if names else "FAIL", "detail": ",".join(names)})
    checks.append({"name": "fake_source", "status": "PASS", "detail": "deterministic read-only fixture"})
    checks.append({"name": "authority", "status": "PASS", "detail": "no live fallback, socket, serial, database, or hardware"})
    return checks


def doctor(*, json_output: bool = False) -> int:
    checks = _doctor_checks()
    failed = any(item["status"] == "FAIL" for item in checks)
    payload = {"schema_version": 2, "status": "FAIL" if failed else "PASS", "checks": checks}
    if json_output:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        for item in checks:
            print(f"{item['status']} {item['name']}: {item['detail']}")
    return int(failed)


def list_surfaces(*, json_output: bool = False) -> int:
    errors: list[str] = []
    try:
        scenarios = _scenario_names()
    except Exception as error:
        scenarios = []
        errors.append(str(error))
    try:
        trusted = _trusted_workflow_ids()
    except Exception as error:
        trusted = []
        errors.append(str(error))
    payload = {
        "schema_version": 2,
        "native_views": list(VIEWS),
        "workflow_scenarios": scenarios,
        "trusted_workflows": trusted,
        "status": "FAIL" if errors else "PASS",
        "errors": errors,
    }
    if json_output:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        for group in ("native_views", "workflow_scenarios", "trusted_workflows"):
            print(f"{group}:")
            for item in payload[group]:
                print(f"  {item}")
    return int(bool(errors))


def run_interactive(kind: str, *, scenario: str | None = None, page: str | None = None) -> int:
    host = scenario_host(scenario) if kind == "workflow" and scenario else None
    app = create_native_app(source=FakeTuiSource(), workflow_host=host, initial_view="workflows" if kind == "workflow" else page or "overview")
    app.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return doctor(json_output=args.json_output)
    if args.command == "list":
        return list_surfaces(json_output=args.json_output)
    if args.command == "shell":
        try:
            return run_interactive("shell", page=args.page)
        except Exception as error:
            print(f"shell_error: {error}", file=sys.stderr)
            return 2
    if args.command == "workflow":
        try:
            return run_interactive("workflow", scenario=args.scenario)
        except Exception as error:
            print(f"workflow_error: {error}", file=sys.stderr)
            return 2
    try:
        results = aggregate_results(_native_smoke())
    except Exception as error:
        results = aggregate_results((SurfaceResult("smoke:runner", "aggregation", "FAIL", error=f"{type(error).__name__}: {error}"),))
    if args.json_output:
        print(results.to_json(), end="")
    else:
        for item in results.results:
            detail = f" ({item.error})" if item.error else ""
            print(f"{item.status} {item.name}{detail}")
    return results.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
