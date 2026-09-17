# eVOLVER Edge Operator Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Edge Dev Container a tooling-only client of the controller operator API, with private controller-to-hardware brokerage and no silent offline fallback.

**Architecture:** A typed bounded Unix operator protocol is the sole normal local control plane. The controller owns controller state and brokers hardware IPC; hardware owns hardware state, `/dev`, and serial. Parent Compose/devcontainer mounts enforce the boundaries.

**Tech Stack:** Python 3.12, argparse, Unix sockets, JSON, pytest, Docker Compose, Dev Containers, Textual.

**Spec:** `docs/superpowers/specs/2026-09-16-evoctl-overlay-controller-api-design.md`

## Global Constraints

- Use RTK-prefixed repository commands and canonical Dev Containers for tests.
- Do not modify central server, WebUI, or frontend behavior.
- Normal `evoctl` must never fall back from operator transport to live SQLite.
- Edge Dev Container must not mount controller/hardware state, hardware runtime, or `/dev`.
- Hardware retains both in-process session mutex and cross-process nonblocking `flock`.
- Firmware flashing is not part of acceptance and must not create a direct serial path.
- Submodules are separate repositories; commit/push them before deliberate parent gitlink updates.

### Task 1: Establish executable protocol and routing contracts

**Ownership:** controller submodule operator protocol/server and client-facing modules; tests beside them.

- [ ] Add failing tests for request envelope validation, size/malformed JSON rejection, allowlist, typed success/error, capabilities metadata, and transport failure.
- [ ] Add failing CLI tests proving status/binding/instruments/runs/hardware dispatch through the client and never instantiate live `EdgeStore` in normal mode.
- [ ] Implement the minimal typed operator client/server dispatch and stable error/exit mapping.
- [ ] Keep `--offline` explicit and reject missing offline state with actionable errors.
- [ ] Run focused controller tests, then commit and push the controller branch.

### Task 2: Add controller hardware brokerage and preserve serial safety

**Ownership:** controller hardware adapter/dispatch plus hardware session implementation and tests; no parent files.

- [ ] Add failing simulator tests for discover/protocol-test request flow through operator API to hardware IPC, including unavailable/protocol errors and operator attribution.
- [ ] Add failing lease/generation/target/physical-opt-in/bounded-parameter tests at the controller boundary.
- [ ] Add or retain failing concurrency tests for same-daemon threads, separate-process BUSY, and exception cleanup.
- [ ] Implement only the controller-mediated hardware path; preserve hardware socket ownership and mutex+flock semantics.
- [ ] Run focused controller/hardware suites, commit and push each submodule branch, and report SHAs.

### Task 3: Convert TUI to the operator client

**Ownership:** controller TUI modules/tests; coordinate dependency declaration only with parent task 4.

- [ ] Add failing tests that live TUI data acquisition uses the operator client and does not open `EdgeStore`.
- [ ] Add clean optional-dependency failure coverage.
- [ ] Implement live/offline TUI distinction using the shared client and central-independent local data.
- [ ] Run focused TUI tests and commit/push the controller changes.

### Task 4: Enforce parent Compose/devcontainer isolation

**Ownership:** `.devcontainer/evolver-edge/*`, `deploy/evolver-edge/*`, parent mount/Compose contract tests.

- [ ] Change tests first to require operator runtime sharing while forbidding controller state, hardware state/runtime, and `/dev` in the Edge Dev Container.
- [ ] Split operator and hardware runtime volumes; mount hardware runtime only controller↔hardware and operator runtime controller↔edge.
- [ ] Remove edge state bootstrap and any live SQLite mount; install TUI/client dependencies in the edge development image/environment.
- [ ] Add executable service volume/health topology assertions.
- [ ] Run focused parent integration contracts and commit parent changes.

### Task 5: Improve runtime helper and unavailable UX

**Ownership:** `tools/evolver-edge`, edge launcher, helper tests, operator docs.

- [ ] Add failing tests for absent/stale operator socket, stopped controller guidance (`tools/evolver-edge up`), and running-but-unreachable guidance (`status`, `logs controller`).
- [ ] Implement generic structured core errors plus environment-specific Compose diagnosis in the launcher/helper.
- [ ] Preserve `up/status/logs/restart/down`; add only bounded `exec`, `diagnose`, or explicit rescue routing where supported.
- [ ] Document live/offline classifications and final data flow in operator/development/devcontainer docs.
- [ ] Run helper and documentation contract tests and commit parent changes.

### Task 6: Integrate and validate

**Ownership:** integration worker; parent gitlinks only after submodule SHAs are verified.

- [ ] Review all diffs and submodule statuses; update parent gitlinks deliberately.
- [ ] Run focused suites in parallel where isolated, then canonical broader controller, hardware, root integration, and full repository suites in Dev Containers.
- [ ] Classify every failure as product fix, environment/harness fix, or justified contract change; dispatch repairs by disjoint ownership.
- [ ] Obtain independent architecture/isolation/CLI/hardware/test review and resolve findings.
- [ ] On r640-0 run disposable simulator/no-device Compose acceptance including controller-down and hardware-down UX.
- [ ] Dispatch exactly one physical-runtime worker for read-only `root-evolver` acceptance and record topology, discovery, protocol, serial owner count, and isolation evidence.
- [ ] Push coherent parent and submodule checkpoints without force-push.

