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

Offline reads are deliberately separate from live operation and are outside
the fixed lifecycle adapter. Direct `evoctl --offline ...` is rejected by the
normal edge launcher. Offline output must be labelled as offline and cannot be
used as evidence of current central state or physical hardware.

## Runtime lifecycle and upgrade modes

The edge lifecycle aliases delegate to the fixed host-runtime adapter:

```text
evoctl runtime status|up|stop|down|restart|logs|upgrade
evoctl up|down|restart|logs|upgrade
metactl server status|up|stop|down|restart|logs|upgrade
```

`evoctl update apply RELEASE` installs an explicit governed release, while
`evoctl upgrade` selects the configured recommended governed release. Neither
command performs a Git checkout update. The developer-only
`tools/evolver-edge upgrade` command is the source-checkout fast-forward,
submodule-sync, rebuild, and health-verification path. Central
`metactl server upgrade` remains unavailable until a governed central release
selector is configured.

`stop` retains service containers and `down` removes the Compose runtime while
preserving durable state and named volumes. Lifecycle commands accept only the
fixed service allowlist and do not expose project, path, shell, container-ID,
Docker-socket, firmware, or physical-actuation authority.

## Safety boundary

`metactl` is a client of the central operator API. It must not open the
controller database, SSH into controllers as an implementation shortcut, or
bypass server authorization. `evoctl` is local to a controller and must not
become a central fleet administrator.

A queued or accepted command is not proof of physical success. Read
[Command Disposition](_concepts/command-disposition.md) and
[Physical Evidence](_concepts/physical-evidence.md) before interpreting an
actuation or hardware result.

Safe-stop remains an unresolved product decision. This path may record a
safe-stop intent, but must not present that intent as a physically completed
stop or imply whether the eventual policy is lease-free or lease-bound.

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
