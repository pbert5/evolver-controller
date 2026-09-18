# Maintenance, lifecycle, and recovery

Maintenance commands are deliberately visible as delegated or rejected rather
than presented as ordinary operator actions:

```text
evoctl update status
evoctl update check RELEASE
evoctl update apply RELEASE
evoctl lifecycle-plan --operation update
evoctl --offline recovery
evoctl simulator start --instruments 1
evoctl simulator create-run RUN_ID --bundle-id BUNDLE --execution-plan '{}'
evoctl simulator tick RUN_ID --ticks 1
evoctl firmware preflight
```

The lifecycle distinction is authoritative:

- `evoctl update apply RELEASE` is an explicit governed release operation.
- #114 owns the pending lifecycle parser family: `evoctl runtime status`,
  `runtime up`, `runtime stop`, `runtime down`, `runtime restart`, `runtime
  logs`, and `runtime upgrade`, plus unambiguous `up`, `down`, `restart`,
  `logs`, and `upgrade` aliases. These are listed as pending in the generated
  reference and are not callable on this #106 parser head.
- `evoctl upgrade` means latest/recommended governed release, never Git pull.
- `tools/evolver-edge upgrade` is a developer checkout fast-forward/rebuild
  convenience when its owning workstream lands; it is not an `evoctl` command.

#112/#114 own the lifecycle implementation and acceptance. Preserve the
host-runtime boundary: `stop` stops services while `down` tears down the
runtime, named volumes preserve state, active runs gate upgrades, and health
must be verified before success. No lifecycle documentation grants firmware
flashing, serial access, Docker authority, state purge, identity reset, or
destructive recovery.
Firmware upload and physical identity provisioning remain maintenance paths
with separate physical evidence requirements.
