# metactl CLI

The CLI has two identities that must stay separate:

1. stable action IDs are the machine contract;
2. human command paths are the operator presentation.

The current client translates grouped human paths into action IDs through its
first-class presentation model. Nested help and the operator TUI consume that
same model while stable action IDs remain the machine contract.

## Target hierarchy

The first-class hierarchy should include the currently implemented paths and
make planned capabilities visibly unavailable rather than pretending they run:

```text
metactl
  actions
    list
    show
  doctor          [pending repair]
  status
  controllers
    list
    show
    freshness
    add
    adopt
    refresh
    rescan
    archive
    restore
    release
      set
    commands
      list
      show
      watch
    manual
      lease
      command
      stir
    measurements
    telemetry
    activities
    events
    evidence
    logs
    recovery
      request
      status
      diff
  instruments
    list
    show
  runs
    list
    show
    pause
    resume
    stop
  experiments
    validate
    describe
    plan
    enqueue      [planned when catalog says planned]
    run          [planned when catalog says planned]
  releases
    build
  tui
  api
    tui
    check
    test
```

This is a presentation tree, not a second action catalog. Each leaf references
one stable [Action Catalog](../_concepts/action-catalog.md) ID.

## Discovery behavior

These must be useful without contacting the central server:

```text
metactl
metactl --help
metactl controllers --help
metactl controllers recovery --help
metactl actions list
metactl actions show <action-id>
```

Nested help should inherit title, description, parameters, lifecycle status,
safety, and permissions from the catalog unless the presentation tree contains
a deliberate operator-facing wording override.

`metactl actions ...` remains the low-level capability inventory. Operators
should not need action IDs for ordinary tasks, but developers and automation
must be able to inspect and execute stable IDs directly.

## Machine output

`--json` remains stable machine-readable output. Human formatting may improve,
but logs, prompts, progress text, or terminal decoration must not contaminate
JSON output.

## Mutations

The CLI must preserve the server's authorization and revision/generation
semantics. Client confirmation is an additional guardrail, not authorization.
Read [Safety Mode](../_concepts/safety-mode.md).

## Relationship to the TUI

The operator TUI must be able to show or copy the corresponding human CLI path
for any action it exposes. The CLI and TUI should therefore consume the same
[Human Command Path](../_concepts/human-command-path.md) model.

The API Workbench remains separately addressable as `metactl api tui`; see
[API Workbench](../api-workbench.md).

## Related

- [Quickstart](quickstart.md)
- [Operator TUI](tui.md)
- [Action Catalog](../_concepts/action-catalog.md) `[[Action Catalog]]`
- [Human Command Path](../_concepts/human-command-path.md) `[[Human Command Path]]`
- [Safety Mode](../_concepts/safety-mode.md) `[[Safety Mode]]`
