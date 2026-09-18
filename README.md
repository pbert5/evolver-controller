# Meta Ball

Private integration repository for independently usable eVOLVER components.
The public component repositories were extracted from the historical private
Meta WebUI source and are pinned here when integrated. Meta Ball owns
integration tooling and private schema consumption; it is not the runtime
implementation owner.

See [architecture](docs/architecture.md), [development](docs/development.md),
and the [operator entry point](docs/operator.md).

## Operator tools

Start with [docs/operator.md](docs/operator.md) when the goal is to operate the
system rather than develop it.

- `metactl` is the central operator CLI and talks to `evolver-server` through
  the declared operator API.
- `metactl tui` is the target human operator console. Its contract and automatic
  connection/bootstrap behavior are defined in [docs/metactl/tui.md](docs/metactl/tui.md).
- `metactl api tui` is the existing advanced API Workbench for action/API
  inspection, drift, fixtures, evidence, and explicit request execution. See
  [docs/api-workbench.md](docs/api-workbench.md).
- `evoctl` is the controller-local edge CLI for local inspection and recovery.
  See [docs/evoctl.md](docs/evoctl.md).

The current pinned `metactl` already provides the central action catalog,
grouped operator commands, and the API Workbench. The operator-TUI and managed
bootstrap documents on this branch define the next implementation contract and
are intentionally explicit about behavior that still needs to land in code.

## Development

For physical-controller development, open the `Meta Ball eVOLVER Edge` Dev
Container. It provides a source-backed `evoctl` and host Docker access for the
root-owned edge Compose stack; the controller container never receives `/dev`
or the Docker socket, and the hardware container remains the exclusive serial
owner.

For central/server development, use the Server Dev Container. The development
and test workflow is documented in [docs/development.md](docs/development.md).
Historical extraction provenance is documented in
[docs/extraction-map.md](docs/extraction-map.md); no private reference checkout
is required by this repository.
