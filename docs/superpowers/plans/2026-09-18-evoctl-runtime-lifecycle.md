# evoctl Runtime Lifecycle and Governed Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or **superpowers:executing-plans** for inline execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `evoctl runtime` lifecycle presentation plus unambiguous short aliases and a fail-closed governed `evoctl upgrade` path without adding host Docker or shell authority.

**Architecture:** Extend the existing controller CLI registry/parser with a maintenance delegation contract for `runtime status|up|stop|down|restart|logs` and `upgrade`. Translate short aliases only at the CLI presentation boundary. `upgrade` selects only a durable recommended release when present; otherwise it emits an explicit unavailable diagnostic, while `update apply RELEASE` remains the explicit pinned-release path.

**Tech Stack:** Python `argparse`, existing `EdgeStore`/`UpdateManager`, pytest in the repository Server Dev Container, `rtk` command wrapper.

**Spec:** GitHub issue #114 and parent issue #112, using #113 provenance `9ec9be54008554cdba1a08671dfa6d455e36824b`.

## Global Constraints

- Lifecycle ownership is limited to `runtime` and short lifecycle aliases; instrument/action namespaces remain untouched for #106.
- `evoctl update apply RELEASE` remains explicit governed release application.
- `evoctl upgrade` is latest/recommended governed release convenience only; no Git pull.
- `tools/evolver-edge upgrade` remains a separate developer-checkout contract owned outside #114.
- Runtime commands return delegation intent and do not execute arbitrary Docker, socket, shell, path, Compose project, or container-ID authority from controller arguments.
- Active runs defer/block governed upgrade; activation/health failure cannot be reported as success; output includes target operation, release information, and final state when available.

### Task 1: Specify parser and semantic boundaries with failing tests

**Files:**
- Modify: `evolver/evolver-controller/tests/test_evolver_command_registry.py`
- Modify: `evolver/evolver-controller/tests/test_evolver_edge_sync_cli.py`

**Interfaces:**
- Tests establish `CommandSpec` entries for `runtime.*` and `upgrade`, parser spellings for canonical and short aliases, a stable delegation payload, and unavailable/active-run upgrade behavior.

- [x] **Step 1: Write failing tests** for parser compatibility, exact alias normalization, lifecycle delegation without operator/store access, recommended-release absence, active-run deferral, and successful/failed governed upgrade observability.
- [x] **Step 2: Run the focused tests** in the Server container and confirm they fail because the new command keys and parser paths do not exist.

### Task 2: Implement the smallest CLI contract

**Files:**
- Modify: `evolver/evolver-controller/src/meta_webui_application_backend/evolver_edge/cli.py`
- Modify: `evolver/evolver-controller/src/meta_webui_application_backend/evolver_edge/update.py` only if the existing manager needs a bounded selection/result adapter.

**Interfaces:**
- Add `runtime` subparsers for `status`, `up`, `stop`, `down`, `restart`, and `logs` with no arbitrary target arguments.
- Add top-level `upgrade` and normalize only `up`, `down`, `restart`, `logs`, and `upgrade` to their runtime equivalents.
- Add a read-only `runtime_delegation()`/equivalent result containing operation, fixed target, allowed services, delegation state, and no executable command supplied by the user.
- Select `controller_release_selection()` only when it contains a valid recommended release; otherwise return exit 2 with a clear diagnostic.
- Route a selected release through `UpdateManager` and retain the existing explicit `update` behavior.

- [x] **Step 1: Implement parser/registry entries and alias normalization.**
- [x] **Step 2: Implement lifecycle delegation output and governed-upgrade selection/gating.**
- [x] **Step 3: Run focused tests until green, then refactor only for clarity while preserving output keys and safety boundaries.**

### Task 3: Document the supported operator surface and validate integration boundaries

**Files:**
- Modify: `docs/evoctl.md`
- Modify: `evolver/evolver-controller/tests/test_evolver_deployment_boundary.py` only for explicit no-Docker/socket assertions needed by #114.

- [x] **Step 1: Add concise canonical/alias examples and the three-way upgrade semantic distinction.**
- [x] **Step 2: Run focused controller tests, controller broader tests, root tools tests, Compose config validation, syntax, lock, and diff checks using `rtk` + Server Dev Container.**
- [x] **Step 3: Inspect the diff for #106 scope contamination and verify only the controller gitlink plus #114-owned files changed.**

### Task 4: Independent review and repair loop

**Files:**
- Review only; bounded repairs use the files above.

- [ ] **Step 1: Perform an independent safety/parser/release review against the issue acceptance criteria and persist any `CHANGES_REQUIRED` finding in the GitHub issue before repair.**
- [ ] **Step 2: Apply bounded repairs, rerun focused/broader validation, and repeat independent review until PASS or PASS_WITH_FOLLOWUPS.**
- [ ] **Step 3: Push the branch, open an early draft PR targeting `hardware-testing`, post validation/review checkpoints, and finish with a durable #114 Session handoff.**
