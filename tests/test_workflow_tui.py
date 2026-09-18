from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from meta_webui_application_backend.evolver_edge.workflow_tui import (
    CloseDecision,
    FakeWorkflowHost,
    WorkflowSnapshot,
    WorkflowWorkspace,
    create_textual_app,
    semantic_status,
)


@dataclass
class FakeSession:
    snapshot: WorkflowSnapshot
    advances: int = 0
    inputs: list[tuple[str, object]] | None = None
    aborted: bool = False

    def __post_init__(self):
        self.inputs = []

    def snapshot_for_ui(self):
        return self.snapshot

    def provide_parameter(self, name, value):
        self.inputs.append((name, value))

    def advance(self):
        self.advances += 1

    def abort(self, reason):
        self.aborted = True


def _snapshot(*, attention: str | None = None, state: str = "READY"):
    return WorkflowSnapshot.from_mapping({
        "workflow_id": "temp-cal",
        "title": "Temperature Calibration",
        "status": state,
        "attention": ([attention] if attention else []),
        "progress": "1 / 4",
        "lease": "ACTIVE",
        "procedures": [{
            "id": "setup",
            "title": "Setup",
            "status": "CURRENT" if state == "RUNNING" else "COMPLETED",
            "steps": [{"id": "input", "title": "Reference temperature", "status": "ATTENTION" if attention else "READY", "attention": attention or "", "representation": {"Step": "Enter reference temperature", "Action": "request_observation"}}],
        }],
        "selected_step": "input",
        "representations": {"Step": "Enter reference temperature", "Action": "request_observation", "API": "POST /observations", "CLI": "evoctl workflow observe", "Raw": '{"id":"input"}'},
        "drawer": {"Info": "A reference observation", "Inputs": "reference_temperature: draft", "Safety": "lease ACTIVE", "Evidence": "protocol: pending", "Outputs": "none", "Events": "step_started"},
    })


def test_status_grammar_keeps_attention_and_domain_semantic():
    assert semantic_status("RUNNING", domain="temperature") == "● 🌡"
    assert semantic_status("RUNNING", attention=("observation",), domain="temperature") == "● !🔎 🌡"
    assert semantic_status("SUCCEEDED") == "■✓"
    assert semantic_status("ABORTED", abort_kind="operator") == "■👤C"


def test_library_open_creates_independent_tabs_without_advancing():
    first = FakeSession(_snapshot())
    second = FakeSession(_snapshot())
    host = FakeWorkflowHost([{"id": "temp-cal", "title": "Temperature Calibration"}], {"temp-cal": [first, second]})
    workspace = WorkflowWorkspace(host)

    workspace.open_workflow("temp-cal")
    workspace.open_workflow("temp-cal")

    assert workspace.tab_ids == ["library", "temp-cal", "temp-cal-2"]
    assert first.advances == second.advances == 0


def test_save_only_does_not_advance_but_confirm_does():
    session = FakeSession(_snapshot(attention="observation"))
    workspace = WorkflowWorkspace(FakeWorkflowHost([], {"temp-cal": [session]}))
    workspace.open_workflow("temp-cal")

    workspace.save_inputs("temp-cal", {"reference_temperature": "31.42"})
    assert session.inputs == [("reference_temperature", "31.42")]
    assert session.advances == 0
    workspace.confirm_inputs("temp-cal")
    assert session.advances == 1


def test_close_live_session_requires_explicit_abort_and_never_detaches():
    session = FakeSession(_snapshot(state="RUNNING"))
    workspace = WorkflowWorkspace(FakeWorkflowHost([], {"temp-cal": [session]}))
    workspace.open_workflow("temp-cal")

    assert workspace.close_current() == CloseDecision.RETURN
    assert workspace.close_current(abort=True) == CloseDecision.CLOSED
    assert session.aborted is True


@pytest.mark.parametrize("mode", ["Step", "Action", "API", "CLI", "Raw"])
def test_inspector_modes_are_projections_of_same_selected_step(mode):
    session = FakeSession(_snapshot())
    workspace = WorkflowWorkspace(FakeWorkflowHost([], {"temp-cal": [session]}))
    workspace.open_workflow("temp-cal")
    assert workspace.inspector(mode) == session.snapshot.representations[mode]


def _pilot_host(session):
    return FakeWorkflowHost(
        [{"id": "temp-cal", "title": "Temperature Calibration"},
         {"id": "pump-cal", "title": "Pump Flow Calibration"}],
        {"temp-cal": [session], "pump-cal": [FakeSession(_snapshot())]},
    )


def test_rendered_pilot_selector_search_and_independent_top_tab():
    session = FakeSession(_snapshot())
    app = create_textual_app(_pilot_host(session))

    async def exercise():
        async with app.run_test() as pilot:
            await pilot.press("ctrl+n")
            search = app.query_one("#workflow-search")
            search.value = "pump"
            await pilot.pause()
            assert len(app.query("#choice-pump-cal")) == 1
            await pilot.press("enter")
            assert app.workspace.tab_ids == ["library", "pump-cal"]
            await pilot.press("ctrl+n")
            await pilot.press("escape")
            assert app.workspace.tab_ids == ["library", "pump-cal"]

    asyncio.run(exercise())


def test_rendered_pilot_input_has_save_only_and_confirm_continue():
    session = FakeSession(_snapshot(attention="observation"))
    snapshot = session.snapshot
    session.snapshot = WorkflowSnapshot.from_mapping({
        **snapshot.__dict__,
        "drawer": {**snapshot.drawer, "Input schema": [{"name": "reference", "label": "Reference", "type": "number"}]},
    })
    app = create_textual_app(_pilot_host(session))

    async def exercise():
        async with app.run_test() as pilot:
            await pilot.press("ctrl+n"); await pilot.press("enter"); await pilot.press("i")
            assert app.query_one("#save-only") and app.query_one("#confirm-continue")
            field = app.query_one("#input-reference")
            field.value = "31.42"
            await pilot.click("#save-only")
            assert session.advances == 0 and session.inputs == [("reference", "31.42")]
            await pilot.press("i")
            await pilot.click("#confirm-continue")
            assert session.advances == 1

    asyncio.run(exercise())


def test_rendered_pilot_drawer_tabs_and_safe_close_prompt():
    session = FakeSession(_snapshot(state="RUNNING"))
    app = create_textual_app(_pilot_host(session))

    async def exercise():
        async with app.run_test() as pilot:
            await pilot.press("ctrl+n"); await pilot.press("enter")
            await pilot.press("d")
            assert len(app.query("#drawer-value-safety")) == 1
            await pilot.press("ctrl+k")
            assert len(app.query("#close-modal")) == 1
            await pilot.click("#abort-close")
            assert session.aborted is True
            assert app.workspace.tab_ids == ["library"]

    asyncio.run(exercise())


def test_rendered_pilot_repeatable_add_instance_delegates_to_host():
    class AddSession(FakeSession):
        def __init__(self, snapshot):
            super().__init__(snapshot)
            self.created = []

        def add_instance(self, stage_id, values):
            self.created.append((stage_id, values))

    session = AddSession(WorkflowSnapshot.from_mapping({
        "workflow_id": "temp-cal", "title": "Temperature Calibration", "status": "READY",
        "procedures": [{"id": "points", "title": "Calibration Points", "cardinality": "repeatable",
                         "parameters": [{"name": "point", "label": "Point", "type": "integer"}]}],
    }))

    class AddHost(FakeWorkflowHost):
        def add_stage_instance(self, active_session, stage_id, values):
            active_session.add_instance(stage_id, values)

    app = create_textual_app(AddHost([{"id": "temp-cal", "title": "Temperature Calibration"}], {"temp-cal": [session]}))

    async def exercise():
        async with app.run_test() as pilot:
            await pilot.press("ctrl+n"); await pilot.press("enter"); await pilot.press("a")
            assert app.query_one("#instance-modal")
            app.query_one("#instance-point").value = "2"
            await pilot.click("#create-instance")
            assert session.created == [("points", {"point": "2"})]

    asyncio.run(exercise())
