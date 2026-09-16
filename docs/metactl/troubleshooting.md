# metactl troubleshooting

Use this page when the normal central operator path fails. Start with the
managed environment checks below; the `metactl doctor` workflow remains
pending its repair.

## The TUI says central is unavailable

The managed Server environment should supply a reachable target through
[Operator Bootstrap](../_concepts/operator-bootstrap.md). Check, in order:

```text
rtk tools/dev-env server status
rtk tools/dev-env server network
rtk tools/dev-env server smoke
```

Do not fix a container-network problem by hardcoding a random host address into
the TUI. Repair the repository-owned bootstrap so the CLI and TUI resolve the
same central target.

## Authentication or permission failure

`401` means the central server rejected authentication. `403` means the request
reached the server but the authenticated operator does not have the required
permission.

The client may report that authentication material is configured, but it must
not print tokens, shared secrets, or credentials. Do not paste secret values
into issue bodies, documentation, or test fixtures.

## The CLI works but the TUI does not

That is a product defect if both are using the same target and action. The TUI
must reuse the shared transport and action catalog. Compare:

```text
metactl controllers list --json
metactl tui
```

The code run should include CLI/TUI equivalence tests for shared actions.

## The API Workbench opens when I run metactl tui

The developer Workbench is available at the explicit path:

```text
metactl api tui
```

and reserves:

```text
metactl tui
```

for the operator console.

## A command says accepted or queued

That proves the central/operator protocol accepted the command state. It does
not prove physical actuation completed. Inspect the command projection and
hardware evidence before making a physical claim. See
[Command Disposition](../_concepts/command-disposition.md) and
[Physical Evidence](../_concepts/physical-evidence.md).

## Repository and live catalog disagree

Use the API Workbench drift tools:

```text
metactl api check --repo . --live
metactl api tui --repo . --live
```

Resolve the version/catalog mismatch rather than allowing the operator TUI to
quietly invoke a changed action contract.

## I need raw API details

Use [API Workbench](../api-workbench.md):

```text
metactl api tui --repo .
metactl api tui --repo . --live
```

The Workbench is the correct surface for raw method/path, body, headers, drift,
route audit, fixtures, response contracts, and local test evidence.

## I need local controller truth

Use [evoctl](../evoctl.md), not a hidden `metactl` shortcut. The distinction is
described in [Central vs Edge](../_concepts/central-vs-edge.md).

## Related

- [Quickstart](quickstart.md)
- [Operator TUI](tui.md)
- [Operator Bootstrap](../_concepts/operator-bootstrap.md) `[[Operator Bootstrap]]`
- [API Workbench](../_concepts/api-workbench.md) `[[API Workbench]]`
