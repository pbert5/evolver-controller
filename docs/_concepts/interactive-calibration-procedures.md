---
aliases:
  - Interactive Calibration Procedures
---
# Interactive Calibration Procedures

The short-session descriptors in `procedure/examples/` are declarative
operator flows. Each family separates setup, point/sample collection, and
review where applicable. Inputs are typed and bounded; action polling and
session timeouts are finite; every descriptor declares actuator cleanup.

Temperature uses controller temperature units through the trusted temperature
action. Pump-flow points issue one bounded pump pulse and do not encode a pulse
loop. OD LED intensity is an 8-bit value from 0 through 255. OD review reports
that fitting is unavailable and does not invoke a fitter.

Observation metadata names only the registered calibration sinks:
`edge.calibration_run.observation` and
`central.calibration_session.observation`. Descriptors contain trusted action
and sink identifiers only; they do not contain serial commands, paths, URLs,
SQL, scripts, or executable source.
