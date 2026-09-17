---
aliases:
  - Human Command Path
---
# Human Command Path

A Human Command Path is the operator-facing CLI hierarchy for one stable action
ID, for example:

```text
metactl controllers show <controller-id>
```

for the corresponding catalog action:

```text
evolver.controllers.show
```

The path is presentation, not behavior. It may define grouping, aliases,
positional arguments, and operator wording, but it inherits the action's real
parameters, lifecycle status, safety, permissions, and implementation/API
contract from the [Action Catalog](action-catalog.md).

The CLI, generated help/reference material, Navi entries, and operator TUI must
consume the same human-path model so they cannot teach conflicting commands.

Related: [Action Catalog](action-catalog.md) `[[Action Catalog]]` ·
[Safety Mode](safety-mode.md) `[[Safety Mode]]`
