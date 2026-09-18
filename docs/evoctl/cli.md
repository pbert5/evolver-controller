# CLI, help, and command classes

Use nested help as the first source of truth:

```text
evoctl --help
evoctl instrument --help
evoctl instrument sensors --help
evoctl action --help
evoctl hardware --help
```

The [generated reference](reference.md) is built from the actual parser. Every
public parser leaf appears there. `record-installed-release` is intentionally
hidden and classified internal; it is not an operator command.

## Modes

- **LIVE** routes through the controller operator socket. Live reads include
  status, inventory, fresh sensors, cached telemetry, capabilities, calibration
  artifacts, and action/workflow inspection.
- **LOCAL/OFFLINE** is explicit and limited to durable-store or simulator
  operations such as `--offline recovery`, export/import, lifecycle planning,
  validation, and simulator runs. Offline data is not proof of live hardware.
- **MAINTENANCE** is delegated or rejected. Update release commands are owned
  by the controller service; firmware is owned by the hardware service;
  quarantine is DB-only and requires operator evidence.

Compatibility aliases (`local instrument list`, `server status`, `runs list`,
and the documented recovery/release/diagnostic aliases) are tested projections
onto existing commands. They do not create a second transport or authority.

## Evidence vocabulary

`accepted` means the controller accepted a request. `ACK` means a protocol
acknowledgement. `protocol-observed` means the typed hardware protocol
reported an observation. `physical` requires the explicit physical gate and
operator evidence. `calibrated` requires a matching calibration artifact and
provenance. Never promote one evidence level to another in documentation or
an operator report.

The old projected spelling `evoctl workflow action ...` is not a command. Use
`evoctl action ...` for trusted action inspection/preflight/run.
