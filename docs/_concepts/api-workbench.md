---
aliases:
  - API Workbench
---
# API Workbench

The API Workbench is the advanced developer/operator inspection surface exposed
as `metactl api tui` and related `metactl api check/test` commands.

It works with action/API contracts, HTTP method/path data, typed parameters,
request and response inspection, fixtures, OpenAPI imports, drift comparison,
route audit, sanitized history/export, and declared test evidence.

It is intentionally not the default fleet/operator dashboard. The normal
operator TUI should present controllers, instruments, runs, experiments,
releases, and recovery as domain objects while reusing the same action catalog
and transport underneath.

The Workbench remains the correct tool when the question is "what API contract
or request is this action using?" rather than "what is happening in my lab?"

See [full API Workbench guide](../api-workbench.md).

Related: [Action Catalog](action-catalog.md) `[[Action Catalog]]` ·
[Human Command Path](human-command-path.md) `[[Human Command Path]]` ·
[Safety Mode](safety-mode.md) `[[Safety Mode]]`
