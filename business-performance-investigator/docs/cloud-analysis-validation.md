# Analytical cloud acceptance

`scripts/validate-analysis.ps1` is the separate acceptance entrypoint for
`business-investigator`. Its implementation and command-boundary tests are
local-only so far: **the new analytical cloud experiment has not been run**.
The existing `validate-agent.ps1` remains probe-only.

## Prepare without Azure

From the template folder, with the pinned sample already prepared:

```powershell
.\scripts\validate-analysis.ps1 -PrepareOnly
```

This verifies the exact normalized CSV hash and parses the reference locally.
It writes `.artifacts/analysis-validation-preparation.json` with
`status: prepared`, `cloud_validation: not_run` and `cloud_calls_made: 0`.
It does not authenticate, inspect Azure, open SQL, or invoke a model.
If the reference is missing, follow [sample preparation](baseline.md) first;
the validator never silently downloads or substitutes data.

Optional parameters are `-SourceCsv`, `-PythonPath` and, for preparation only,
`-OutputPath`. The default Python interpreter is the project's `.venv`.

## Live pair: fresh authorization required

Do not run the following until the resource, inference-cost, permission and
cleanup scope is freshly approved. An old probe approval is not reusable.
The switches record intent; they do not grant organizational authorization or
create a hard spending cap.

Prerequisites:

- A new owned experiment initialized with `-AgentName business-investigator`
  and `-InitializationMode AnalysisSnapshot`.
- The current analytical service version deployed, including the runtime
  `security.server` field and shared Top-K ceiling of 5. Earlier analytical
  builds fail this acceptance contract.
- The configured Azure CLI/azd context and explicit Chat Completions model.
- An existing, explicitly approved session ID for this agent and project.
- The exact runtime identity already has approved model access. This validator
  does not grant roles, change shared models, initialize SQL or provision resources.

```powershell
.\scripts\validate-analysis.ps1 `
  -ConfigPath .\config.local.json `
  -SessionId '<approved-existing-analysis-session-id>' `
  -ApproveAzureChanges `
  -ApproveModelInference
```

The same `-Question` is sent to both paths; the default requests overall changes
and territory/product investigation. The fixed baseline is intentionally
question-agnostic. This acceptance run requires completed, valid evidence; an
`insufficient_data`, exhausted or error response does not count as acceptance.
That is not a judgment that an abstention was semantically incorrect.

The script performs one baseline invocation, verifies it locally, then performs
at most one adaptive invocation. A failed baseline prevents the adaptive call.
Each uses a new conversation in the selected session, never `--new-session`.
Invoking an idle session may resume compute and incur charges. No automatic
invocation retry is added. Runtime limits are 10 analytical requests, Top-K 5,
120 analytical seconds and, for adaptive mode, six model calls capped at 1,024
completion tokens each. The CLI itself has no hard process-kill deadline;
operator monitoring and the separately approved cleanup deadline remain required.

## What is checked

Before invocation, the script verifies recorded initialization, reference hash,
resource-group ownership/inventory, local azd project/model/SQL bindings, active
agent name/version, directory object-to-client-ID mapping and model deployment
metadata. It requires SQL public access Disabled and exactly the recorded,
approved SQL private endpoint, subnet and NIC. Public/unknown IPs are rejected.

After each successful invocation, the same cloud context is read again. A
changed agent version, identity, model version, environment or SQL network
context fails the attempt. These are point-in-time checks, not continuous
network monitoring.

The local evidence validator then:

- Requires one complete `BPI_ANALYSIS_RESULT=` marker, strict JSON and successful
  analytical status; probe markers, duplicates and nonfinite JSON are rejected.
- Matches runtime SQL server/database, SQL SID, private DNS candidates, TLS,
  named permission checks and completed connection cleanup against expected context.
- Matches approved periods, coverage, sample identity, counts and execution budgets.
- Regenerates approved parameterized SQL plans without executing their SQL text.
- Compares **every captured aggregate**, including unselected adaptive results,
  to the hash-checked CSV and recomputes reported numerical results.
- Checks evidence/result references, baseline workflow, actual-inference labels,
  model identity, request counts and coherent known/unknown token accounting.

The fixed and adaptive requests use separate SQL transactions. Matching
initializer attestations and all checked aggregates establishes consistency
for the observed scopes; it is not a runtime cryptographic hash of the entire
SQL database. The numerical implementation is shared with the baseline; the
independent mathematical/reference tests remain the separate oracle.

## Reports, failures and cleanup

Each attempt receives a unique ignored directory:

```text
.artifacts/<environment>/cloud-analysis/<attempt-id>/
  context.json
  preparation.json
  evidence-validation.json
  report.json
```

The outer `report.json` records the session, agent/model context, attempted
invocations, client-observed invocation wall times and nested validated evidence.
Only a fully accepted pair permits the lifecycle state to become `validated`.
Failure leaves ownership state unchanged and records a sanitized failure stage.
State changes during the attempt are rejected instead of overwritten. A
per-experiment lock prevents concurrent validator runs; inspect a leftover lock
after an interrupted process rather than deleting it blindly.

Raw CLI transcripts are removed on normal exit, including failure; accepted
structured evidence remains. A later failure preserves the already verified
baseline and a bounded failure receipt (status, reported counters/token usage and
recognized diagnostic categories), not raw model prose or private reasoning.
Malformed/unrecognized fields are not copied into that receipt.
Reports are written before state promotion.
Costs remain explicitly unknown: token counts alone do not establish prices or
platform charges. A passed pair sets `real_model_quality_validated: false`.
It is neither a statistical comparison nor evidence that the model answered the
business question better than the fixed workflow.

The validator does **not** stop the session, revoke external model roles or
delete the experiment. Those remain separately authorized cleanup steps.
`cleanup` and `idleResume` remain `not_run` in this report.

## Recheck saved evidence locally

The Python CLI can recheck retained transcripts supplied by an operator, without
any cloud call:

```powershell
.\.venv\Scripts\python.exe -m analysis.cloud_validation `
  --csv .\.artifacts\adventureworks\internet_sales.csv `
  --context '<saved-context.json>' `
  --baseline '<baseline-transcript.txt>' `
  --adaptive '<adaptive-transcript.txt>' `
  --output .\.artifacts\saved-evidence-validation.json
```

This is labeled `execution_kind: offline_evidence_validation`, even for saved
cloud responses. It cannot independently prove that a live invocation occurred.
Omit `--adaptive` to check the baseline only; that returns `baseline_passed`,
not complete pair acceptance. Malformed input/evidence returns a nonzero exit
code and a failure report rather than leaving a previous successful report.
