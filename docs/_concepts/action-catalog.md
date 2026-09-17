---
aliases:
  - Action Catalog
---
# Action Catalog

The Action Catalog is the declarative inventory of operator capabilities. In
the pinned `metactl` component, the eVOLVER catalog lives at
`metactl/applications/evolver/actions.json` and carries stable action IDs,
parameters, lifecycle status, safety, permissions, implementation identity,
API method/path mappings, and declared test evidence.

The catalog describes what exists. It does not contain arbitrary executable
code and it does not replace server authorization. A human command path or TUI
action references a catalog action; the server-side trusted adapter remains the
runtime authority.

An action marked `planned` is discoverable metadata, not an executable
capability.

Related: [Human Command Path](human-command-path.md) `[[Human Command Path]]` ·
[Safety Mode](safety-mode.md) `[[Safety Mode]]` ·
[API Workbench](api-workbench.md) `[[API Workbench]]`
