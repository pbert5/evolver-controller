# API Workbench

The specialized Textual workbench is owned by the `metactl` component. It reads
the same explicitly composed action catalogs used by the CLI. The umbrella
pins both the client and the server discovery implementation.

## Run inside the Server Dev Container

```sh
metactl api tui --repo .
metactl api tui --repo . --live
metactl api tui --server http://127.0.0.1:18087
metactl api check --repo . --live
metactl api check --repo . --audit
metactl api test evolver.edge.status --repo . --dry-run
metactl api test evolver.edge.status --repo . --trust-tests
metactl api test --repo . --app evolver --trust-tests
```

From a host, enter the profile with `rtk tools/dev-env server up`, then use
`rtk tools/dev-env server exec` before the commands above. Rebuild the Server
profile after checking out this branch so its `metactl` wrapper enables the
`workbench` extra. No server is needed for repository browsing.

The default live target is metactl's configured central URL, normally port
18087. Use your actual exposed address when connecting through a deployment.
The existing `META_WEBUI_METACTL_CENTRAL_URL`, `META_WEBUI_METACTL_TIMEOUT`,
operator, token, permissions and control shared-secret environment settings
are reused for the configured target. The workbench does not grant permissions;
the server continues to authenticate and authorize every operation. Credentials
are not forwarded automatically to a different target. Changing the target in
the TUI clears configured headers and invalidates the displayed drift result.

## Interaction

Search matches words across action IDs, method, path, tags, status and safety
badge. Select a leaf to edit typed parameters. Required fields and enum choices
are displayed beside each field. `Body` generates the JSON body; `null` means
generate it from the form at send time. Edited body fields override form body
fields, but cannot override path parameters or the action selector.

Use Send or Ctrl+Enter for a request, `t` to run the same request with response
checks, `f` for endpoint pytest evidence and `T` for application evidence. Writes
never run on an accidental tree-selection Enter. `Watch` polls a selected read
every two seconds without overlapping requests. It does not subscribe to SSE or
WebSocket streams. Test output streams into the Evidence tab and Escape cancels
the local test subprocess group. Individual HTTP requests have a bounded timeout.

Response tabs show the recorded request, JSON, a bounded expandable tree, raw
sanitized representation, headers, the contract snapshot, response diff, checks,
drift, route audit, evidence and export. Select history rows to compare responses.
`c` and `p` generate sanitized curl or Python requests and copy them using the
terminal clipboard protocol. Replace redacted credentials before using exports.

## Discovery and imports

`GET /api/meta/actions` returns `meta-api-catalog/1`, containing complete action
records and API bindings for this server's available adapters. `/api/actions`
continues to provide the legacy summary. Discovery does not execute tests or
actions. Missing runtime adapters are reported explicitly. The client validates
each full catalog before it becomes an endpoint registry.

Repository plus live mode compares action IDs, routes, parameters, safety,
permissions, schemas and other contract metadata. Intentional route aliases
remain separate actions. Actions without an API mapping stay visible but cannot
be sent. Requests to changed or missing actions are blocked after a drift
comparison; resolve the mismatch or inspect the live catalog directly.
Unavailable discovery is an error, never a claim of zero drift. A server
exposing only the eVOLVER application cannot establish availability for other
applications or for routes outside its discovery contract.

```sh
metactl api tui --openapi ./openapi.yaml --server http://localhost:9000
metactl api tui --openapi https://example.test/openapi.json --server https://example.test
metactl api tui --repo . --fixture metactl/examples/api-workbench-responses.json
```

OpenAPI 3.0 and 3.1 imports support JSON bodies, local references, scalar
path/header parameters and standard form query parameters. External references,
cookie parameters, nonstandard serialization and non-JSON request media types
are rejected explicitly. Bundle external references before importing. Imported
server URLs are not automatically execution targets. Response schemas are
validated when declared; missing schemas are displayed as unverified.

`--audit` parses static Python route decorators without importing application
code. It reports unmatched routes and dynamic-decorator diagnostics. It cannot
prove coverage of router prefixes, source-generated routes, manual HTTP dispatch
or routes omitted by server discovery.

## Execution safety and retention

SAFE mode only sends reads. `--allow-mutations` enables explicitly classified
writes; `--allow-hardware` additionally enables hardware and legacy writes whose
physical effect is unknown. Both flags are required for potentially physical
writes, and each write requires typing the complete action ID. These controls
are client guardrails, not substitutes for server authorization, revision fences,
leases or physical interlocks. An HTTP success is never physical evidence.

Catalog authors can explicitly declare `safety.effect` as `read`, `mutation`,
`destructive` or `hardware`. Existing physical confirmations remain authoritative;
unclassified writes are `HW?`. Optional `api.request_schema` and `api.responses`
carry JSON Schemas; response keys are status codes, status families or `default`.
This work does not invent response guarantees for existing endpoints.

Fixture mode is fully offline, matches exact method/path/body and never falls
back to a server. It still confirms writes. Session history is memory-only and
bounded to 100 exchanges; bodies are limited to 2 MiB. Known credential fields
and echoed values are redacted from history and exports. Original wire bytes
are not retained. Non-JSON bodies are withheld from history, with status, headers
and byte count still available. Redirects are not followed.

Evidence executes only references from local repository catalogs, with exact
file/node resolution and no shell interpretation. Missing or ambiguous evidence
is an explicit error. `--dry-run` previews the commands. `--trust-tests`, or the
TUI's RUN TESTS confirmation, authorizes repository Python execution; tests are
not sandboxed by the HTTP safety mode. Remote/OpenAPI evidence cannot execute.
Legacy evidence references that are absent after repository extraction must be
fixed at their source. The workbench does not guess replacement test names.

## Verification

The standalone metactl workflow runs the complete component suite, including
headless Textual interaction and fixture/safety/import tests. The umbrella
workflow resolves the workspace lock and runs selected metactl and server
discovery regressions through the supported Server Dev Container and the new
`tools/test evidence` lane. No live controller or physical hardware is required.
