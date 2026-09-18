# evoctl generated command reference

<!-- GENERATED FILE. DO NOT EDIT. Run tools/generate_evoctl_reference.py. -->

This inventory is derived from `evolver/evolver-controller`'s `build_parser()`.
Descriptions, safety classifications, and examples live in the linked operator
guide; this file answers which parser spellings exist at the reviewed head.

| Command | Classification | Parser status |
| --- | --- | --- |
| `evoctl action availability [-h] --target TARGET [--parameters PARAMETERS] [--operator OPERATOR] [--lease-token LEASE_TOKEN] [--controller-generation CONTROLLER_GENERATION] [--physical] [--simulator] action_id` | `live` | execute |
| `evoctl action list [-h] [--target TARGET] [--simulator]` | `live` | execute |
| `evoctl action preflight [-h] --target TARGET [--parameters PARAMETERS] [--operator OPERATOR] [--lease-token LEASE_TOKEN] [--controller-generation CONTROLLER_GENERATION] [--physical] [--simulator] action_id` | `live` | execute |
| `evoctl action run [-h] --target TARGET [--parameters PARAMETERS] [--operator OPERATOR] [--lease-token LEASE_TOKEN] [--controller-generation CONTROLLER_GENERATION] [--physical] [--simulator] action_id` | `live` | execute |
| `evoctl action show [-h] [--target TARGET] [--simulator] action_id` | `live` | execute |
| `evoctl binding [-h]` | `live` | execute |
| `evoctl calibration artifacts [-h] [--instrument-id INSTRUMENT_ID]` | `live` | execute |
| `evoctl calibration preflight [-h] [--requirements REQUIREMENTS] references` | `live` | execute |
| `evoctl capabilities [-h]` | `live` | execute |
| `evoctl controllers [-h]` | `live` | execute |
| `evoctl dispense [-h] --artifact ARTIFACT --volume-ul VOLUME_UL --channel CHANNEL [--maximum-duration-ms MAXIMUM_DURATION_MS]` | `local` | execute |
| `evoctl doctor [-h]` | `live` | execute |
| `evoctl enroll [-h] --server SERVER --token TOKEN [--mode {repair,live_handoff,forced_adoption}] [--confirm-forced-adoption]` | `local` | execute |
| `evoctl export-state [-h] [archive]` | `local` | execute |
| `evoctl firmware [-h] [--port PORT] [--artifact ARTIFACT] [--physical] [--operator OPERATOR] [--sha256 SHA256] {build,upload,verify,preflight}` | `maintenance` | delegated |
| `evoctl hardware actuate [-h] --target TARGET [--channel CHANNEL] [--duration-ms DURATION_MS] [--level LEVEL] [--physical] [--operator OPERATOR] [--lease-token LEASE_TOKEN] [--controller-generation CONTROLLER_GENERATION] {set_output,pulse_pump,set_stir,pulse_heater}` | `live` | execute |
| `evoctl hardware discover [-h]` | `live` | execute |
| `evoctl hardware layout [-h] --target TARGET --operator OPERATOR --channel CHANNEL --physical-side {left,right,unconfirmed} --method {operator_observed,inferred_two_position_profile}` | `live` | execute |
| `evoctl hardware lease acquire [-h] --operator OPERATOR [--ttl-seconds TTL_SECONDS]` | `live` | execute |
| `evoctl hardware lease release [-h] --operator OPERATOR` | `live` | execute |
| `evoctl hardware lease status [-h]` | `live` | execute |
| `evoctl hardware protocol-test [-h]` | `live` | execute |
| `evoctl hardware provision-identity [-h] --device-id DEVICE_ID --owner-id OWNER_ID --operator OPERATOR [--physical]` | `live` | execute |
| `evoctl hardware quarantine-command [-h] --operator OPERATOR --reason-kind REASON_KIND [--requested-device REQUESTED_DEVICE] [--requested-owner REQUESTED_OWNER] [--observed-device OBSERVED_DEVICE] [--observed-owner OBSERVED_OWNER] command_id` | `maintenance` | rejected |
| `evoctl hardware safe-stop [-h] --physical --operator OPERATOR` | `live` | execute |
| `evoctl import-state [-h] archive` | `local` | execute |
| `evoctl instrument capabilities [-h] instrument_id` | `live` | execute |
| `evoctl instrument components [-h] instrument_id` | `live` | execute |
| `evoctl instrument list [-h]` | `live` | execute |
| `evoctl instrument sensors list [-h] instrument_id` | `live` | execute |
| `evoctl instrument sensors read [-h] --channel CHANNEL instrument_id {temperature,od}` | `live` | execute |
| `evoctl instrument show [-h] instrument_id` | `live` | execute |
| `evoctl instrument status [-h] instrument_id` | `live` | execute |
| `evoctl instrument telemetry latest [-h] [--limit LIMIT] instrument_id` | `live` | execute |
| `evoctl instrument telemetry list [-h] [--limit LIMIT] instrument_id` | `live` | execute |
| `evoctl instruments [-h]` | `live` | execute |
| `evoctl lifecycle-plan [-h] --operation {install,repair,update,clean-reinstall,uninstall,handoff,forced-adoption,factory-reset} [--server SERVER] [--release RELEASE] [--current-state CURRENT_STATE] [--confirmed]` | `local` | execute |
| `evoctl record-installed-release [-h] release` | `internal` | hidden compatibility helper |
| `evoctl recovery [-h]` | `local` | execute |
| `evoctl run events [-h] run_id` | `live` | execute |
| `evoctl run pause [-h] [--based-on-revision BASED_ON_REVISION] run_id` | `live` | execute |
| `evoctl run resume [-h] [--based-on-revision BASED_ON_REVISION] run_id` | `live` | execute |
| `evoctl run show [-h] run_id` | `live` | execute |
| `evoctl run stop [-h] [--based-on-revision BASED_ON_REVISION] run_id` | `live` | execute |
| `evoctl run telemetry [-h] run_id` | `live` | execute |
| `evoctl runs [-h]` | `live` | execute |
| `evoctl simulator create-run [-h] --bundle-id BUNDLE_ID --execution-plan EXECUTION_PLAN [--instruments INSTRUMENTS] run_id` | `local` | execute |
| `evoctl simulator start [-h] [--instruments INSTRUMENTS]` | `local` | execute |
| `evoctl simulator tick [-h] [--ticks TICKS] [--instruments INSTRUMENTS] run_id` | `local` | execute |
| `evoctl status [-h]` | `live` | execute |
| `evoctl sync [-h] [--loop] [--interval INTERVAL]` | `local` | execute |
| `evoctl tui [-h] [--page {overview,controllers,instruments,runs,recovery,maintenance}]` | `local` | execute |
| `evoctl update apply [-h] release` | `maintenance` | delegated |
| `evoctl update check [-h] release` | `maintenance` | delegated |
| `evoctl update status [-h]` | `maintenance` | delegated |
| `evoctl validation [-h] [--parameters PARAMETERS] {safe_stop,pulse_pump,set_stir,pulse_heater}` | `local` | execute |
| `evoctl workflow list [-h] [--search SEARCH]` | `live` | implemented parser path |
| `evoctl workflow preflight [-h] [--parameter NAME=VALUE] [--target TARGET] [--simulator] [--jsonl] [--scenario {bounded_poll,central_disconnected,concurrent_sessions,correction_retry_stale,failure_cleanup,instrument_disconnected,library_browsing,multiple_concurrent_sessions,observation_required,physical_intervention,repeatable_calibration,successful_completion,unsupported_temperature,waiting_for_input}] [--operator OPERATOR] [--lease-token LEASE_TOKEN] [--physical] workflow_id` | `live` | implemented parser path |
| `evoctl workflow run [-h] [--parameter NAME=VALUE] [--target TARGET] [--simulator] [--jsonl] [--scenario {bounded_poll,central_disconnected,concurrent_sessions,correction_retry_stale,failure_cleanup,instrument_disconnected,library_browsing,multiple_concurrent_sessions,observation_required,physical_intervention,repeatable_calibration,successful_completion,unsupported_temperature,waiting_for_input}] [--operator OPERATOR] [--lease-token LEASE_TOKEN] [--physical] workflow_id` | `live` | implemented parser path |
| `evoctl workflow show [-h] workflow_id` | `live` | implemented parser path |
## Pending lifecycle integration inventory

The following spellings are the #112/#114 coordination contract. They are
intentionally marked pending because the reviewed #106 parser head does not
implement them. The #108 integration owner must regenerate this section from
the integrated lifecycle parser and preserve the existing `update` commands.

| Command | Classification | Parser status |
| --- | --- | --- |
| `evoctl runtime status` | `live` | pending #114 / #112 |
| `evoctl runtime up` | `maintenance` | pending #114 / #112 |
| `evoctl runtime stop` | `maintenance` | pending #114 / #112 |
| `evoctl runtime down` | `maintenance` | pending #114 / #112 |
| `evoctl runtime restart` | `maintenance` | pending #114 / #112 |
| `evoctl runtime logs` | `maintenance` | pending #114 / #112 |
| `evoctl runtime upgrade` | `maintenance` | pending #114 / #112 |
| `evoctl up` | `maintenance` | pending #114 / #112 |
| `evoctl down` | `maintenance` | pending #114 / #112 |
| `evoctl restart` | `maintenance` | pending #114 / #112 |
| `evoctl logs` | `maintenance` | pending #114 / #112 |
| `evoctl upgrade` | `maintenance` | pending #114 / #112 |

