# metactl operator experience design

**Date:** 2026-09-16

**Status:** approved design, documentation-first handoff

## Objective

Make `metactl` easy to discover and operate without requiring the user to learn
action IDs, API routes, Dev Container network topology, or manually wire the
TUI to the central stack.

The approved product split is:

```text
metactl
    normal central operator CLI

metactl tui
    normal interactive central operator console

metactl api ...
    API inspection, drift, fixtures, evidence, and developer diagnostics

metactl api tui
    existing advanced API Workbench

evoctl
    controller-local edge operation
```

## Verified starting state

The parent integration branch is
`finaly-actualy-interacting-with-the-evolver` at prompt-time commit
`608510e8209fe623784dfa2ec833980e4ada8690`.

It pins the `metactl` submodule at
`2e7bb589645dc65423ed7df8dcba8d2a055b40ac`.

The pinned client already has:

- validated application/action catalogs;
- stable action IDs with parameters, status, safety, permissions, API mapping,
  and test evidence;
- HTTP central transport derived from the action contract;
- grouped human aliases such as `controllers show`, `runs pause`, and
  `controllers recovery diff`;
- an `interactive` numbered action selector;
- a Textual API Workbench with search, request editing, responses, history,
  drift, route audit, fixtures, evidence, and export;
- `metactl tui` as an alias for that API Workbench;
- a bare `metactl` discovery landing page.

The current generic parser still presents stable action IDs as flat argparse
subcommands. Friendly grouped aliases are translated separately, so the working
human hierarchy is not itself a first-class model for nested help, completion,
document generation, or TUI navigation.

The central transport already has one canonical `configured_transport()`.
It resolves `META_WEBUI_METACTL_CENTRAL_URL`, then the legacy
`META_WEBUI_EVOLVER_CONTROL_URL`, with a current loopback fallback. The Server
Dev Container does not currently provision those operator connection variables.

## Architecture

### 1. Keep the action catalog authoritative

Do not redesign the action catalog. Stable action IDs remain the machine
contract and the server's trusted adapter/authorization path remains the runtime
authority.

### 2. Add one declarative human presentation model

Replace the hand-maintained alias translation as the primary UX model with a
first-class command tree whose leaves reference existing stable action IDs.

The tree owns only presentation concerns:

- grouping;
- command names and compatibility aliases;
- positional versus option mapping;
- operator-facing wording overrides when necessary;
- TUI grouping hints when they are truly presentation data.

It must not duplicate action parameters, safety, permissions, lifecycle status,
or API mappings by default.

CLI nested help, generated operator reference, Navi commands, and the operator
TUI should consume the same presentation model.

### 3. Split operator TUI from API Workbench

`metactl tui` becomes a domain-oriented central operator console with primary
navigation for Overview, Controllers, Instruments, Runs, Experiments, Releases,
Recovery, and Developer.

`metactl api tui` retains the existing API Workbench. Do not remove its request,
drift, fixture, audit, evidence, or export capabilities.

The operator TUI must call the same catalog actions through the same central
transport. It is not a second control plane and it must not directly access
central persistence or edge state.

### 4. Bootstrap the managed connection

Normal Meta Ball development should not require `--server`, `--repo`, `--live`,
or manual host/container address discovery.

Create a repository-owned bootstrap path that makes the existing shared
transport resolver correct from the Server Dev Container. The implementation
must first verify which URL is actually reachable in the current topology, then
provision `META_WEBUI_METACTL_CENTRAL_URL` or an equivalent input to the shared
resolver through repository-owned Dev Container/runtime tooling.

Do not encode a separate connection precedence inside the TUI.

Add a root `tools/metactl` convenience launcher that executes current-checkout
source through the Server Dev Container from the host. Inside the container,
`metactl` remains the normal command.

### 5. Add read-only doctor

`metactl doctor` should explain the resolved target, source of that target,
reachability, presence of auth configuration without secret values, live action
discovery, application/action availability, and catalog drift where local
catalog data exists.

Failure should produce exact repository remediation commands. It must not
silently convert a live operator request into offline repository inspection.

### 6. Preserve safety semantics

Client safety is an extra guardrail, not authorization. Server permissions,
revision/generation fences, leases, identity rules, and physical interlocks stay
authoritative.

The operator TUI must visually distinguish command disposition from physical
evidence. Accepted or queued commands are never labeled physical success.

Automated tests use mocks, simulators, fixtures, or read-only state. No physical
actuation is part of this implementation run.

## Documentation architecture

Task-oriented documentation lives under `docs/metactl/` and starts at
`docs/operator.md`.

Single-concept definitions live under `docs/_concepts/`. Each concept has an
Obsidian alias and ordinary Markdown links so the checkout works both as a
GitHub document set and as an Obsidian-style knowledge graph.

The low-level concept pages should remain small. Primary docs should link rather
than restate definitions.

## Completion criteria

The implementation is complete when:

- `metactl controllers --help` and other nested groups are real parser paths;
- friendly paths and raw stable action IDs resolve to the same action contract;
- `metactl tui` is the operator console, while `metactl api tui` remains the
  Workbench;
- the managed Server environment gives `metactl tui` a truthful live target
  without manual connection reconstruction;
- `tools/metactl tui` works from the repository host against current checkout
  source;
- `metactl doctor` is read-only and produces useful connection diagnostics;
- CLI and TUI share target resolution, action dispatch, safety, and human path
  metadata;
- documentation/Navi/reference output is generated from the same presentation
  and action contracts where practical;
- focused and broader tests are green;
- headless Textual acceptance proves the operator navigation and safety model;
- no real hardware is actuated.

## Related documentation

- [Operator guide](../../operator.md)
- [metactl docs](../../metactl/README.md)
- [CLI](../../metactl/cli.md)
- [Operator TUI](../../metactl/tui.md)
- [Operator Bootstrap](../../_concepts/operator-bootstrap.md) `[[Operator Bootstrap]]`
- [Action Catalog](../../_concepts/action-catalog.md) `[[Action Catalog]]`
