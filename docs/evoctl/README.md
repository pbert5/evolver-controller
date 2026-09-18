# evoctl operator guide

`evoctl` is the local operator surface for one controller. It talks to the
controller operator socket for live operations; it does not replace the
controller service, hardware daemon, or central `metactl` API.

## Read next

- [Quickstart](quickstart.md): safe, non-actuating inspection and simulator use.
- [CLI and modes](cli.md): authority, command classes, aliases, and help.
- [Instruments](instruments.md): identity, fresh sensors, telemetry, and evidence.
- [Actions](actions.md): availability, preflight, leases, bounds, and opt-in.
- [Workflows and runs](workflows.md): inspection, revisions, and operator attribution.
- [Calibration](calibration.md): artifacts and preflight without claiming calibration.
- [Maintenance](maintenance.md): lifecycle, simulator, firmware, and delegated commands.
- [Troubleshooting](troubleshooting.md): unavailable, permission, lease, and stale-generation errors.
- [Generated reference](reference.md): parser-derived command inventory.

## Authority and safety

The normal path is:

```text
evoctl -> operator.sock -> evolver-controller -> hardware.sock -> evolver-hardware -> serial
```

The hardware daemon is the exclusive serial owner. Do not open serial devices,
write the controller database, or call arbitrary Docker/shell commands from an
operator script. `evoctl` commands are classified as live, local/offline, or
maintenance/delegated/rejected; a command's existence is not evidence that it
is safe to execute.

Automated acceptance uses simulator, fakes, and read-only evidence. It must not
actuate real hardware, flash firmware, reset identity, purge state, or perform
destructive recovery.
