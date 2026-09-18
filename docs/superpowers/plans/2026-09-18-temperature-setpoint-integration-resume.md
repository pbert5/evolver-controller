# Temperature Setpoint Integration Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-pin Meta BAL PR #91 to the accepted controller head and independently validate the complete non-actuating temperature-setpoint boundary against the exact firmware, hardware, and controller heads.

**Architecture:** Meta BAL remains the integration owner and changes only its component gitlink, provenance contract, and integration assertions. Controller, hardware, and firmware source semantics remain in their separately owned reviewed heads; evidence is collected from their focused lanes plus the root integration/evidence, lock, full-suite, and CI lanes.

**Tech Stack:** Git submodules, Markdown/YAML provenance contracts, pytest, repository `rtk` Dev Container tooling, GitHub CLI/Actions.

**Spec:** GitHub issues #60/#83, existing PR #91, and the prior durable blocker `F-83-INTEGRATION-001`.

## Global Constraints

- Keep PR #91 open and update it in place; do not create a replacement PR or erase prior review history.
- Use `hardware-testing` as the integration base and preserve newer compatible origin work.
- Exact pins are firmware `83483cda621a2e913ad778ae62294872084a507a`, hardware `78a17ebf90b64fea394a05a670ce6b58820fa377`, controller `c9b1eb24e35a52f4f328793b3b4891a314b6ba25`.
- No component default-branch merge, deployment, credentials, firmware flash, real serial, heater actuation, long hold, or physical thermal claim.
- Preserve unrelated dirty state in the parent checkout and do not use destructive resets or force pushes.
- A protocol ACK is protocol evidence only; it is not thermal or physical evidence.

### Task 1: Update the exact integration pin and provenance contract

**Files:**
- Modify: `evolver/evolver-controller` gitlink
- Modify: `docs/temperature-setpoint-integration.md`
- Modify: `integration/tests/test_temperature_setpoint_integration_contract.py`

**Interfaces:**
- Consumes: accepted controller head `c9b1eb24e35a52f4f328793b3b4891a314b6ba25`.
- Produces: root gitlink and assertions that agree on all three exact component heads.

- [ ] **Step 1: Write the failing pin assertion**

Change the controller expected SHA in the root integration test and run that focused test before changing the gitlink or docs. The test must fail because the current HEAD still points to `a28fa191190bb0ae05c6556adab18afe90e248d7`.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `rtk tools/dev-env server exec rtk sh -lc 'cd /workspaces/meta_bal && rtk uv run --project . pytest -q integration/tests/test_temperature_setpoint_integration_contract.py'`

Expected: the exact controller gitlink assertion fails with the old SHA.

- [ ] **Step 3: Advance the controller submodule and documentation**

Checkout the already-fetched accepted commit in `evolver/evolver-controller`, update the controller SHA in `docs/temperature-setpoint-integration.md`, and retain the existing firmware/hardware pins and evidence-boundary wording.

- [ ] **Step 4: Run focused tests to verify green**

Run the same focused test command and `rtk git diff --check`; expected result is a passing contract test and clean whitespace validation.

- [ ] **Step 5: Commit the bounded integration update**

Commit only the gitlink, provenance document, root contract assertion, and this plan with message `Integrate accepted controller temperature head`.

### Task 2: Execute exact-head non-actuating validation

**Files:**
- Read-only: component test suites, root integration/evidence lanes, lock/test tooling, CI workflow results.

**Interfaces:**
- Consumes: exact pins from Task 1 and fetched `origin/hardware-testing`.
- Produces: command/output evidence for the full requested boundary and all negative cases.

- [ ] **Step 1: Verify provenance and clean scope**

Run `rtk git status --short`, `rtk git submodule status`, exact `git rev-parse` checks, and inspect the diff. Confirm the base is the fetched compatible `origin/hardware-testing` and no unrelated files changed.

- [ ] **Step 2: Run the component lanes**

Run the firmware exact-head tests, controller focused/full supported-container tests, hardware focused/full supported-container tests, and the repository’s integration/evidence lanes. Record known non-blocking #110 deployment-boundary behavior separately if reproduced.

- [ ] **Step 3: Run repository locks and complete full suite**

Run `rtk tools/dev-env server exec rtk tools/check-locks` and `rtk tools/dev-env server exec rtk tools/test all`, retaining exact counts and exit codes.

- [ ] **Step 4: Exercise the required negative matrix**

Confirm fixtures/tests cover v1 rejection, wrong vial/channel, missing or mismatched fingerprint, tampered identity/range/digest, opaque lease, replay/duplicate, bad ACK/correlation, authority-loss refresh, and safe-stop, with no transport I/O for pre-dispatch rejections. Use only fake transport/PTY-compatible fixtures; do not open real serial.

### Task 3: Independent review, relationship audit, and durable handoff

**Files:**
- Modify: PR #91 and issue #83 comments only; no source changes unless a bounded review repair is required.

**Interfaces:**
- Consumes: Task 1 diff and Task 2 evidence.
- Produces: fresh independent integration review, fresh independent safety/scientific review, mandatory relationship audit, fresh CI result, and a Session handoff.

- [ ] **Step 1: Compare prose DAG with authenticated native GitHub metadata**

Audit #60/#80/#81/#82/#83/#84/#110, PR #91, and component PR metadata. Record supported native edges and explicitly record empty/ambiguous relationship endpoints; do not invent or mutate unsupported edges.

- [ ] **Step 2: Persist any review finding before repair**

If either review returns `CHANGES_REQUIRED`, post the finding durably on PR #91 or issue #83 before making a bounded repair, then rerun the affected validation and both reviews. Treat #110 as separate/non-blocking unless evidence directly implicates the integrated authority boundary.

- [ ] **Step 3: Run fresh CI and decide merge**

Dispatch or observe a fresh CI run for PR #91. Merge into `hardware-testing` only if every requested gate is fresh green and the reviews are accepted; otherwise leave PR #91 draft and report the smallest safe follow-up.

- [ ] **Step 4: Post the Session handoff and terminal packet**

Post exact base/head/PR, pins, validations, review outcomes, relationship audit, merge outcome, blockers/follow-ups, and the Trust audit. Return only the required accepted terminal packet.
