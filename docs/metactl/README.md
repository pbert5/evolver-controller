# metactl operator documentation

`metactl` is the central operator client for Meta Ball. It uses the declared
action catalog and the trusted `evolver-server` operator API. It does not own a
database, direct EdgeStore access, SSH transport, or duplicated domain logic.

> This documentation describes the approved operator experience implemented by
> the pinned client and the repository-owned Server Dev Container. The client
> provides the action catalog, grouped command aliases, first-class nested help,
> and the operator TUI; the parent repository supplies the managed
> central-target bootstrap. The read-only `metactl doctor` workflow reports
> target, reachability, discovery, and catalog drift without exposing secrets.

## Start here

- [Quickstart](quickstart.md): get from checkout to a usable operator session.
- [CLI](cli.md): human command hierarchy and discovery behavior.
- [Operator TUI](tui.md): the interactive central operator console.
- [Troubleshooting](troubleshooting.md): connection, auth, drift, and command-state problems.
- [API Workbench](../api-workbench.md): advanced API inspection, fixtures, drift, and evidence.
- [evoctl](../evoctl.md): controller-local edge operation.
- [Runtime Lifecycle QoL](../runtime-lifecycle-qol.md): implemented host-runtime lifecycle convenience, developer checkout upgrade, and the unavailable central production-upgrade boundary.

## Design rule

Normal operation should not require learning action IDs, HTTP routes, Dev
Container network details, or which environment variable points at the central
service. Those remain inspectable, but the managed development environment and
operator tooling must bootstrap the normal path.

The intended first-run experience is:

```text
# from the repository host
tools/metactl tui

# from inside the Server Dev Container
metactl tui
```

An explicit target remains available for unusual deployments, but it is an
override rather than the ordinary setup path.

## Host-runtime lifecycle QoL

Issue #112's lifecycle surface is available through the repository launcher:

```text
metactl server up
metactl server stop
metactl server down
metactl server restart [SERVICE]
metactl server logs SERVICE
metactl server upgrade
```

The wrapper runs these operations from the external host-runtime process and
delegates only to the canonical fixed adapter. `metactl server upgrade` is
currently unavailable because no governed central release selector exists.
The normal metactl toolbox/API context has no Docker socket, SSH authority, or
arbitrary shell execution, and self-shutdown is not routed through the central
HTTP service being terminated.

See [Runtime Lifecycle QoL](../runtime-lifecycle-qol.md) for the full contract
and the distinction between governed release upgrade and developer checkout
refresh.

## Mental model

A [Human Command Path](../_concepts/human-command-path.md) is presentation for a
stable [Action Catalog](../_concepts/action-catalog.md) action. Both the CLI and
operator TUI dispatch the same action through the same transport and server
authorization boundary. The TUI does not create a second control plane.

Connection setup is owned by [Operator Bootstrap](../_concepts/operator-bootstrap.md).
Mutation and hardware guardrails are described by [Safety Mode](../_concepts/safety-mode.md).
Returned command state is interpreted using
[Command Disposition](../_concepts/command-disposition.md), and physical claims
require [Physical Evidence](../_concepts/physical-evidence.md).

## Obsidian aliases

`[[Action Catalog]]` · `[[Operator Bootstrap]]` · `[[Human Command Path]]` ·
`[[Safety Mode]]` · `[[Command Disposition]]` · `[[Physical Evidence]]` ·
`[[API Workbench]]` · `[[Central vs Edge]]`
