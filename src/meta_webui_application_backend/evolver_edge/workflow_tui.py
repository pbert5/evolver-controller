"""Workflow workspace model and Textual renderer.

The model in this module is deliberately boring.  It owns selection, tabs,
input presentation, and close decisions; the injected host/session owns all
procedure, action, hardware, and persistence semantics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol


STATUS_GLYPHS = {
    "RUNNING": "●",
    "READY": "○",
    "PENDING": "○",
    "PAUSED": "⏸",
    "WAITING": "⏸",
    "SUCCEEDED": "■✓",
    "COMPLETED": "■✓",
    "FAILED": "■F",
    "CANCELLED": "■👤C",
    "ABORTED": "■!A",
}
ATTENTION_GLYPHS = {"input": "!📝", "choice": "!📝", "observation": "!🔎", "physical": "!👤"}
DOMAIN_GLYPHS = {"temperature": "🌡", "calibration": "⚖"}


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def semantic_status(status: str, *, attention: tuple[str, ...] = (), domain: str | None = None,
                    abort_kind: str | None = None, saved: bool = False, dirty: bool = False) -> str:
    """Render semantic state; color is intentionally not part of this contract."""
    state = status.upper()
    if state in {"ABORTED", "CANCELLED"} and abort_kind == "operator":
        primary = "■👤C"
    else:
        primary = STATUS_GLYPHS.get(state, "○")
    parts = [primary]
    parts.extend(ATTENTION_GLYPHS[item] for item in attention if item in ATTENTION_GLYPHS)
    if domain in DOMAIN_GLYPHS:
        parts.append(DOMAIN_GLYPHS[domain])
    if saved:
        parts.append("💾")
    if dirty:
        parts.append("*")
    return " ".join(parts)


@dataclass(frozen=True)
class WorkflowSnapshot:
    workflow_id: str
    title: str
    status: str = "READY"
    attention: tuple[str, ...] = ()
    progress: str = ""
    lease: str = ""
    procedures: tuple[Mapping[str, Any], ...] = ()
    selected_step: str | None = None
    representations: Mapping[str, Any] = field(default_factory=dict)
    drawer: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    correction: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "WorkflowSnapshot":
        attention = value.get("attention", ())
        if isinstance(attention, str):
            attention = (attention,)
        return cls(
            workflow_id=str(value.get("workflow_id", "")), title=str(value.get("title", "Workflow")),
            status=str(value.get("status", "READY")), attention=tuple(attention or ()),
            progress=str(value.get("progress", "")), lease=str(value.get("lease", "")),
            procedures=tuple(value.get("procedures", ()) or ()), selected_step=value.get("selected_step"),
            representations=value.get("representations", {}) or {}, drawer=value.get("drawer", {}) or {},
            metadata=value.get("metadata", {}) or {}, correction=value.get("correction", {}) or {},
        )

    @property
    def status_glyph(self) -> str:
        return semantic_status(self.status, attention=self.attention, domain=self.metadata.get("domain"),
                                abort_kind=self.metadata.get("abort_kind"), saved=self.metadata.get("saved", False),
                                dirty=self.metadata.get("dirty", False))


class CloseDecision(str, Enum):
    RETURN = "return"
    CLOSED = "closed"
    UNSUPPORTED = "unsupported"


class WorkflowSessionLike(Protocol):
    def snapshot_for_ui(self) -> WorkflowSnapshot | Mapping[str, Any]: ...
    def provide_parameter(self, name: str, value: Any) -> Any: ...
    def advance(self) -> Any: ...
    def abort(self, reason: str) -> Any: ...


class RuntimeSessionAdapter:
    """Project a frozen runtime session into the renderer's read-only shape."""

    def __init__(self, session: Any, workflow: Any):
        self._session, self._workflow = session, workflow

    def snapshot_for_ui(self) -> WorkflowSnapshot:
        state = getattr(getattr(self._session, "state", None), "value", None) or getattr(self._session, "state", "READY")
        workflow_id = _field(self._workflow, "id", "workflow")
        title = _field(self._workflow, "title", workflow_id)
        return WorkflowSnapshot(workflow_id, title, str(state).upper(),
                                progress=str(getattr(self._session, "progress", "")),
                                metadata={"source": "frozen-runtime"})

    def provide_parameter(self, name: str, value: Any) -> Any:
        return self._session.provide_parameter(name, value)

    def advance(self) -> Any:
        return self._session.advance()

    def abort(self, reason: str) -> Any:
        return self._session.abort(reason)


class WorkflowHostLike(Protocol):
    def list_workflows(self) -> Any: ...
    def new_session(self, workflow: Any) -> WorkflowSessionLike: ...


@dataclass
class WorkflowTab:
    tab_id: str
    workflow: Any
    session: WorkflowSessionLike | None = None
    draft: bool = True

    @property
    def snapshot(self) -> WorkflowSnapshot:
        if self.session is None:
            workflow_id = _field(self.workflow, "id", self.tab_id)
            title = _field(self.workflow, "title", workflow_id)
            return WorkflowSnapshot(workflow_id, title)
        value = self.session.snapshot_for_ui()
        return value if isinstance(value, WorkflowSnapshot) else WorkflowSnapshot.from_mapping(value)


class WorkflowWorkspace:
    """Deterministic controller for tabs and semantic session interactions."""

    def __init__(self, host: WorkflowHostLike):
        self.host = host
        self.tabs: list[WorkflowTab] = [WorkflowTab("library", {"id": "library", "title": "Workflow Library"}, None, False)]
        self.active_index = 0
        self.representation = "Step"
        self.drawer_view = "Info"
        self.drawer_open = False

    @property
    def tab_ids(self) -> list[str]:
        return [tab.tab_id for tab in self.tabs]

    @property
    def current(self) -> WorkflowTab:
        return self.tabs[self.active_index]

    def workflows(self, search: str = "") -> list[Any]:
        values = list(self.host.list_workflows())
        if not search:
            return values
        needle = search.casefold()
        return [item for item in values if needle in str(_field(item, "title", "")).casefold()
                or needle in str(_field(item, "id", "")).casefold()]

    def open_workflow(self, workflow_id: str) -> WorkflowTab:
        workflow = next((item for item in self.workflows() if _field(item, "id") == workflow_id), None)
        if workflow is None:
            raise KeyError(workflow_id)
        base = workflow_id
        used = {tab.tab_id for tab in self.tabs}
        tab_id, number = base, 2
        while tab_id in used:
            tab_id, number = f"{base}-{number}", number + 1
        # Constructing a session is side-effect free in the frozen runtime;
        # execution still requires the explicit Confirm + Continue/advance path.
        session = self.host.new_session(workflow)
        session = session if hasattr(session, "snapshot_for_ui") else RuntimeSessionAdapter(session, workflow)
        tab = WorkflowTab(tab_id, workflow, session=session, draft=True)
        self.tabs.append(tab)
        self.active_index = len(self.tabs) - 1
        return tab

    def start_current(self) -> WorkflowTab:
        tab = self.current
        if tab.tab_id == "library":
            raise ValueError("the library is not a workflow session")
        if tab.session is None:
            session = self.host.new_session(tab.workflow)
            tab.session = session if hasattr(session, "snapshot_for_ui") else RuntimeSessionAdapter(session, tab.workflow)
            tab.draft = False
        return tab

    def select_tab(self, index: int) -> None:
        if not 0 <= index < len(self.tabs):
            raise IndexError(index)
        self.active_index = index

    def cycle_tab(self, delta: int) -> None:
        self.active_index = (self.active_index + delta) % len(self.tabs)

    def save_inputs(self, tab_id: str, values: Mapping[str, Any]) -> None:
        tab = self._tab(tab_id)
        if tab.session is None:
            self.start_current()
        assert tab.session is not None
        for name, value in values.items():
            tab.session.provide_parameter(name, value)

    def confirm_inputs(self, tab_id: str) -> Any:
        tab = self._tab(tab_id)
        if tab.session is None:
            raise ValueError("session has not been started")
        return tab.session.advance()

    def close_current(self, *, abort: bool = False) -> CloseDecision:
        tab = self.current
        if tab.tab_id == "library":
            return CloseDecision.UNSUPPORTED
        snapshot = tab.snapshot
        if snapshot.status.upper() in {"RUNNING", "WAITING", "PAUSED"} and not abort:
            return CloseDecision.RETURN
        if abort and tab.session is not None:
            tab.session.abort("operator closed workflow tab")
        self.tabs.pop(self.active_index)
        self.active_index = min(self.active_index, len(self.tabs) - 1)
        return CloseDecision.CLOSED

    def inspector(self, mode: str | None = None) -> Any:
        return self.current.snapshot.representations.get(mode or self.representation, "Not available")

    def _tab(self, tab_id: str) -> WorkflowTab:
        return next(tab for tab in self.tabs if tab.tab_id == tab_id)


class FakeWorkflowHost:
    """Small fixture host used by headless tests and preview scenarios."""

    def __init__(self, workflows: list[Mapping[str, Any]], sessions: Mapping[str, list[WorkflowSessionLike]]):
        self._workflows, self._sessions = workflows, {key: list(value) for key, value in sessions.items()}

    def list_workflows(self) -> list[Mapping[str, Any]]:
        values = list(self._workflows)
        known = {item["id"] for item in values}
        values.extend({"id": key, "title": key} for key in self._sessions if key not in known)
        return values

    def new_session(self, workflow: Mapping[str, Any]) -> WorkflowSessionLike:
        return self._sessions[workflow["id"]].pop(0)


def run_textual(host: WorkflowHostLike) -> int:
    """Run the optional Textual UI; imports remain lazy for offline/model tests."""
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical
        from textual.widgets import Footer, Header, Label, ListItem, ListView, Static, TabbedContent, TabPane
    except (ImportError, ModuleNotFoundError) as error:
        raise RuntimeError("the Workflow TUI is unavailable; install evoctl[tui]") from error

    class WorkflowApp(App[None]):
        BINDINGS = [
            ("ctrl+n", "new_workflow", "New workflow"), ("ctrl+k", "close_workflow", "Close tab"),
            ("ctrl+left", "previous_tab", "Previous tab"), ("ctrl+right", "next_tab", "Next tab"),
            ("ctrl+[", "previous_tab", "Previous tab"), ("ctrl+]", "next_tab", "Next tab"),
        ]
        CSS = """
        #top-tabs { height: 3; }
        #main { height: 1fr; }
        .pane { border: solid $surface; padding: 1; }
        #drawer { height: 7; border-top: solid $surface; }
        """

        def __init__(self):
            super().__init__()
            self.workspace = WorkflowWorkspace(host)

        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            yield Static("", id="top-tabs")
            with Horizontal(id="main"):
                yield ListView(id="library", classes="pane")
                yield ListView(id="procedure", classes="pane")
                with Vertical(classes="pane"):
                    yield Static("", id="session")
                    with TabbedContent("Step", "Action", "API", "CLI", "Raw", id="representations"):
                        for mode in ("Step", "Action", "API", "CLI", "Raw"):
                            yield TabPane(Static(""), title=mode, id=f"representation-{mode.lower()}")
            yield Static("", id="drawer")
            yield Footer()

        def on_mount(self) -> None:
            self.refresh_view()

        def refresh_view(self) -> None:
            tabs = "  ".join(f"[{tab.snapshot.status_glyph} {tab.snapshot.title}]" for tab in self.workspace.tabs)
            self.query_one("#top-tabs", Static).update(tabs)
            tab = self.workspace.current
            self.query_one("#session", Static).update(f"{tab.snapshot.status_glyph} {tab.snapshot.title}\n{tab.snapshot.progress}  lease={tab.snapshot.lease}")
            self.query_one("#drawer", Static).update("Drawer: " + ("open" if self.workspace.drawer_open else "collapsed"))

        def action_previous_tab(self) -> None:
            self.workspace.cycle_tab(-1); self.refresh_view()

        def action_next_tab(self) -> None:
            self.workspace.cycle_tab(1); self.refresh_view()

        def action_new_workflow(self) -> None:
            values = self.workspace.workflows()
            if values:
                item = values[0]
                self.workspace.open_workflow(getattr(item, "id", None) or item["id"])
                self.refresh_view()

        def action_close_workflow(self) -> None:
            if self.workspace.close_current() is CloseDecision.RETURN:
                self.notify("Procedure is still active; abort explicitly to close", severity="warning")
            self.refresh_view()

    WorkflowApp().run()
    return 0
