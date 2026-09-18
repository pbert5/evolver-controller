# Native evoctl TUI test mode

`tools/tui-test` is a self-contained, deterministic harness for the real
controller-native `EvoctlApp` produced by #131. It never constructs a second
screen model and never falls back to a live operator, serial, database, or
hardware authority.

The supported commands are:

```text
./tools/tui-test doctor [--json]
./tools/tui-test list --json
./tools/tui-test smoke [--json]
./tools/tui-test shell --page <overview|controllers|instruments|runs|recovery|maintenance|workflows>
./tools/tui-test workflow --scenario <scenario>
```

Inside the Server Dev Container the wrapper resolves the repository root and
executes `uv run --all-packages --all-extras python tools/tui_test.py`, so the
direct command uses the repository environment rather than host
`/usr/bin/python3`.

The harness imports the native factory from the reviewed #131 module and calls
the single seam:

```python
create_app(source=FakeTuiSource(), workflow_host=host, initial_view="workflows")
```

`FakeTuiSource` supplies deterministic status, binding, doctor, capability,
instrument, run, recovery, and maintenance reads. Every request is recorded;
anything outside the read set raises `AuthorityViolation`. Source failures can
be injected with `fail_next()` to verify last-good/error behavior in the
native app.

The smoke matrix exercises all seven native views, direct initial pages,
keyboard navigation, refresh and repeated lifecycle activity, source errors,
ScenarioRegistry workflow discovery, workflow library/draft/search entry,
inspector and drawer representations, repeatable workflow interaction, and
read-only authority. Pilot settling is used for synchronization; arbitrary
sleeps are not used.

## #103 integration instructions

1. Integrate the reviewed #131 controller commit that exports
   `create_app(source=..., workflow_host=..., initial_view=...)` and the
   `ScenarioRegistry` contract used by this harness.
2. From the integrated Server Dev Container, run `./tools/tui-test doctor`,
   `./tools/tui-test list --json`, `./tools/tui-test smoke`, and
   `./tools/tui-test smoke --json`.
3. Run one interactive check for every native page and one trusted scenario:
   `./tools/tui-test shell --page overview` and
   `./tools/tui-test workflow --scenario <scenario>`.
4. Confirm no controller gitlink, hardware behavior, safe-stop semantics,
   credentials, deployment state, or protected branch was changed by #132.
5. Re-run the controller suite and retain the native-shell smoke JSON with
   the #131/#132 provenance in the integration evidence.
