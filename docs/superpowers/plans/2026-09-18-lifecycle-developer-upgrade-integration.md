# Lifecycle Developer Upgrade Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the accepted #113/#114/#115 lifecycle contracts into `hardware-testing` and add the bounded developer-checkout upgrade, synchronized lifecycle documentation, Navi output, and cross-component acceptance for #116.

**Architecture:** Preserve the fixed host-owned `tools/evolver-edge` adapter as the only Compose authority. Add `tools/evolver-edge upgrade` as a host-only, clean-checkout, fetch/fast-forward/submodule-sync/rebuild/health workflow that delegates runtime recreation to the canonical adapter and never changes production release semantics. Reconcile the accepted controller gitlink, metactl wrapper, docs, generated Navi, and contract tests in one integration branch.

**Tech Stack:** Bash, Python/pytest fixture tests, Git submodules, Docker Compose config validation, generated Navi cheatsheets, repository Dev Containers and RTK.

**Spec:** GitHub issues #112/#116 and accepted PRs #125/#128/#127 plus documentation baseline PR #120.

## Global Constraints

- `evoctl update apply RELEASE` remains explicit governed release installation.
- `evoctl upgrade` remains latest/recommended governed release convenience and never becomes `git pull`.
- `tools/evolver-edge upgrade` is developer checkout fast-forward plus rebuild/health only.
- `stop` and `down` remain distinct; `down` preserves state/volumes and never passes `--volumes`.
- No arbitrary Compose project/path/container/shell/Docker authority, firmware flashing, physical actuation, deploy/release/publish, or protected/default-branch merge.
- Preserve #106/#107/#108 shared parser/docs ownership and accepted #120 terminology unless reviewed implementation evidence supersedes it.

---

### Task 1: Integrate accepted lifecycle provenance

**Files:**
- Modify: parent gitlinks and accepted lifecycle files by cherry-picking #113/#114/#115 and #120 provenance.
- Test: existing lifecycle, controller, metactl, docs, and Navi contract tests.

**Interfaces:**
- Consumes: `9ec9be54008554cdba1a08671dfa6d455e36824b`, `4e93af43256f500e5985ae91d117ba9fce71ed38`, `e68a3889ab4dbbdc0a8b3b287ae064681d87108b`, and `28b32bc5b59bb192ab3003aba58dba59e0a99b3f`.
- Produces: a branch containing the accepted host adapter, controller parser/gitlink, metactl lifecycle wrapper/tests, and reviewed lifecycle documentation baseline without altering unowned worktrees.

- [ ] Verify each source SHA and branch ancestry against GitHub before cherry-picking.
- [ ] Cherry-pick only the accepted parent commits and resolve shared-file conflicts by preserving both accepted contracts.
- [ ] Record resulting parent and submodule SHAs and run `git diff --check`.

### Task 2: Add the developer checkout upgrade contract

**Files:**
- Modify: `tools/evolver-edge`.
- Create: `tools/tests/test_evolver_edge_upgrade.py`.

**Interfaces:**
- Consumes: fixed adapter command path and repository root discovered from the script location.
- Produces: `tools/evolver-edge upgrade`, accepting no arbitrary arguments and returning nonzero for dirty state, fetch failure, non-fast-forward-only update, submodule sync/update failure, build failure, or unhealthy final Compose state.

- [ ] Add fixture tests first for clean success, dirty checkout refusal, non-fast-forward refusal, failed build/health, and command ordering/immutability.
- [ ] Implement clean-tree check, remote fetch, current-branch fast-forward-only update without branch switching or reset, recursive submodule URL sync and pinned update, then canonical Compose rebuild/health verification.
- [ ] Ensure old/new parent SHAs are reported, no volume deletion or firmware command is reachable, and failure cannot print success.
- [ ] Run focused tests and shell syntax checks.

### Task 3: Reconcile lifecycle docs, Navi, and integration acceptance

**Files:**
- Modify: `docs/runtime-lifecycle-qol.md`, `docs/evoctl.md`, `docs/metactl/README.md`, `docs/development.md`, `docs/operator.md`, and generated `docs/navi/generated/meta-ball.cheat` only where implementation evidence requires updates.
- Modify: `integration/tests/test_navi_contracts.py` and/or add a focused integration contract test for upgrade semantics and provenance.

**Interfaces:**
- Consumes: implemented #113/#114/#115 behavior and developer-upgrade command.
- Produces: docs that distinguish implemented behavior from planned/unavailable behavior, generated command references synchronized with authoritative presentation, and acceptance assertions for no Docker/socket authority, no state/volume deletion, active-run/release semantic preservation, Compose validity, and no physical/firmware action.

- [ ] Reconcile #120 planned language with implemented lifecycle commands while retaining unavailable central production upgrade semantics.
- [ ] Add the developer upgrade command and exact update-vs-upgrade distinction to operator/development docs without overwriting #107/#108 instrument/action material.
- [ ] Regenerate Navi with `tools/generate_navi_cheats` and require `--check` to pass.
- [ ] Add/extend acceptance tests for generated references, shell allowlists, Compose config, and provenance pins.

### Task 4: Validate, independently review, repair, and hand off

**Files:**
- Modify: no product files unless review identifies a bounded repair; append durable GitHub checkpoints to #116 and PR/issue as appropriate.

- [ ] Run exact focused tests, root `tools/tests`, integration tests, controller affected tests, syntax, Compose config, generated-file check, lock check, and `git diff --check` using supported Server Dev Container commands.
- [ ] Review the complete diff independently against #112/#116 and all frozen invariants; if findings exist, post `CHANGES_REQUIRED` before repair, repair narrowly, and rerun validation/review.
- [ ] Post a durable #116 Session handoff with branch/worktree/HEAD/PR, provenance, behavior, validation/CI, review history, follow-ups, relationships, and Trust audit.
- [ ] Return only `PASS`/`PASS_WITH_FOLLOWUPS`/`READY_FOR_INTEGRATION`/`DONE`, or an explicit durable blocker.
