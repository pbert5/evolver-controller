"""Controller-native Textual operator shell.

The shell is independent of configured Meta WebUI applications. Live reads
cross the typed operator socket through ``LiveTuiSource``; offline reads are
explicit and use ``OfflineTuiSource``. Widgets only render read models.
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from .operator import OperatorClient

VIEW_NAMES = ("overview", "controllers", "instruments", "runs", "recovery", "maintenance", "workflows")


class TUIUnavailableError(RuntimeError):
    """The optional controller-native Textual extra is not installed."""


class TuiSource(Protocol):
    def read(self, view: str) -> Mapping[str, Any]: ...


def _require_view(view: str) -> str:
    if view not in VIEW_NAMES:
        raise ValueError(f"unknown TUI view: {view}")
    return view


class LiveTuiSource:
    """Read-only source backed exclusively by the typed ``OperatorClient``."""

    def __init__(self, client: OperatorClient):
        self.client = client

    def read(self, view: str) -> Mapping[str, Any]:
        view = _require_view(view)
        if view == "workflows":
            return {"workflows": []}
        status = self.client.request("status")
        controller = status.get("controller", {})
        binding = status.get("binding", {})
        if view in {"controllers", "recovery"}:
            return {"controller": controller, "binding": binding}
        if view == "instruments":
            return {"instruments": self.client.request("instruments")}
        if view == "runs":
            return {"runs": self.client.request("runs")}
        if view == "maintenance":
            return {"doctor": self.client.request("doctor"),
                    "capabilities": self.client.request("capabilities"),
                    "controller": controller, "binding": binding}
        return {"controller": controller, "binding": binding,
                "instruments": self.client.request("instruments"),
                "runs": self.client.request("runs")}


class OfflineTuiSource:
    """Explicit offline source backed only by the durable ``EdgeStore``."""

    def __init__(self, store: Any):
        self.store = store

    def read(self, view: str) -> Mapping[str, Any]:
        view = _require_view(view)
        controller = self.store.identity()
        binding = self.store.binding()
        if view == "workflows":
            return {"workflows": []}
        if view in {"controllers", "recovery"}:
            result: dict[str, Any] = {"controller": controller, "binding": binding}
            if view == "recovery" and hasattr(self.store, "recovery_manifest"):
                result["manifest"] = self.store.recovery_manifest()
            return result
        if view == "instruments":
            return {"instruments": self.store.list_instruments()}
        if view == "runs":
            return {"runs": self.store.list_runs()}
        if view == "maintenance":
            from .doctor import doctor_report
            return {"doctor": doctor_report(self.store), "capabilities": {"mode": "offline"},
                    "controller": controller, "binding": binding}
        return {"controller": controller, "binding": binding,
                "instruments": self.store.list_instruments(), "runs": self.store.list_runs()}


def _format(value: Any) -> str:
    if isinstance(value, Mapping):
        return "\n".join(f"{key}: {_format(item)}" for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return "\n".join(_format(item) for item in value) or "(none)"
    return str(value)


def create_app(*, source: TuiSource, workflow_host: Any | None = None,
               initial_view: str = "overview") -> Any:
    """Build the one native app; ``source`` is the deterministic #132 seam."""
    _require_view(initial_view)
    try:
        from textual.app import App, ComposeResult
        from textual.widgets import Footer, Header, Static
    except (ImportError, ModuleNotFoundError) as error:
        raise TUIUnavailableError("the controller TUI is unavailable; install evoctl[tui]") from error

    class EvoctlApp(App[None]):
        TITLE = "evoctl"
        BINDINGS = [
            ("ctrl+left", "previous_view", "Previous view"),
            ("ctrl+right", "next_view", "Next view"),
            ("ctrl+[", "previous_view", "Previous view"),
            ("ctrl+]", "next_view", "Next view"),
            ("r", "refresh_view", "Refresh"),
            ("?", "show_help", "Help"),
        ]
        CSS = """
        #navigation { height: 3; padding: 1; border: solid $surface; }
        #content { height: 1fr; padding: 1; border: solid $surface; }
        #status { height: 2; padding: 0 1; }
        """

        def __init__(self) -> None:
            super().__init__()
            self.source = source
            self.workflow_host = workflow_host
            self.initial_view = initial_view
            self.current_view = initial_view
            self.view_names = VIEW_NAMES
            self.last_good: dict[str, Mapping[str, Any]] = {}
            self.section_errors: dict[str, str] = {}
            self._refresh_requested = 0
            self._refresh_completed = 0
            self._refresh_running = False
            self._workflow_workspace = None

        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            yield Static("", id="navigation")
            yield Static("", id="status")
            yield Static("", id="content")
            yield Footer()

        def on_mount(self) -> None:
            if self.workflow_host is not None:
                from .workflow_tui import WorkflowWorkspace
                self._workflow_workspace = WorkflowWorkspace(self.workflow_host)
            self.run_worker(self.refresh_view())

        def _render_navigation(self) -> None:
            self.query_one("#navigation", Static).update("  ".join(
                f"[{index}] {name.title()}" + (" ◀" if name == self.current_view else "")
                for index, name in enumerate(self.view_names, 1)))

        def _render(self, data: Mapping[str, Any]) -> None:
            self._render_navigation()
            error = self.section_errors.get(self.current_view)
            status = f"view={self.current_view} · refresh={self._refresh_completed}"
            if error:
                status += f" · read error: {error} · showing last good data"
            self.query_one("#status", Static).update(status)
            if self.current_view == "workflows" and self._workflow_workspace is not None:
                tab = self._workflow_workspace.current
                snapshot = tab.snapshot
                data = {"workflow_tabs": self._workflow_workspace.tab_ids,
                        "active_tab": tab.tab_id,
                        "status": snapshot.status_glyph,
                        "title": snapshot.title,
                        "procedures": snapshot.procedures,
                        "representations": snapshot.representations,
                        "drawer": snapshot.drawer}
            self.query_one("#content", Static).update(_format(data))

        async def refresh_view(self) -> None:
            self._refresh_requested += 1
            if self._refresh_running:
                return
            self._refresh_running = True
            try:
                while self._refresh_completed < self._refresh_requested:
                    requested = self._refresh_requested
                    try:
                        data = await asyncio.to_thread(self.source.read, self.current_view)
                        self.last_good[self.current_view] = data
                        self.section_errors.pop(self.current_view, None)
                    except Exception as error:
                        self.section_errors[self.current_view] = str(error)
                        data = self.last_good.get(self.current_view, {"unavailable": str(error)})
                    self._refresh_completed = requested
                    self._render(data)
            finally:
                self._refresh_running = False

        def _move(self, delta: int) -> None:
            self.current_view = self.view_names[(self.view_names.index(self.current_view) + delta) % len(self.view_names)]
            self.run_worker(self.refresh_view())

        def action_previous_view(self) -> None:
            if self.current_view == "workflows" and self._workflow_workspace is not None:
                self._workflow_workspace.cycle_tab(-1)
                self.run_worker(self.refresh_view())
                return
            self._move(-1)

        def action_next_view(self) -> None:
            if self.current_view == "workflows" and self._workflow_workspace is not None:
                self._workflow_workspace.cycle_tab(1)
                self.run_worker(self.refresh_view())
                return
            self._move(1)

        def action_refresh_view(self) -> None:
            self.run_worker(self.refresh_view())

        def action_show_help(self) -> None:
            self.notify("Ctrl+Left/Right or Ctrl+[ ]: navigate · 1-7: select · r: refresh · ?: help")

        def on_key(self, event: Any) -> None:
            if event.key in {str(index) for index in range(1, 8)}:
                focused = self.focused
                if focused is not None and focused.__class__.__name__ in {"Input", "TextArea"}:
                    return
                self.current_view = self.view_names[int(event.key) - 1]
                self.run_worker(self.refresh_view())

    return EvoctlApp()


def _workflow_host(client: OperatorClient):
    """Build the reviewed workflow host from typed, side-effect-free projections."""
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
                        context=HostContext(target_identity=identity, controller_generation=target.generation),
                        safe_stop_authority=operator_safe_stop_authority(client))


def run(client: OperatorClient, *, page: str = "overview", workflow: bool = False) -> int:
    host = _workflow_host(client) if workflow or page == "workflows" else None
    app = create_app(source=LiveTuiSource(client), workflow_host=host,
                     initial_view="workflows" if workflow else page)
    app.run()
    return 0


def run_offline(store: Any, *, page: str = "overview") -> int:
    app = create_app(source=OfflineTuiSource(store), initial_view=page)
    app.run()
    return 0
