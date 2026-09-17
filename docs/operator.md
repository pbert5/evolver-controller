# Operator guide

This is the entry point for operating Meta Ball and eVOLVER. Pick the tool by
where the operation belongs, not by which executable happens to be convenient.

| Goal | Tool | Scope |
|---|---|---|
| Inspect or change central controller, instrument, run, experiment, release, or recovery state | `metactl` | Central control plane |
| Browse and operate the central system interactively | `metactl tui` | Central operator TUI |
| Inspect API contracts, drift, fixtures, evidence, or raw requests | `metactl api tui` | Developer/API Workbench |
| Inspect or recover one controller locally | `evoctl` | Edge controller |

For central operation, start with [metactl quickstart](metactl/quickstart.md).
The target operator TUI is described in [metactl TUI](metactl/tui.md), while
command-line usage is described in [metactl CLI](metactl/cli.md). If a normal
operator path fails, use [metactl troubleshooting](metactl/troubleshooting.md)
before dropping into the API Workbench.

For local controller work, use [evoctl](evoctl.md). Central and edge state are
intentionally different responsibilities; see
[Central vs Edge](_concepts/central-vs-edge.md).

Normal commands are live commands. They use the local operator service and
never silently fall back to a direct SQLite read:

`evoctl -> operator.sock -> controller -> hardware.sock -> hardware -> serial`

If the operator service is stopped or unreachable, the CLI reports that state
and points to `tools/evolver-edge up`, `tools/evolver-edge status`, and
`tools/evolver-edge logs controller`. The edge launcher returns an unavailable
exit status instead of presenting stale local data as live state.

Offline mode is an intentional rescue/maintenance mode. It reads the durable
controller store without contacting the operator socket and does not prove
central state or physical hardware was observed. Use the explicit route when
the controller service is stopped:

```text
tools/evolver-edge rescue recovery
tools/evolver-edge rescue export-state recovery.tar.zst
```

Inside the edge container, `evoctl rescue ...` delegates to that host helper;
it never reads the local controller store. Direct `evoctl --offline ...` is
rejected with the same canonical rescue guidance.
Recovery/planning commands include `recovery`, `export-state`,
`lifecycle-plan`, and `update status`; offline output must be labelled as
offline by the operator.

## Safety boundary

`metactl` is a client of the central operator API. It must not open the
controller database, SSH into controllers as an implementation shortcut, or
bypass server authorization. `evoctl` is local to a controller and must not
become a central fleet administrator.

A queued or accepted command is not proof of physical success. Read
[Command Disposition](_concepts/command-disposition.md) and
[Physical Evidence](_concepts/physical-evidence.md) before interpreting an
actuation or hardware result.

## Cross-reference graph

Concept aliases for Obsidian-style navigation:

- `[[Central vs Edge]]`
- `[[Action Catalog]]`
- `[[Operator Bootstrap]]`
- `[[Human Command Path]]`
- `[[Safety Mode]]`
- `[[Command Disposition]]`
- `[[Physical Evidence]]`
- `[[API Workbench]]`

The concept definitions live under `docs/_concepts/` so primary operator docs
stay task-oriented instead of turning into a glossary.
