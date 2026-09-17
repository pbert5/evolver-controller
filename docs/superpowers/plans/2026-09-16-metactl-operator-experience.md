# metactl operator experience implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `metactl` a discoverable central operator CLI/TUI with automatic managed connection bootstrap while preserving the existing API Workbench and action/server authority.

**Architecture:** Keep stable action IDs and the current transport/server boundary authoritative. Add one declarative human presentation tree consumed by nested CLI help, the operator TUI, generated references, and Navi. Wire the managed Server Dev Container and a root launcher into the existing shared transport resolver rather than creating TUI-specific networking.

**Tech Stack:** Python 3.12, argparse, Textual, JSON action catalogs, uv, pytest, pytest-xdist, Dev Container CLI, RTK, Git submodules.

**Spec:** `docs/superpowers/specs/2026-09-16-metactl-operator-experience-design.md`

## Global Constraints

- The main Codex thread stays in the user-selected current working directory and branch.
- Use RTK for shell commands whenever RTK supports the command.
- The Server Dev Container is the canonical build/test environment for central/metactl work.
- `metactl` remains a central API client with no EdgeStore, controller DB, SSH, or direct serial access.
- `evoctl` remains the controller-local operator CLI.
- `metactl api tui` retains the existing API Workbench.
- No real hardware actuation is authorized for this run.
- Every changed conceptual behavior gets a focused executable test before product implementation.
- Establish one persistent read-only Terra test architect for the implementation run.
- Preserve all server authorization, revision/generation fencing, leases, and physical-evidence boundaries.

---

### Task 1: First-class human command tree

**Files:**
- Modify in `pbert5/metactl`: `cli.py`
- Modify in `pbert5/metactl`: `meta_webui_ui_runtime_textual/cli.py`
- Create in `pbert5/metactl`: `applications/deployment/metactl-cli.json` or the smallest equivalent presentation file after repository reconnaissance
- Modify in `pbert5/metactl`: `tests/test_metactl.py`
- Add focused presentation-model tests in the nearest existing metactl test module

**Interfaces:**
- Consumes: existing action catalog records and `_HUMAN_ALIASES` behavior as compatibility evidence
- Produces: one presentation tree mapping nested human command paths to stable action IDs

- [ ] **Step 1: Write failing nested-help tests**

Add tests equivalent to:

```python
def test_controllers_help_is_a_real_nested_parser_path(capsys):
    module = _metactl_module()
    with pytest.raises(SystemExit) as raised:
        module.main(["controllers", "--help"], transport=object())
    assert raised.value.code == 0
    text = capsys.readouterr().out
    assert "show" in text
    assert "freshness" in text
    assert "recovery" in text


def test_human_path_and_action_id_dispatch_same_action(capsys):
    fake = FakeTransport()
    assert module.main(["controllers", "show", "edge-a", "--json"], transport=fake) == 0
    first = fake.calls[-1]
    assert module.main(["evolver.controllers.show", "--controller-id", "edge-a", "--json"], transport=fake) == 0
    assert fake.calls[-1] == first
```

- [ ] **Step 2: Run the focused tests and record the expected red result**

Run inside the Server Dev Container:

```text
rtk tools/dev-env server exec rtk tools/test component metactl -q
```

The new nested-help contract should fail before implementation.

- [ ] **Step 3: Implement the presentation tree**

The tree must own only grouping, names/aliases, positional mapping, and deliberate display wording. It must reference catalog action IDs and inherit parameters, safety, permissions, and lifecycle status from the catalog.

- [ ] **Step 4: Preserve raw action-ID execution and current compatibility aliases**

Existing automation using stable action IDs must keep working. Current friendly spellings must remain valid unless an explicit compatibility alias is added.

- [ ] **Step 5: Run focused metactl tests**

```text
rtk tools/dev-env server exec rtk tools/test component metactl -q
```

- [ ] **Step 6: Commit and push the metactl submodule branch**

Commit message:

```text
feat: make metactl command hierarchy first class
```

---

### Task 2: Shared operator bootstrap and read-only doctor

**Files:**
- Modify in `pbert5/metactl`: `metactl_transport.py`
- Modify in `pbert5/metactl`: `cli.py`
- Modify/add metactl tests for configuration source reporting and doctor behavior
- Modify in parent `pbert5/meta_bal`: `.devcontainer/server/devcontainer.json`
- Modify in parent `pbert5/meta_bal`: `.devcontainer/server/scripts/bootstrap-devcontainer` if needed
- Create in parent `pbert5/meta_bal`: `tools/metactl`
- Modify parent tests covering Dev Container helpers/launchers

**Interfaces:**
- Consumes: existing `configured_transport()` and repository Server Dev Container
- Produces: one truthful resolved target shared by CLI, doctor, TUI, and API Workbench

- [ ] **Step 1: Write failing transport-source tests**

Add a pure test that verifies resolution precedence and reports a non-secret source label:

```python
def test_operator_target_prefers_metactl_url(monkeypatch):
    monkeypatch.setenv("META_WEBUI_METACTL_CENTRAL_URL", "http://central-a:18087")
    monkeypatch.setenv("META_WEBUI_EVOLVER_CONTROL_URL", "http://legacy:18087")
    resolved = resolve_operator_target()
    assert resolved.url == "http://central-a:18087"
    assert resolved.source == "META_WEBUI_METACTL_CENTRAL_URL"
```

Do not expose token/shared-secret values through this result.

- [ ] **Step 2: Write failing doctor tests**

Use an injected/fake transport and discovery response. Prove that doctor reports target, reachability, auth presence as booleans/source labels, discovery state, and drift state without secret values.

- [ ] **Step 3: Inspect the live Dev Container topology before choosing the managed URL**

Use repository tooling, not guesswork:

```text
rtk tools/dev-env server up
rtk tools/dev-env server network
rtk tools/dev-env server exec rtk env
```

Probe the actual central service path from inside the Server Dev Container using a read-only health/discovery request. Do not hardcode loopback unless it is proven reachable from that execution context.

- [ ] **Step 4: Provision the managed target through repository-owned environment/bootstrap**

Set the existing shared resolver input in the Server profile. Do not add separate TUI target logic.

- [ ] **Step 5: Add `tools/metactl`**

The host launcher should delegate to the current worktree's Server Dev Container and execute the source-backed in-container `metactl` wrapper. It must preserve arguments and exit status.

- [ ] **Step 6: Verify host and in-container equivalence**

```text
rtk tools/metactl --help
rtk tools/metactl doctor
rtk tools/dev-env server exec metactl doctor
```

Use a fixture or safe local central service. No physical controller is required.

- [ ] **Step 7: Commit parent and submodule changes separately and push both branches**

---

### Task 3: Operator TUI at `metactl tui`

**Files:**
- Create focused operator-TUI modules under `pbert5/metactl`, separate from `api_workbench/`
- Modify `pbert5/metactl/cli.py` entrypoint routing
- Add headless Textual tests in `pbert5/metactl/tests/`
- Keep `pbert5/metactl/api_workbench/` behavior compatible except for explicit navigation/cross-linking where needed

**Interfaces:**
- Consumes: action catalog, human presentation tree, shared configured transport/bootstrap
- Produces: domain-oriented operator console

- [ ] **Step 1: Write headless startup/navigation tests before UI implementation**

Tests must prove:

```text
startup header shows resolved central target and connection state
primary navigation includes Controllers, Instruments, Runs, Experiments, Releases, Recovery
raw HTTP endpoint tree is not the primary navigation
planned actions render unavailable and cannot dispatch
```

- [ ] **Step 2: Write shared-dispatch tests**

Use a fake transport. Selecting a read action such as controller refresh/list must dispatch the exact stable catalog action and parameters already used by the CLI.

- [ ] **Step 3: Write safety and evidence tests**

Prove that a mutating action follows catalog confirmation, queued/accepted status is not labeled physical success, and no hardware access is required by the test.

- [ ] **Step 4: Implement the smallest operator TUI matching `docs/metactl/tui.md`**

Primary areas: Overview, Controllers, Instruments, Runs, Experiments, Releases, Recovery, Developer. Use domain projections and action forms. Do not duplicate API Workbench tabs for raw request/response diagnostics.

- [ ] **Step 5: Route entrypoints**

```text
metactl tui       -> operator TUI
metactl api tui   -> existing API Workbench
meta-api-tui      -> existing API Workbench compatibility entrypoint
```

- [ ] **Step 6: Add CLI-command and API-context affordances**

For a selected operator action, generate the same human CLI path as the first-class presentation tree. The API affordance may show the explicit Workbench command/context rather than embedding the Workbench.

- [ ] **Step 7: Run metactl component tests**

```text
rtk tools/dev-env server exec rtk tools/test component metactl -q
```

- [ ] **Step 8: Commit and push**

Commit message:

```text
feat: add metactl operator tui
```

---

### Task 4: Generated discovery and documentation integration

**Files:**
- Modify parent `README.md`, `docs/operator.md`, `docs/metactl/*`, and `docs/_concepts/*` only where implementation facts changed
- Remove target-contract warning blocks once behavior is implemented
- Modify `docs/navi/cheatsheets/meta-ball.cheat`
- Modify `tools/generate_navi_cheats`
- Regenerate `docs/navi/generated/meta-ball.cheat`
- Add/modify tests that check generated Navi/reference content

**Interfaces:**
- Consumes: action catalog plus first-class human presentation tree
- Produces: one searchable human command/reference vocabulary

- [ ] **Step 1: Write a failing generated-command test**

Prove a representative action with a human path generates the friendly path, for example:

```text
metactl controllers show <controller_id>
```

and that the stable action ID remains searchable metadata.

- [ ] **Step 2: Update generator to consume the presentation tree**

Do not maintain a second hand-written command mapping in the generator.

- [ ] **Step 3: Add curated Navi entries for operator docs and bootstrap**

Include operator guide, metactl quickstart, TUI guide, doctor, and API Workbench paths.

- [ ] **Step 4: Regenerate and verify**

```text
rtk tools/generate_navi_cheats
rtk tools/generate_navi_cheats --check
```

- [ ] **Step 5: Update documentation status text**

Once code is green, remove statements that describe doctor/operator TUI/launcher as future targets. Keep conceptual definitions and architecture links.

---

### Task 5: Integration, failure fan-out, and acceptance

**Files:**
- No default product ownership; repair tasks go back to the owning submodule/parent subsystem

**Interfaces:**
- Consumes: all earlier tasks
- Produces: operational proof and final pinned submodule state

- [ ] **Step 1: Run focused suites in parallel where isolation allows**

At minimum:

```text
rtk tools/dev-env server exec rtk tools/test component metactl -q
rtk tools/dev-env server exec rtk tools/test component server -q
rtk tools/dev-env server exec rtk tools/test integration -q
```

- [ ] **Step 2: Run parent fast and full relevant topology**

```text
rtk tools/dev-env server exec rtk tools/test fast
rtk tools/dev-env server exec rtk tools/test all
```

Any discovered failure must be classified and repaired as product, environment/harness, or explicitly justified stale test contract. Do not leave unexplained red tests.

- [ ] **Step 3: Run operator acceptance**

Verify from the repository host and inside the Server Dev Container:

```text
rtk tools/metactl --help
rtk tools/metactl controllers --help
rtk tools/metactl doctor
rtk tools/metactl tui
rtk tools/dev-env server exec metactl api tui --help
```

Use headless/fixture acceptance for TUI behavior. No physical actuation.

- [ ] **Step 4: Coverage-gap review against Terra test map**

Ask the persistent read-only Terra test architect to compare implemented conceptual behaviors with the focused tests and identify missing meaningful coverage. Convert gaps into Luna test/product repair tasks.

- [ ] **Step 5: Pin the verified metactl submodule commit in Meta Ball**

Only after standalone metactl tests are green. Run parent tests after the gitlink update.

- [ ] **Step 6: Commit and push the final `fix-documentation` integration branch**

The final report must include actual starting/final SHAs, submodule SHA, exact tests/counts, failure resolutions, environment/bootstrap evidence, review findings, and confirmation that no physical hardware was actuated.
