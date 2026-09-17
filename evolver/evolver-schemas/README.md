# eVOLVER instrument schema package

This directory is the Meta BAL-owned source of the private eVOLVER instrument
contract. The LinkML modules define typed experiment programs, requirements,
measurements, validation, and fixtures. BAL identity and sample semantics stay
in the BAL schema and are referenced through `BALSampleReference`; this package
does not replace or embed that private BAL schema.

The module-to-field map is [field-reference.md](field-reference.md). It is a
navigation aid, not a second schema: definitions and allowed values live in
the LinkML YAML modules under `instrument/`.

`instrument/protocol.yaml` remains the edge/central transport contract. It is
not the scientist-facing experiment state machine.

Schema package version: `0.1.0`. Trusted action identities and supported
versions are declared in `registry/trusted_actions.yaml` (revision
`trusted-actions-1`); the compiler binds that revision into every bundle.

The compiler accepts declarative action identities only. It validates the
program graph, policies, parameters, conditions, triggers, and optional
validation criteria before resolving seeded random windows. Bundle digests are
SHA-256 hashes of canonical, sorted JSON and contain no wall-clock values.

Use `python tools/validate_schema_package.py` for deterministic import and
contract checks, and `python tools/export_schema.py` for the neutral manifest.
Runtime components consume generated neutral artifacts rather than importing
this checkout at runtime. The checked-in example is for validation; it is not
evidence of a physical instrument or calibration.
