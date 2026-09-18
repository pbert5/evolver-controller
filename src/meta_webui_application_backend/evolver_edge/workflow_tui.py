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
CONNECTIVITY_GLYPHS = {"connected": "↔", "online": "↔", "degraded": "⚠", "offline": "×"}


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def semantic_status(status: str, *, attention: tuple[str, ...] = (), domain: str | None = None,
                    abort_kind: str | None = None, saved: bool = False, dirty: bool = False,
                    connectivity: str | None = None) -> str:
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
    if connectivity in CONNECTIVITY_GLYPHS:
        parts.append(CONNECTIVITY_GLYPHS[connectivity])
    if saved:
        parts.append("💾")
    if dirty:
        parts.append("*")
    return " ".join(parts)


def semantic_copy(value: Any) -> str:
    """Return stable plain text for Ctrl+Shift+C and SSH/headless use."""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return "\n".join(f"{key}: {semantic_copy(item)}" for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return "\n".join(semantic_copy(item) for item in value)
    return str(value)


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
                                dirty=self.metadata.get("dirty", False), connectivity=self.metadata.get("connectivity"))


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
            session = self.host.new_session(tab.workflow)
            tab.session = session if hasattr(session, "snapshot_for_ui") else RuntimeSessionAdapter(session, tab.workflow)
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

    def toggle_drawer(self) -> bool:
        self.drawer_open = not self.drawer_open
        return self.drawer_open

    def copy_focused(self, value: Any | None = None) -> str:
        return semantic_copy(self.inspector() if value is None else value)

    def set_representation(self, mode: str) -> None:
        if mode not in {"Step", "Action", "API", "CLI", "Raw"}:
            raise ValueError(mode)
        self.representation = mode

    def set_drawer_view(self, view: str) -> None:
        if view not in {"Info", "Inputs", "Safety", "Evidence", "Outputs", "Events"}:
            raise ValueError(view)
        self.drawer_view = view
        self.drawer_open = True

    def add_instance(self, tab_id: str, stage_id: str, values: Mapping[str, Any]) -> Any:
        """Delegate repeatable-stage creation; UI owns no cardinality rules."""
        tab = self._tab(tab_id)
        if tab.session is None:
            raise ValueError("session has not been started")
        add = getattr(self.host, "add_stage_instance", None)
        if add is None:
            add = getattr(tab.session, "add_instance", None)
        if add is None:
            raise ValueError("stage instances are unavailable")
        return add(tab.session, stage_id, values) if callable(getattr(self.host, "add_stage_instance", None)) else add(stage_id, values)

    def input_schema(self) -> tuple[Mapping[str, Any], ...]:
        """Return the session-projected fields without interpreting them."""
        value = self.current.snapshot.drawer.get("Input schema", ())
        return tuple(value) if isinstance(value, (list, tuple)) else ()

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


def create_textual_app(host: WorkflowHostLike):
    """Create the real workflow app; imports stay lazy for model-only installs."""
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical, Container
        from textual.widgets import (Button, Footer, Header, Input, Label, ListItem,
                                      ListView, Static, Tab, TabbedContent, TabPane, Tree)
        from textual.screen import ModalScreen
    except (ImportError, ModuleNotFoundError) as error:
        raise RuntimeError("the Workflow TUI is unavailable; install evoctl[tui]") from error

    class ChoiceModal(ModalScreen[str | None]):
        """Searchable workflow selector. Selection only creates an unstarted tab."""
        def __init__(self, workspace: WorkflowWorkspace):
            super().__init__()
            self.workspace = workspace

        def compose(self) -> ComposeResult:
            with Container(id="workflow-selector"):
                yield Label("New Workflow")
                yield Input(placeholder="Search workflows", id="workflow-search")
                yield ListView(id="workflow-choices")
                yield Label("Enter Open · Esc Cancel", id="selector-help")

        async def on_mount(self) -> None:
            await self._refresh()
            self.query_one("#workflow-search", Input).focus()

        async def _refresh(self) -> None:
            choices = self.query_one("#workflow-choices", ListView)
            await choices.remove_children()
            for item in self.workspace.workflows(self.query_one("#workflow-search", Input).value if self.is_mounted else ""):
                ident = str(_field(item, "id", ""))
                choices.append(ListItem(Label(str(_field(item, "title", ident))), id=f"choice-{ident}"))

        async def on_input_changed(self, event: Input.Changed) -> None:
            if event.input.id == "workflow-search":
                await self._refresh()
                self.query_one("#workflow-search", Input).focus()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id == "workflow-search":
                self._choose_first()

        def _choose_first(self) -> None:
            choices = self.query_one("#workflow-choices", ListView)
            item = choices.highlighted_child or (choices.children[0] if choices.children else None)
            if item is not None:
                self.dismiss((item.id or "").removeprefix("choice-"))

        def on_key(self, event: Any) -> None:
            if event.key == "enter":
                self._choose_first()
                event.stop()

        def on_list_view_selected(self, event: ListView.Selected) -> None:
            ident = (event.item.id or "").removeprefix("choice-")
            if ident:
                self.dismiss(ident)

        def key_enter(self) -> None:
            choices = self.query_one("#workflow-choices", ListView)
            item = choices.highlighted_child or (choices.children[0] if choices.children else None)
            if item is not None:
                self.dismiss((item.id or "").removeprefix("choice-"))

        def key_escape(self) -> None:
            self.dismiss(None)

    class InputModal(ModalScreen[tuple[str, Mapping[str, str]] | None]):
        """Typed operator-input surface with deliberately separate save/continue."""
        def __init__(self, workspace: WorkflowWorkspace, tab: WorkflowTab):
            super().__init__()
            self.workspace, self.tab = workspace, tab

        def compose(self) -> ComposeResult:
            with Container(id="input-modal"):
                yield Label("Operator Input", id="input-title")
                schema = self.tab.snapshot.drawer.get("Input schema", ())
                fields = schema if isinstance(schema, (list, tuple)) else ()
                if not fields:
                    fields = ({"name": "value", "label": "Value", "type": "text"},)
                for field in fields:
                    name = str(field.get("name", "value"))
                    yield Label(f"{field.get('label', name)} ({field.get('type', 'text')})")
                    yield Input(id=f"input-{name}", name=name, value=str(field.get("value", "")))
                with Horizontal(id="input-actions"):
                    yield Button("Save only", id="save-only")
                    yield Button("Confirm + Continue", id="confirm-continue", variant="primary")
                    yield Button("Cancel", id="cancel-input")

        def _values(self) -> dict[str, str]:
            return {field.name: field.value for field in self.query("Input") if field.name}

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "cancel-input":
                self.dismiss(None)
            elif event.button.id == "save-only":
                self.dismiss(("save", self._values()))
            elif event.button.id == "confirm-continue":
                self.dismiss(("confirm", self._values()))

    class CloseModal(ModalScreen[bool | None]):
        def compose(self) -> ComposeResult:
            with Container(id="close-modal"):
                yield Label("Procedure is still active. Abort safely and close?")
                with Horizontal():
                    yield Button("Return to procedure", id="return-close")
                    yield Button("Abort procedure safely and close", id="abort-close", variant="error")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            self.dismiss(event.button.id == "abort-close")

    class InstanceModal(ModalScreen[tuple[str, str, Mapping[str, str]] | None]):
        """Form for one repeatable stage; validation/cardinality remain host-owned."""
        def __init__(self, tab: WorkflowTab, stage_id: str, fields: tuple[Mapping[str, Any], ...]):
            super().__init__()
            self.tab, self.stage_id, self.fields = tab, stage_id, fields

        def compose(self) -> ComposeResult:
            with Container(id="instance-modal"):
                yield Label(f"Add Instance · {self.stage_id}")
                for field in self.fields or ({"name": "value", "label": "Value"},):
                    name = str(field.get("name", "value"))
                    yield Label(str(field.get("label", name)))
                    yield Input(id=f"instance-{name}", name=name, placeholder=str(field.get("type", "text")))
                with Horizontal():
                    yield Button("Create instance", id="create-instance", variant="primary")
                    yield Button("Cancel", id="cancel-instance")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "cancel-instance":
                self.dismiss(None)
            elif event.button.id == "create-instance":
                self.dismiss((self.stage_id, "create", {field.name: field.value for field in self.query("Input") if field.name}))

    class WorkflowApp(App[None]):
        BINDINGS = [
            ("ctrl+n", "new_workflow", "New workflow"), ("ctrl+k", "close_workflow", "Close tab"),
            ("ctrl+left", "previous_tab", "Previous tab"), ("ctrl+right", "next_tab", "Next tab"),
            ("ctrl+[", "previous_tab", "Previous tab"), ("ctrl+]", "next_tab", "Next tab"),
            ("ctrl+shift+c", "copy_focused", "Copy semantic content"),
            ("i", "open_input", "Operator input"), ("a", "add_instance", "Add instance"),
            ("d", "toggle_drawer", "Details"),
        ]
        CSS = """
        #top-tabs { height: 3; border: solid $surface; padding: 1; }
        #main { height: 1fr; }
        .pane { border: solid $surface; padding: 1; width: 1fr; }
        #session { height: 6; }
        #drawer { height: 9; border-top: solid $surface; padding: 1; }
        #workflow-selector, #input-modal, #instance-modal, #close-modal { width: 70; height: auto; max-height: 80%; padding: 1 2; border: thick $accent; background: $surface; }
        #workflow-choices { height: 1fr; min-height: 5; }
        #input-actions { height: 3; align: center middle; }
        """

        def __init__(self):
            super().__init__()
            self.workspace = WorkflowWorkspace(host)

        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            yield Static("", id="top-tabs")
            with Horizontal(id="main"):
                yield ListView(id="library", classes="pane")
                yield Tree("Procedure", id="procedure", classes="pane")
                with Vertical(classes="pane"):
                    yield Static("", id="session")
                    with TabbedContent(id="representations"):
                        for mode in ("Step", "Action", "API", "CLI", "Raw"):
                            with TabPane(mode, id=f"representation-{mode.lower()}"):
                                yield Static("", id=f"representation-value-{mode.lower()}")
            with TabbedContent(id="drawer-tabs"):
                for view in ("Info", "Inputs", "Safety", "Evidence", "Outputs", "Events"):
                    with TabPane(view, id=f"drawer-{view.lower()}"):
                        yield Static("", id=f"drawer-value-{view.lower()}")
            yield Footer()

        def on_mount(self) -> None:
            self.refresh_view()

        def on_key(self, event: Any) -> None:
            # Modal input retains focus while the filtered list is rebuilt.
            # Handle Enter at the app boundary so keyboard selection remains
            # deterministic across Textual versions.
            if event.key == "enter" and isinstance(self.screen, ChoiceModal):
                self.screen._choose_first()
                event.stop()

        def refresh_view(self) -> None:
            tabs = "  ".join(f"{'▶ ' if i == self.workspace.active_index else ''}{tab.snapshot.status_glyph} {tab.snapshot.title} · {tab.snapshot.metadata.get('target', '')}" for i, tab in enumerate(self.workspace.tabs))
            self.query_one("#top-tabs", Static).update(tabs)
            tab = self.workspace.current
            library = self.query_one("#library", ListView)
            library.clear()
            if tab.tab_id == "library":
                for item in self.workspace.workflows():
                    workflow_id = _field(item, "id", "")
                    library.append(ListItem(Label(f"○ {_field(item, 'title', workflow_id)}"), id=f"workflow-{workflow_id}"))
            else:
                library.append(ListItem(Label(f"{tab.snapshot.status_glyph} {tab.snapshot.title}")))
            procedure = self.query_one("#procedure", Tree)
            procedure.clear()
            if tab.tab_id == "library":
                procedure.root.add("Select a workflow")
            else:
                procedure.root.add("⚙ Initial Parameters", data={"id": "initial-parameters"})
                for procedure_data in tab.snapshot.procedures:
                    node = procedure.root.add(f"{procedure_data.get('status', '○')} {procedure_data.get('title', procedure_data.get('id', 'Procedure'))}", data=procedure_data)
                    for step in procedure_data.get("steps", ()):
                        node.add(f"  {step.get('status', '○')} {step.get('title', step.get('id', 'Step'))}", data=step)
            correction = semantic_copy(tab.snapshot.correction) if tab.snapshot.correction else "none"
            history = tab.snapshot.metadata.get("history", "session-local")
            self.query_one("#session", Static).update(
                f"{tab.snapshot.status_glyph} {tab.snapshot.title}\n"
                f"Target: {tab.snapshot.metadata.get('target', 'unknown')}  "
                f"connectivity={tab.snapshot.metadata.get('connectivity', 'unknown')}  "
                f"{tab.snapshot.progress}  lease={tab.snapshot.lease}\n"
                f"Correction/retry: {correction}  history: {history}")
            for mode in ("Step", "Action", "API", "CLI", "Raw"):
                self.query_one(f"#representation-value-{mode.lower()}", Static).update(semantic_copy(tab.snapshot.representations.get(mode, "Not available")))
            for view in ("Info", "Inputs", "Safety", "Evidence", "Outputs", "Events"):
                value = tab.snapshot.drawer.get(view, "Not available") if self.workspace.drawer_open else "Drawer collapsed (press d to open)"
                self.query_one(f"#drawer-value-{view.lower()}", Static).update(semantic_copy(value))
            self.query_one("#drawer-tabs", TabbedContent).active = f"drawer-{self.workspace.drawer_view.lower()}"

        def action_previous_tab(self) -> None:
            self.workspace.cycle_tab(-1); self.refresh_view()

        def action_next_tab(self) -> None:
            self.workspace.cycle_tab(1); self.refresh_view()

        def action_new_workflow(self) -> None:
            def opened(workflow_id: str | None) -> None:
                if workflow_id:
                    self.workspace.open_workflow(workflow_id)
                    self.refresh_view()
            self.push_screen(ChoiceModal(self.workspace), opened)

        def on_list_view_selected(self, event: Any) -> None:
            item_id = getattr(event.item, "id", "") or ""
            if item_id.startswith("workflow-"):
                self.workspace.open_workflow(item_id.removeprefix("workflow-"))
                self.refresh_view()

        def action_close_workflow(self) -> None:
            if self.workspace.current.snapshot.status.upper() in {"RUNNING", "WAITING", "PAUSED"}:
                self.push_screen(CloseModal(), self._close_decision)
            else:
                self.workspace.close_current()
                self.refresh_view()

        def _close_decision(self, abort: bool | None) -> None:
            if abort:
                self.workspace.close_current(abort=True)
                self.refresh_view()

        def action_toggle_drawer(self) -> None:
            self.workspace.toggle_drawer(); self.refresh_view()

        def action_open_input(self) -> None:
            tab = self.workspace.current
            if tab.tab_id != "library":
                def done(result):
                    if result:
                        action, values = result
                        self.workspace.save_inputs(tab.tab_id, values)
                        if action == "confirm":
                            self.workspace.confirm_inputs(tab.tab_id)
                        self.refresh_view()
                self.push_screen(InputModal(self.workspace, tab), done)

        def action_add_instance(self) -> None:
            tab = self.workspace.current
            if tab.tab_id == "library" or tab.session is None:
                return
            procedures = tab.snapshot.procedures
            candidate = next((item for item in procedures if item.get("cardinality") == "repeatable" or item.get("can_add")), None)
            if candidate is None:
                self.notify("No repeatable stage is available", severity="warning")
                return
            stage_id = str(candidate.get("id", candidate.get("stage_id", "")))
            fields = tuple(candidate.get("parameters", candidate.get("instance_parameters", ())))
            def added(result):
                if result:
                    try:
                        self.workspace.add_instance(tab.tab_id, result[0], result[2])
                    except Exception as error:
                        self.notify(str(error), severity="error")
                    self.refresh_view()
            self.push_screen(InstanceModal(tab, stage_id, fields), added)

        def action_copy_focused(self) -> None:
            value = self.workspace.copy_focused()
            try:
                self.copy_to_clipboard(value)
            except Exception:
                pass
            self.notify("Copied semantic content", severity="information")

        def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
            tab_id = event.pane.id or ""
            if tab_id.startswith("representation-"):
                self.workspace.set_representation(tab_id.removeprefix("representation-").title())
            elif tab_id.startswith("drawer-"):
                self.workspace.set_drawer_view(tab_id.removeprefix("drawer-").title())

    return WorkflowApp()


def run_textual(host: WorkflowHostLike) -> int:
    """Run the optional Textual UI; imports remain lazy for model-only tests."""
    try:
        app = create_textual_app(host)
    except (ImportError, ModuleNotFoundError) as error:
        raise RuntimeError("the Workflow TUI is unavailable; install evoctl[tui]") from error
    app.run()
    return 0
