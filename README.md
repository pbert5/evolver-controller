# Meta Ball

Private integration repository for independently usable eVOLVER components.
The public component repositories are extracted from the private Meta WebUI
reference checkout and are pinned here when integrated. Meta Ball owns
integration tooling and private schema consumption; it is not the runtime
implementation owner.

See [docs/architecture.md](docs/architecture.md), [docs/extraction-map.md](docs/extraction-map.md), and [docs/development.md](docs/development.md).

The implemented local operator executable is `evoctl`; use it for local edge
inspection and recovery. See [docs/operator.md](docs/operator.md).

For physical-controller development, open the `Meta Ball eVOLVER Edge`
Dev Container. It provides a source-backed `evoctl` and host Docker access
for the root-owned edge Compose stack; the controller container never receives
`/dev` or the Docker socket, and the hardware container remains the exclusive
serial owner.

The reference checkout under `refference/` is intentionally retained with its
original spelling and is read-only source material.

## API Workbench

Run `rtk metactl api tui --repo .` inside the Server Dev Container to explore
the action/API contract without starting a server. Add `--live` for discovery
and drift checks. See [API Workbench](docs/api-workbench.md) for imports,
fixtures, request execution, testing and safety controls.

