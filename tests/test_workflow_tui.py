from __future__ import annotations

from dataclasses import dataclass

import pytest

from meta_webui_application_backend.evolver_edge.workflow_tui import (
    CloseDecision,
    FakeWorkflowHost,
    WorkflowSnapshot,
    WorkflowWorkspace,
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
