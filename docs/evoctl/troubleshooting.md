# Troubleshooting

Use the structured error and evidence outcome to choose the next safe step:

| Outcome | Meaning | Safe next step |
| --- | --- | --- |
| operator unavailable | live socket/daemon is unreachable | inspect Edge runtime health; do not infer hardware state from offline data |
| permission denied | caller lacks operator or maintenance authority | use the approved operator identity and role; do not bypass the socket |
| lease unavailable/expired | mutating action lacks a valid lease | acquire or renew the bounded lease through the documented path |
| stale generation/revision | controller or run changed since inspection | refresh status and re-plan against the new generation/revision |
| unavailable/rejected | registry or safety policy forbids the operation | inspect `availability`/`preflight`; do not retry through a lower-level path |
| protocol ACK only | transport accepted the request | report protocol evidence only, not physical success |

For live inspection, use `evoctl doctor`, `evoctl status`, and the nested help
surfaces. `--offline` is explicit and is for local recovery/planning evidence;
it does not authorize live operation. Never solve an `evoctl` problem by opening
serial devices, editing SQLite, invoking arbitrary Docker/shell commands, or
flashing firmware.
