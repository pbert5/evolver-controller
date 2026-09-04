# eVOLVER instrument schema package

This directory is the Meta BAL-owned source of the private eVOLVER instrument
contract. The five files copied from the historical reference are preserved;
the additive modules define typed experiment programs, requirements,
measurements, validation, and fixtures. BAL identity and sample semantics stay
in the BAL schema and are referenced through `BALSampleReference`.

`instrument/protocol.yaml` remains the edge/central transport contract. It is
not the scientist-facing experiment state machine.

Schema package version: `0.1.0`.

Use `python tools/validate_schema_package.py` for deterministic import and
contract checks. Runtime components consume generated neutral artifacts rather
than importing this checkout at runtime.
