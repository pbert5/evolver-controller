# Native Evoctl TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the configured evoctl TUI with one controller-native Textual app while preserving the current temperature/safe-stop lineage and the reviewed #98 workflow behavior.

**Architecture:** The controller branch starts at `c9b1eb24e35a52f4f328793b3b4891a314b6ba25` and incorporates the reviewed #98 workflow modules and repairs without replacing the temperature-control files. `tui.py` owns a typed `TuiSource` boundary, native seven-view shell, and mountable workflow workspace; live and explicit offline adapters are the only socket/store users. CLI parsing normalizes `--page` and `--workflow` to the same app factory.

**Tech Stack:** Python 3.10+, Textual, pytest, operator socket protocol, EdgeStore, controller submodule gitlink.

**Spec:** GitHub issue #131, including the #103 integration contract.

## Global Constraints

- Work only in `.worktrees/130-native-evoctl-tui` and its controller submodule branch `codex/130-native-evoctl-tui`.
- Preserve temperature-setpoint and safe-stop semantics and operator/hardware authority.
- No physical hardware, safe-stop invocation, firmware, credentials, identity, deployment, destructive state, or merge to `hardware-testing`.
- No evoctl runtime dependency on `app.yaml`, `META_WEBUI_APPLICATION_ROOT`, `config_compiler`, `meta_webui_ui_runtime_textual`, configured page YAML, extension manifests, or Meta WebUI query composition.
- Widgets remain read-only; all reads happen through the injected source and off the Textual UI thread.

### Task 1: Reconcile reviewed workflow lineage

**Files:** controller `workflow_host.py`, `workflow_tui.py`, `workflow_cli.py`, package metadata, and their focused tests.

- [ ] Add the #98 workflow commits/files onto the current controller branch, resolving conflicts in favor of current temperature and safe-stop code.
- [ ] Run the focused workflow host/TUI/CLI tests and inspect the diff for accidental temperature or safety deletions.
- [ ] Commit the semantic merge with both source heads recorded in the commit message.

### Task 2: Define the native source and shell seam

**Files:** controller `src/.../evolver_edge/tui.py`, new focused native view/source module if needed, `tests/test_evolver_tui.py`.

- [ ] Write failing tests for `create_app(source=..., workflow_host=..., initial_view=...)`, seven view names, live/offline source separation, and `--workflow` initial selection.
- [ ] Implement typed read-only source adapters and native views for Overview, Controllers, Instruments, Runs, Recovery, Maintenance, and Workflows.
- [ ] Implement centralized worker refresh/coalescing with last-good data and bounded section errors.
- [ ] Run focused Textual pilot tests, then commit.

### Task 3: Retire configured runtime and normalize CLI

**Files:** controller `tui.py`, `cli.py`, doctor/packaging metadata and controller TUI tests/docs.

- [ ] Add failing parser and isolated-import tests for `tui`, `--page`, `--workflow`, and absence of legacy imports/files.
- [ ] Remove compiler/ApplicationLoader, app-root, generic query resolver, configured page IDs, and Meta WebUI dependency wording from the evoctl path.
- [ ] Keep explicit `--offline` on `OfflineTuiSource` only and make missing Textual errors mention the controller TUI extra.
- [ ] Run CLI/TUI/install tests and commit.

### Task 4: Umbrella provenance and documentation

**Files:** umbrella gitlink, native TUI documentation, provenance tests if present.

- [ ] Record the controller branch/head and reviewed #98 input in the umbrella worktree.
- [ ] Document views, navigation, workflow deep-linking, live/offline authority, and #132 deterministic source injection.
- [ ] Run focused and broad container-backed checks, diff checks, and lock checks.
- [ ] Request independent review; persist every `CHANGES_REQUIRED` finding before bounded repair, then re-run verification and review.
- [ ] Post the Session handoff with exact #103 integration instructions: consume the umbrella HEAD and controller gitlink after independent review, then re-run controller/root integration and authorized #97 physical-host acceptance only under #103.
