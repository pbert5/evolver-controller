# metactl operator TUI

`metactl tui` is the target human operator console for the central Meta Ball
control plane. It is intentionally distinct from `metactl api tui`, which is
the developer/API Workbench.

> Target-contract note: the pinned client currently maps `metactl tui` to the
> API Workbench. The follow-up implementation should move the API Workbench to
> the explicit `metactl api tui` path and make `metactl tui` the operator
> console described here.

## Startup contract

Normal use must not require the operator to discover the server URL or choose
between repository and live modes.

`metactl tui` should:

1. resolve the central target through the shared
   [Operator Bootstrap](../_concepts/operator-bootstrap.md);
2. show the resolved target and connection state in the header;
3. perform a bounded read-only connection/discovery probe;
4. load live central projections when the target is available;
5. show a specific repair path when the managed target is unavailable;
6. never silently fall back to offline repository browsing and make the user
   think they are viewing live state.

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

A representative controller view should expose current central projection,
freshness, release, instruments, current run, recent/queued commands, recovery
state, and the actions valid for that controller.

A representative run view should expose state, revision, assigned resources,
controller/instrument relationships, recent commands, and valid pause/resume/
stop actions.

Planned catalog actions may be discoverable, but must be visibly unavailable.
They must never dispatch simply because the TUI can render them.

## Interaction model

The baseline keyboard model should be small and teachable:

- `/`: focus search;
- `?`: open contextual help;
- `r`: refresh the current read projection;
- `c`: show/copy the equivalent human CLI command for the selected action;
- `a`: show the corresponding API Workbench command/context;
- `q`: quit.

Mutation and hardware actions must open an explicit action form and use catalog
safety metadata. There should be no single-key mutation that bypasses review of
parameters and confirmation.

## Suggested layout

```text
+ metactl | central: connected | operator: configured | SAFE ----------------+
| / search                                                ? help   q quit     |
+-------------------+----------------------------+----------------------------+
| NAVIGATION        | CONTROLLERS                | edge-01                    |
|                   |                            |                            |
| Overview          | * edge-01 healthy      4s  | Connected                  |
| Controllers       | * edge-02 healthy     12s  | Release 0.4.2              |
| Instruments       | o edge-03 offline     14m  | 2 instruments              |
| Runs              |                            | Run ALE-42                 |
| Experiments       |                            |                            |
| Releases          |                            | Actions                    |
| Recovery          |                            | > Refresh                  |
| Developer         |                            |   Rescan                   |
|   API Workbench   |                            |   Commands                 |
|                   |                            |   Recovery                 |
+-------------------+----------------------------+----------------------------+
| last: refresh queued | cmd-391 | press c for CLI, a for API context        |
+----------------------------------------------------------------------------+
```

Exact colors and spacing may adapt to Textual and terminal width. The hierarchy,
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
- selecting a controller exposes its central projection and valid actions;
- planned actions are visible but not executable;
- a read action dispatches through the shared transport;
- a mutation requires the catalog-defined confirmation path;
- copy/show command produces the same human path as CLI help;
- queued/accepted responses are not labeled physical success;
- no real hardware is required for tests.

## Related

- [Quickstart](quickstart.md)
- [CLI](cli.md)
- [Troubleshooting](troubleshooting.md)
- [Operator Bootstrap](../_concepts/operator-bootstrap.md) `[[Operator Bootstrap]]`
- [Safety Mode](../_concepts/safety-mode.md) `[[Safety Mode]]`
- [API Workbench](../_concepts/api-workbench.md) `[[API Workbench]]`
