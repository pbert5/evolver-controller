# Calibration

Inspect stored calibration evidence and validate references without implying
that a calibration was performed:

```text
evoctl calibration artifacts
evoctl calibration artifacts --instrument-id INSTRUMENT_ID
evoctl calibration preflight '{"artifact_id":"artifact-1"}' --requirements '[]'
evoctl dispense --artifact artifact.json --volume-ul 80 --channel 0
```

Calibration artifacts are matched by instrument, component/vial, capability,
version, and digest/provenance. Raw observations remain raw until the artifact
and transformation are explicit. `dispense` plans a bounded calibrated
operation without actuating hardware; it is not a pump command.

Calibration workflows may contain trusted actions, but action availability,
lease, generation, bounds, operator attribution, physical opt-in, and safe-stop
rules still apply at execution time.
