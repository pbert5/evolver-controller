# evoctl

`evoctl` is the implemented controller-local operator CLI. Use it when you are
working on one controller and need local inspection, recovery, lifecycle, or
hardware-observation information. For central fleet operation, use
[metactl](metactl/README.md) instead.

In the eVOLVER Edge Dev Container run:

```text
evoctl ...
```

From the host use:

```text
tools/dev-env evolver-edge exec evoctl ...
```

Read-only inspection:

```text
evoctl status
evoctl binding
evoctl runs
evoctl instruments
evoctl doctor
```

`--offline` reads the durable controller store without contacting the local
operator socket. It does not prove central state or physical hardware was
observed. Recovery/planning commands include `recovery`, `export-state`,
`lifecycle-plan`, and `update status`.

## Native operator shell

`evoctl tui` opens one controller-native Textual application with these views:

```text
Overview | Controllers | Instruments | Runs | Recovery | Maintenance | Workflows
```

Use `evoctl tui --page <view>` to select the initial view, or
`evoctl tui --workflow` as the equivalent Workflows deep-link. `Ctrl+Left` /
`Ctrl+Right` and `Ctrl+[` / `Ctrl+]` move between views; `1` through `7`
select a view when a text field is not focused; `r` refreshes the current
read-only projection and `?` shows the key reference.

Live views use only the typed controller operator read contract. `--offline`
uses `OfflineTuiSource` and the durable edge store only when explicitly
selected. The native app factory is `create_app(source=..., workflow_host=...,
initial_view=...)`; this is the deterministic source seam for #132. No evoctl
TUI startup requires `app.yaml`, configured page YAML, a Meta WebUI compiler,
Meta WebUI Textual runtime, extension manifests, or Meta WebUI query
composition.

Workflows remain backed by the reviewed `WorkflowHost` and workspace model,
including repeatable instances, typed input, API/CLI representation mapping,
refresh coalescing, safe close, and active-instance inspection. The shell does
not add mutation controls to the other six views.

The controller owns durable edge state; the hardware daemon owns serial access
and observation state. Do not open serial devices or write the controller DB
from an operator script. Hardware observations are evidence across private IPC,
not identity or command authority. Enrollment, handoff, forced adoption,
release changes, uninstall, firmware upload, and actuation retain their
operator, confirmation, generation, lease, and physical-evidence checks.

## Workflow CLI

The workflow commands use the same trusted library, `WorkflowHost`, and
session runtime as the workflow UI:

```text
evoctl workflow list [--search TEXT]
evoctl workflow show WORKFLOW_ID
evoctl workflow preflight WORKFLOW_ID --target INSTRUMENT_ID --parameter name=value
evoctl workflow run WORKFLOW_ID --target INSTRUMENT_ID --parameter name=value
```

`preflight` performs read-only target/capability resolution and never invokes
an action. `run --jsonl` emits versioned, deterministic records with bounded
structural redaction; lease tokens, credentials, and raw unbounded responses
are not emitted. Ctrl+C during a run calls the runtime abort path and reports
the terminal cleanup outcome.

Product tests and preview tooling can use the side-effect-free scenario seam:

```python
from meta_webui_application_backend.evolver_edge.workflow_cli import ScenarioRegistry
host = ScenarioRegistry().host("waiting_for_input")
```

Scenario hosts use the public host/session contracts and an in-memory operator;
they do not open sockets, access stores, or touch hardware.

Central catalog entries marked `planned` are not callable capabilities;
experiment enqueue/run and run-start remain planned.

## Related

- [Operator guide](operator.md) `[[Operator Guide]]`
- [Central vs Edge](_concepts/central-vs-edge.md) `[[Central vs Edge]]`
- [Command Disposition](_concepts/command-disposition.md) `[[Command Disposition]]`
- [Physical Evidence](_concepts/physical-evidence.md) `[[Physical Evidence]]`
