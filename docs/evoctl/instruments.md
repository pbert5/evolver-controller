# Instruments and observations

Instrument identity is stable controller inventory, not a serial port name.
Keep controller, instrument, device, component/vial, and channel identities
distinct. Use `instrument list/show/status/capabilities/components` to inspect
that relationship.

## Fresh versus persisted data

```text
evoctl instrument sensors list INSTRUMENT_ID
evoctl instrument sensors read INSTRUMENT_ID temperature --channel 0
evoctl instrument sensors read INSTRUMENT_ID od --channel 0
evoctl instrument telemetry latest INSTRUMENT_ID
evoctl instrument telemetry list INSTRUMENT_ID --limit 10
```

`sensors read` requests a fresh typed read through the operator and hardware
authority. `telemetry latest/list` reads persisted telemetry and may be stale.
Raw values are not derived or calibrated values unless the response carries
that provenance. Report target, channel, timestamp, freshness, raw/derived
value, calibration status, and evidence level together.

The CLI is read-only by default for instrument observation. A sensor response
does not grant action authority, a lease, or physical success.
