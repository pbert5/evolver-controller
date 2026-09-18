# Historical Python test recovery

Historical source provenance: the recovery inventory was created from the
private Meta WebUI source at `wire-in-cli` commit
`652cc5de7098949c31d71d035f41fbe0499e6ac1`. That source is no longer a
submodule or repository dependency; this document preserves only the recovery
record. WebUI/frontend and private BAL behavior are not reintroduced.

The historical scan found 82 Python test files (75 application/repo tests and 7
package-scoped suites). Classification is semantic by test family; individual
obsolete frontend tests are intentionally retired rather than copied.

| Classification | Recovered families or decision |
|---|---|
| ALREADY_EXTRACTED | central controller/actions/sync; edge store/sync/lifecycle/simulator; hardware read-only/IPC/firmware; metactl transport; devcontainer contracts |
| RECOVER | edge recovery/archive, simulator adverse cases, controller install/update, hardware daemon/IPC edge cases, release-builder failure cases |
| REWRITE_CONTRACT | action catalog/API projection, auth/authorization, route ownership, schema selector, release provenance, CLI transport |
| RETIRED_SURFACE | WebUI dashboards/detail/TUI, frontend runtime/debug, local frontend harness, obsolete application composition |
| PRIVATE_SCHEMA_DEPENDENT | BAL schema build/OWL and catalog/data tests requiring private sources or private services |
| HARNESS_ONLY | acceptance registry/harness, test census, compose/devcontainer, CLI launchers, environment/toolchain checks |
| OBSOLETE_LEGACY | removed application roots, old config/compiler/runtime packages, legacy DC/strain database adapters |

Current ownership decisions:

- central behavior stays in `evolver-server`; edge behavior in
  `evolver-controller`; serial and bounded local IPC in `evolver-hardware`;
  catalog-driven operator transport in `metactl`;
- release-builder tests stay at root beside the authoritative `tools/` scripts;
- private BAL content is selected from configuration and is never copied into
  public repositories;
- all hardware tests use fakes, simulators, or pseudo-terminals and never
  actuate physical outputs or flash firmware.

The inventory is revisited when a component adds a new public surface. Derived
action, route, schema, and test-file counts are asserted by automated contract
tests rather than hand-edited in this document.
