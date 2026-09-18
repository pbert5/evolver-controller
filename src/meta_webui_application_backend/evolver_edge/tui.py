"""Textual operator UI backed by the controller's shared operator API."""
from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any, Mapping

from .operator import OperatorClient

_LOCAL_QUERY_PAGES = {"overview": "evolver_overview", "controllers": "evolver_controllers", "instruments": "evolver_instruments", "runs": "evolver_runs", "recovery": "evolver_recovery", "maintenance": "evolver_maintenance"}


class TUIUnavailableError(RuntimeError):
    """The optional configured TUI runtime is not installed."""


def _application_root() -> Path:
    configured = os.environ.get("META_WEBUI_APPLICATION_ROOT")
    candidates = [Path(configured)] if configured else []
    candidates.extend((Path.cwd() / "applications" / "deployment", Path("/etc/meta-webui/applications/deployment")))
    return next((candidate for candidate in candidates if (candidate / "app.yaml").is_file()), candidates[0] if candidates else Path("applications/deployment"))


def _load_ui_dependencies():
    try:
        compiler = importlib.import_module("config_compiler")
        runtime = importlib.import_module("meta_webui_ui_runtime_textual")
        return compiler.compile_application, runtime.ApplicationLoader
    except (ImportError, ModuleNotFoundError) as error:
        raise TUIUnavailableError("the TUI is unavailable; install the optional dependencies with evoctl[tui]") from error


def _operator_source(client: OperatorClient):
    """Resolve configured page queries exclusively through ``OperatorClient``."""
    def resolve(source: Mapping[str, Any], _scope: Mapping[str, Any]) -> Any:
        query = source.get("query")
        if query == "evolver.controllers":
            status = client.request("status")
            instruments = client.request("instruments")
            return [{**status["controller"], "binding": status["binding"], "inventory": instruments}]
        if query == "evolver.controller_snapshot":
            status = client.request("status")
            return {"controller": status["controller"], "binding": status["binding"], "instruments": client.request("instruments"), "central": "connected" if status["controller"].get("connection_state") == "connected" else "offline"}
        if query == "evolver.runs":
            return client.request("runs")
        if query == "evolver.instruments":
            return client.request("instruments")
        if query == "evolver.maintenance":
            status = client.request("status")
            controller = status["controller"]
            return [{"controller_id": controller["id"], "connection_state": controller.get("connection_state", "unknown"), "binding": status["binding"], "software_release": controller.get("software_release"), "desired_release": controller.get("desired_release"), "update_policy": os.environ.get("EVOLVER_UPDATE_POLICY", "when_idle"), "service_health": controller.get("service_health", "unknown"), "hardware_service_health": controller.get("hardware_service_health", "unknown")}]
        return None
    return resolve


def _offline_source(store):
    """Explicit offline adapter for ``evoctl --offline tui`` only."""
    def resolve(source: Mapping[str, Any], _scope: Mapping[str, Any]) -> Any:
        query = source.get("query")
        if query == "evolver.controllers":
            return [{**store.identity(), "binding": store.binding(), "connection_state": "local_edge", "inventory": store.list_instruments()}]
        if query == "evolver.controller_snapshot":
            return {"controller": store.identity(), "binding": store.binding(), "instruments": store.list_instruments(), "central": "offline"}
        if query == "evolver.runs":
            return store.list_runs()
        if query == "evolver.instruments":
            return store.list_instruments()
        if query == "evolver.maintenance":
            return [{"controller_id": store.identity()["id"], "connection_state": "local_edge", "binding": store.binding(), "software_release": store.meta("controller_software_release"), "desired_release": store.meta("desired_controller_software_release"), "update_policy": os.environ.get("EVOLVER_UPDATE_POLICY", "when_idle"), "service_health": "local_edge", "hardware_service_health": "unknown"}]
        return None
    return resolve


def _run(*, page: str, source_resolver, offline: bool) -> int:
    compile_application, application_loader = _load_ui_dependencies()
    document = compile_application(_application_root()).app_config["definition"]
    status = "CENTRAL OFFLINE · EDGE RUNNING" if offline else "CENTRAL LIVE · EDGE OPERATOR API"
    app = application_loader(document, source_resolver=source_resolver).application(_LOCAL_QUERY_PAGES.get(page, page), scope={"edge": {"status": status}})
    app.run()
    return 0


def run(client: OperatorClient, *, page: str = "overview", workflow: bool = False) -> int:
    """Run live TUI data through the shared local operator client."""
    if workflow:
        from .workflow_tui import run_textual
        return run_textual(_workflow_host(client))
    return _run(page=page, source_resolver=_operator_source(client), offline=False)


def _workflow_host(client: OperatorClient):
    """Build the #55 production host from side-effect-free local projections."""
    import os
    from pathlib import Path
    import yaml
    from evolver_procedure_runtime import WorkflowLibrary, compile_procedure
    from .workflow_host import HostContext, WorkflowHost, operator_safe_stop_authority, resolve_target

    root = Path(os.environ.get("EVOLVER_WORKFLOW_ROOT", "workflows/calibration"))
    descriptor_root = Path(os.environ.get("EVOLVER_PROCEDURE_ROOT", "workflows/examples"))
    library = WorkflowLibrary.from_directories([root]) if root.is_dir() else WorkflowLibrary([])
    procedures = {}
    if descriptor_root.is_dir():
        for path in sorted(descriptor_root.glob("*.yaml")):
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            procedures[(document["id"], document["version"])] = compile_procedure(document)
    instruments = client.request("instruments")
    identity = instruments[0].get("id", "controller") if instruments else "controller"
    target = resolve_target(client, identity)
    return WorkflowHost(client, target=target, workflows=library, procedures=procedures,
                        context=HostContext(target_identity=identity),
                        safe_stop_authority=operator_safe_stop_authority(client))


def run_offline(store, *, page: str = "overview") -> int:
    """Run the explicitly selected offline TUI against durable local state."""
    return _run(page=page, source_resolver=_offline_source(store), offline=True)
