# Workflow composition contract

`evolver_procedure_runtime` owns the generic `WorkflowDefinition`,
`WorkflowLibrary`, and `WorkflowSession` types. Meta BAL owns concrete workflow
manifests under `workflows/calibration/`; the runtime contains no calibration
science or eVOLVER-specific grouping.

A definition has typed initial `parameters`, discovery `metadata`, ordered
`stages`, and trusted procedure references. A stage is either `once` or
`repeatable`. Bindings are explicit named references to a validated workflow
parameter or operator-created stage-instance parameter; there is no expression
evaluation.

Opening and preflighting a session validates the definition, resolves every
procedure reference, creates the once-stage `ProcedureSession` instances, and
does not invoke an action. A repeatable instance is created only by an explicit
`add_instance` call. `WorkflowSession.advance()` delegates to the frozen #48
`ProcedureEngine.advance()` contract. A completed child reports
`stage_complete`; `continue_stage()` is required before the next stage is
selected. No downstream action starts implicitly.

The library loader reads YAML only from explicitly configured local directories,
rejects symlinked files, sorts results deterministically, and exposes metadata
search/list operations. It does not download or execute arbitrary workflow
sources. Workflow state is in-process and nonpersistent.
