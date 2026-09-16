# metactl quickstart

This page defines the ordinary operator path. The goal is to reach the central
stack without manually reconstructing its URL, container network, or auth
configuration.

> The pinned client provides `metactl tui` for the operator console and
> `metactl api tui` for the API Workbench. The parent repository's
> `tools/metactl` launcher runs that client in the current checkout's Server
> Dev Container. The `metactl doctor` workflow remains pending its repair.

## Managed development checkout

Bring up the repository-owned Server Dev Container:

```text
rtk tools/dev-env server up
```

The target host-side convenience path is:

```text
rtk tools/metactl tui
```

`tools/metactl` should enter the current checkout's Server Dev Container and
run the source-backed `metactl`. It must not use a stale globally installed
client.

Inside the Server Dev Container, the equivalent path is:

```text
metactl tui
```

The managed environment should provision the reachable central target and any
non-secret session defaults through the shared
[Operator Bootstrap](../_concepts/operator-bootstrap.md). The operator should
not need `--repo`, `--live`, or a manually discovered host/container address for
normal Meta Ball development.

## Doctor status

The `metactl doctor` contract is pending its repair. Do not treat it as a
proven diagnostic workflow until that repair lands; use the managed target and
the explicit status, network, and smoke checks while it is pending.

## Direct CLI examples

Representative human paths already exist in the pinned client and remain part
of the target hierarchy:

```text
metactl controllers list
metactl controllers show <controller-id>
metactl controllers freshness <controller-id>
metactl controllers commands list <controller-id>
metactl controllers commands watch <controller-id> <command-id>
metactl controllers recovery status <controller-id>
metactl instruments list
metactl runs list
metactl runs show <run-id>
```

Mutating commands keep catalog/server safety and authorization. Do not infer
physical success from an accepted or queued response. See
[Command Disposition](../_concepts/command-disposition.md).

## Explicit and deployed targets

An explicit server remains supported for non-managed deployments. The shared
transport currently recognizes:

1. `META_WEBUI_METACTL_CENTRAL_URL`;
2. legacy `META_WEBUI_EVOLVER_CONTROL_URL`;
3. the transport fallback when neither is configured.

The managed Meta Ball environment should set the first value to a URL that is
actually reachable from the execution environment. The TUI must reuse that
shared resolver instead of creating a second precedence rule.

Authentication-related environment values remain secret-bearing process
configuration and must not be copied into documentation, shell history, or
committed files.

## Next

- [CLI](cli.md)
- [Operator TUI](tui.md)
- [Troubleshooting](troubleshooting.md)
- [API Workbench](../api-workbench.md)

Obsidian aliases: `[[Operator Bootstrap]]` · `[[Human Command Path]]` ·
`[[Safety Mode]]`
