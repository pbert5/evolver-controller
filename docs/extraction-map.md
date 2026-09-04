# Extraction map

Reference source: `refference/meta_webui_demo`, `wire-in-cli` at
`652cc5de7098949c31d71d035f41fbe0499e6ac1`; the proven Dev Container source is
`realy-fix-devcontainers` at `a21bb4009938e3a61ca52377ad109d753890b05c`.

| Old path/package | New owner | Tests | Status |
|---|---|---|---|
| `applications/evolver/backend/src/.../evolver_controller.py` and `evolver_control/` | `evolver-server` | central controller/action/sync tests | copied; compatibility imports retained |
| `.../evolver_edge/` | `evolver-controller` | EdgeStore, sync, lifecycle, installer, simulator tests | copied nearly unchanged |
| `.../evolver_edge/{hardware,hardware_ipc,hardware_service,identity,store}.py` | `evolver-hardware` | hardware IPC/read-only/simulator tests | bounded extraction copied |
| `tools/metactl.py`, `metactl_transport.py` | `metactl` | `test_metactl.py`, transport tests | catalog-driven transport; canonical eVOLVER action contract in `applications/evolver/actions.json` |
| `tools/build_evolver_*.py`, `validate_evolver_release.py` | Meta Ball `tools/` | release-builder tests | copied authoritative implementation |
| BAL assembled schema selection | Meta Ball `private-schema/` | focused selector tests | implemented without private source |
| `.devcontainer/server`, `.devcontainer/evolver-edge`, `.codex`, `.vscode` | Meta Ball root | devcontainer contract tests | adapted from reference |
