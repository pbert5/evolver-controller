# metactl operator TUI

`metactl tui` is the human operator console for the central Meta Ball
control plane. It is intentionally distinct from `metactl api tui`, which is
the developer/API Workbench.

> `metactl tui` is the operator console. The developer/API Workbench remains
> separately addressable as `metactl api tui`. `metactl doctor` is the
> read-only diagnostic workflow for target, discovery, and catalog drift.

## Startup contract

Normal use must not require the operator to discover the server URL or choose
between repository and live modes.

`metactl tui` should:

1. resolve the central target through the shared
   [Operator Bootstrap](../_concepts/operator-bootstrap.md);
2. show the resolved target and connection state in the header;
3. perform a bounded read-only connection/discovery probe;
4. make live central projections available through the selected read actions
   when the target is available;
5. show a specific repair path when the managed target is unavailable;
6. never silently fall back to offline repository browsing and make the user
   think they are viewing live state.

The local catalog is only a form and navigation description until `/api/actions`
discovery succeeds. An unavailable, unauthorized, or forbidden discovery keeps
actions unavailable. When the gateway supplies a catalog version, the TUI also
compares its action IDs and version with the local catalog; drift is an explicit
gate and never a reason to invoke a stale contract. Configured authentication is
shown as configuration only, not as proof that authentication succeeded.

An explicit `--server` override may be supported for unusual deployments, but
it should flow into the same transport/session machinery rather than creating a
TUI-only client.

## Information architecture

The main navigation should be operator nouns, not HTTP endpoints:

```text
Overview
Controllers
Instruments
Runs
Experiments
Releases
Recovery
Developer
  API Workbench
```

The current TUI is an action browser, not a composite dashboard. Each section
contains the implemented action entries present in the shared presentation
model. Selecting an entry shows its title, human CLI path, stable action ID,
catalog status, safety metadata, and catalog-defined parameter form. Results
are displayed as the redacted response returned by the central transport.

The sections currently map to these executable projections:

- `Controllers`: controller list/show, freshness, refresh/rescan, release
  assignment, commands, and recovery actions. Commands and recovery are
  grouped under their own top-level sections only where the presentation model
  places them there.
- `Instruments`: instrument list/show actions.
- `Runs`: run list/show and the cataloged pause/resume/stop actions. Run
  revisions are supplied through the action's `expected_revision` parameter;
  the TUI does not synthesize or display a separate revision dashboard.
- `Releases`: the cataloged release action(s), currently release build.
- `Recovery`: controller recovery request/status/diff actions.
- `Overview` and `Experiments`: their cataloged actions, including planned
  experiment actions when present.

These entries query or mutate one selected action at a time. The TUI does not
currently assemble a controller or run view containing freshness, release,
instruments, current run, commands, recovery state, revisions, or valid
actions in one screen. Use the individual actions (or the equivalent CLI
commands) for those projections.

Planned catalog actions may be discoverable, but are visibly marked
`planned / unavailable` and never dispatch.

Form values are converted and checked from the catalog fields themselves:
`required`, `type`, `default`, and `enum` are applied before transport dispatch.
The resulting request uses the same stable action ID and shared transport as
the CLI. Results from read actions represent central projections, not an
offline cache; the current TUI does not provide aggregate controller/run
views.

## Interaction model

The current interaction model is deliberately limited to the supported
Textual controls:

- select a navigation entry and press Enter to show its action form;
- enter values using the catalog parameter types, defaults, required fields,
  and enums;
- press Run to dispatch an implemented action after a clean live discovery
  gate;
- confirm the action ID in the modal for actions whose catalog safety metadata
  requires confirmation;
- select `Open API Workbench` to see the separate Workbench route.

Search, contextual help, refresh, CLI copy, and API-context shortcut keys are
not currently implemented by this application and are not part of its
contract.

Mutation and hardware actions must open an explicit action form and use catalog
safety metadata. There should be no single-key mutation that bypasses review of
parameters and confirmation.

## Current layout

The screen has a header, a connection/status line, a grouped navigation tree,
an action detail/parameter pane, a Run button, and a footer. The detail pane
starts with guidance to use `metactl <noun> <action>` or
`metactl api tui`; it is not a live aggregate of central entities. Exact
colors and spacing may adapt to Textual and terminal width. The hierarchy,
connection truthfulness, action visibility, and safety semantics are the
contract.

## Safety modes

The operator TUI starts in read-oriented `SAFE` behavior. Client-side mode is a
UI guardrail only. Server authorization, revision/generation fencing, leases,
and physical interlocks remain authoritative. See
[Safety Mode](../_concepts/safety-mode.md).

The TUI must distinguish accepted/queued command state from completed physical
behavior. See [Command Disposition](../_concepts/command-disposition.md) and
[Physical Evidence](../_concepts/physical-evidence.md).

## Relationship to the API Workbench

The existing API Workbench stays available at:

```text
metactl api tui
```

The operator TUI may expose a developer action that shows the exact Workbench
command or context for the selected action. It should not duplicate Workbench
features such as raw headers, OpenAPI import, route audit, fixture execution,
or evidence-suite controls.

## Testable acceptance

Headless Textual tests should prove at least:

- startup shows the resolved target and does not silently use offline mode;
- navigation groups operator nouns, not raw route trees;
- selecting a controller action exposes its catalog form, human CLI path, and
  stable action ID;
- planned actions are visible but not executable;
- a read action dispatches through the shared transport;
- a mutation requires the catalog-defined confirmation path;
- the displayed human path comes from the shared presentation model;
- queued/accepted responses are not labeled physical success;
- no real hardware is required for tests.

## Related

- [Quickstart](quickstart.md)
- [CLI](cli.md)
- [Troubleshooting](troubleshooting.md)
- [Operator Bootstrap](../_concepts/operator-bootstrap.md) `[[Operator Bootstrap]]`
- [Safety Mode](../_concepts/safety-mode.md) `[[Safety Mode]]`
- [API Workbench](../_concepts/api-workbench.md) `[[API Workbench]]`
