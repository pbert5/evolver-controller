# Workflows and runs

Workflow metadata and preflight use the same trusted host/session contracts as
the workflow UI:

```text
evoctl workflow list
evoctl workflow show WORKFLOW_ID
evoctl workflow preflight WORKFLOW_ID --target INSTRUMENT_ID --parameter name=value
evoctl workflow run WORKFLOW_ID --target INSTRUMENT_ID --parameter name=value
evoctl run show RUN_ID
evoctl run events RUN_ID
evoctl run telemetry RUN_ID
evoctl run pause RUN_ID --based-on-revision 3
evoctl run resume RUN_ID --based-on-revision 3
evoctl run stop RUN_ID --based-on-revision 3
```

Workflow `preflight` resolves target and capabilities without invoking an
action. Run mutation uses an optional revision fence; stale revisions must be
reported rather than silently overwritten. `--jsonl` workflow output is
versioned and redacted structurally; credentials, leases, and unbounded raw
responses are not operator output.

Lifecycle commands remain distinct from workflow runs. `stop` is an explicit
run operation; `down` is a host-runtime operation and is not an `evoctl` run
mutation. Active-run upgrade gating, named-volume/state preservation, and
health verification belong to the runtime lifecycle authority.
