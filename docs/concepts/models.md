# Models, requests, and evidence

`ModelIdentity` describes a provider-scoped logical model. `ModelEndpoint`
represents an execution endpoint separately; catalog adapters do not invent
endpoint data that their source does not supply. A `ModelProfile` combines
identity, capabilities, pricing, provenance, and retrieval time.

Capabilities use `SupportStatus.SUPPORTED`, `UNSUPPORTED`, and `UNKNOWN`.
Missing catalog fields stay unknown. `RequestProfile` describes explicit task,
modality, context, tool/structured-output, cost, latency, and quality
requirements.

Selection evaluates only quality observations with the exact requested task.
It does not substitute a general benchmark score for task-specific evidence.
Every `CandidateAssessment` retains eligibility, reasons, estimated cost, and
available evidence values.
