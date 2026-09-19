# Issue #28 calibration-actions review record

Stable finding identifiers preserved from the independent review:

- `edge_permission_missing`
- `activation_not_calibration_restricted_or_revision_fenced`
- `stale_add_observation_alias`
- `removed_OD_routes_still_exposed`

Repair evidence is kept in the calibration action and operator API regression
tests. The edge mutation boundary requires `manage_calibration`; activation is
restricted to calibration runs, matches calibration type and target, and uses
`based_on_revision` through a revisioned patch; the stale catalog alias is
rejected; and retired OD/pump-fixture routes have no public route owner.
