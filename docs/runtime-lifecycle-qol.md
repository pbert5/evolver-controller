# Runtime Lifecycle QoL

Tracking issue: #112

Status: planned. The commands in the target sections below are not yet an implemented contract unless they are already documented elsewhere as existing behavior.

## Goal

Make routine edge and central runtime lifecycle operations easy to discover and run from the supported CLIs without creating a second deployment, update, or hardware authority.

The desired operator surface is intentionally small:

```text
evoctl up
evoctl down
evoctl restart
evoctl logs
evoctl upgrade

metactl server up
metactl server down
metactl server restart
metactl server logs
metactl server upgrade
```

The convenience commands must remain presentation over existing runtime and release ownership.

## Existing authority

The edge repository already has a host-side Compose helper at `tools/evolver-edge` with `up`, `down`, `restart`, `status`, `logs`, `diagnose`, and `rescue`.

The controller CLI already has explicit release operations:

```text
evoctl update status
evoctl update check RELEASE
evoctl update apply RELEASE
```

These commands operate on governed release identifiers. They are not source-checkout update commands.

The controller container intentionally does not own the Docker socket. Docker/Compose activation remains host-owned. Firmware also remains outside the software-update contract.

`metactl` remains catalog-driven. Central host lifecycle operations must execute through an explicit host-runtime capability and not through arbitrary shell execution or through the HTTP service that is being stopped.

## Update versus upgrade

The target terminology is:

```text
evoctl update apply RELEASE
    Install this explicit governed release.

evoctl upgrade
    Move to the latest/recommended governed release.

tools/evolver-edge upgrade
    Developer-only source checkout fast-forward, submodule sync, rebuild, and health verification.
```

Production `upgrade` must never be implemented as an unrestricted `git pull`.

If the system does not yet have an authoritative latest/recommended release selector, `evoctl upgrade` should remain unavailable with a clear diagnostic or the implementation should add the smallest explicit release-selection contract needed.

## Edge runtime target

Canonical grouping:

```text
evoctl runtime status
evoctl runtime up
evoctl runtime stop
evoctl runtime down
evoctl runtime restart
evoctl runtime logs
evoctl runtime upgrade
```

Short aliases may expose:

```text
evoctl up
evoctl down
evoctl restart
evoctl logs
evoctl upgrade
```

`stop` should stop containers while retaining them. `down` should remove the Compose runtime but preserve durable controller/hardware state and named volumes. No shortcut may imply `--volumes`.

Edge upgrade must reuse existing release discovery, update planning, active-run gating, activation, verification, and installed-release recording.

## Central runtime target

Target grouping:

```text
metactl server status
metactl server up
metactl server stop
metactl server down
metactl server restart [SERVICE]
metactl server logs [SERVICE]
metactl server upgrade
```

Short top-level aliases are acceptable only when they are unambiguous presentation aliases to the same canonical actions.

The normal metactl toolbox/API context must not gain Docker socket access, SSH authority, or arbitrary shell execution. Service names must come from a strict allowlist.

A command such as `metactl server down` must run from an external host-runtime process whose authority survives termination of the central service.

## Developer checkout upgrade

The developer-only edge helper may provide:

```text
tools/evolver-edge upgrade
```

Its contract is:

1. require a clean working tree
2. fetch the configured remote
3. remain on the current/configured integration branch
4. fast-forward only
5. refuse non-fast-forward replacement
6. run `git submodule sync --recursive`
7. update submodules to the parent-pinned revisions
8. report the old and new parent SHAs
9. rebuild/recreate through the canonical Compose path
10. wait for controller and hardware health
11. return nonzero if build, activation, or health verification fails

It must never force reset, discard dirty files, silently switch branches, delete volumes/state, or flash firmware.

If a central developer-checkout upgrade is added, it should follow the same source-control rules and use the central runtime's canonical migration/build/health entrypoints.

## Observability

Lifecycle operations should report enough information to distinguish request acceptance from a healthy final state:

- runtime and operation
- affected services
- previous release or SHA when known
- requested/new release or SHA
- governed-release versus developer-checkout source mode
- active-run gate result for edge upgrade
- health verification result
- final observed state

Compose command acceptance alone is not sufficient evidence of success.

## Safety invariants

- no Docker socket added to the normal controller container
- no Docker socket added to the normal metactl toolbox/API context
- no arbitrary command or shell-fragment parameters
- no arbitrary Compose project/container/path selection
- no state or volume deletion from normal down/upgrade flows
- no firmware flash from software lifecycle shortcuts
- active eVOLVER runs continue to gate unsafe update activation
- explicit `evoctl update ...` semantics remain compatible

## Workstreams

The implementation is tracked under #112:

- #113 canonical host lifecycle adapter
- #114 evoctl lifecycle aliases and governed upgrade
- #115 metactl server lifecycle and upgrade
- #116 developer checkout upgrade, docs, Navi, and acceptance

## Acceptance evidence

Before the feature is documented as implemented, evidence should cover host-runtime denial, service allowlisting, stop versus down semantics, no-volume-deletion behavior, dirty/non-fast-forward checkout refusal, active-run update gating, failed build/health reporting, catalog/presentation synchronization, Compose validation, and the absence of physical actuation or firmware flashing.
