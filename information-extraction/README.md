# Information extraction: local G0 core and optional Foundry model

This is a **new local implementation** of the execution invariants described in
the [migration inventory](docs/migration-inventory.md), not a copy of DataFlowMVP
or a Blob/SDK-compatible adapter. It is one preliminary step toward the
[implementation plan](docs/implementation-plan.md). **G0 is not complete.**

The core uses real transactional SQLite persistence and an injected model
adapter. Tests provide a synthetic model; an **optional Foundry Responses
adapter** can invoke an explicitly selected deployment. The core has no runtime
dependencies outside Python's standard library. No Azure hosting or storage is
provided.

A [bounded live model smoke](docs/model-smoke-results.md) exercised an existing
DeepSeek deployment: one chunk succeeded after an explicit prompt revision,
and the next timed out. This is partial model integration evidence, not a
completed batch or cloud-hosting validation.

## Run the offline checks

Prerequisite: Python **3.13 or newer**. From the repository root, in PowerShell:

```powershell
Set-Location .\information-extraction
# Adjust this executable path if Python was installed elsewhere.
$python = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
& $python --version
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
& $python -m unittest discover -v
```

This source-based route requires no package installation, Azure credentials,
network access, or model service. Tests create uniquely named directories under
`.test-data` in the current directory and remove them on completion. They launch
real subprocesses and exercise independent SQLite connections, including a
deliberate process exit and a publication-lock failure.

Optional editable installation, from the same directory:

```powershell
& $python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e .
& .\.venv\Scripts\python.exe -m unittest discover -v
```

Editable installation may download the setuptools build backend; it is not
needed for the offline checks. With the Azure extra installed, additional tests
exercise real SDK response deserialization against `httpx.MockTransport`, not
Azure. Without the extra, those tests skip; core and read-only smoke tests still
run.

## Small execution interface

The caller supplies a `Model` adapter with a stable `binding` string and a
synchronous `complete(ModelRequest) -> ModelResponse` method. The binding is a
non-secret versioned identifier for the actual deployment/model/settings, not
an endpoint, credential, or an automatically discovered provider identity.
The adapter is responsible for honoring it and disabling automatic retries.
The core rejects an adapter whose binding differs from the persisted plan.

Library usage with your adapter (not a configured live-model example):

```python
from information_extraction import Action, Execution, SQLiteStore
from information_extraction.sample import synthetic_plan
from dataclasses import replace

execution = Execution(SQLiteStore("ledger.sqlite3"), model_adapter)
plan = replace(synthetic_plan(), model_binding=model_adapter.binding)
created = execution.create("job-1", plan, "create-1")
current = execution.read("job-1")  # Always read-only.
first = execution.advance("job-1", 0, "advance-1")
second = execution.advance("job-1", 1, "advance-2")

# Only if the current committed state is FAILED:
# current = execution.read("job-1")
# resumed = execution.advance(
#     "job-1", current.revision, "resume-1", action=Action.RESUME
# )
```

The two explicit calls above demonstrate the one-attempt interface; they are
**not a batch driver**. An `advance` call runs in its caller's synchronous
process. No work progresses after `create`, on inspection, or independently
of that process.

### Identity, replay, and ownership

- `create` freezes the entire pre-normalized source plan before inference.
  Identity hashes bind document/chunk/block identifiers, text, source
  locations, ordering, fixed schema version, profile version, parser version,
  and model binding. There is no normalization or mutable configuration lookup.
- A compatible new create request for an existing job returns its current
  state; changing its plan conflicts. An identical consumed request returns
  its **saved historical snapshot**, which may differ from the latest state.
  Use `read` to refresh.
- Request identifiers are globally unique **within a ledger**, not merely per
  job. Reusing an identifier for a different job, operation, expected revision,
  or create configuration raises `Conflict`. Keep them durable at the caller;
  do not generate a new identifier on every transport retry.
- Each advance requires a nonnegative integer expected revision (not a boolean)
  and a request identifier. Stale new requests raise `StaleRevision`. Replays
  of consumed requests are checked before staleness and never repeat inference.
- A short SQLite transaction grants one immutable claim per job revision.
  It commits before the model call and holds **no database lock during
  inference**. A second worker or repeated unresolved request gets `Blocked`.
- Candidates, attempt accounting, coverage, the next checkpoint, and the saved
  request result publish in one transaction. Claims and checkpoints are never
  deleted or overwritten by this interface.

Identifiers use 1–128 ASCII letters, digits, `.`, `_`, `:`, or `-`, beginning
with a letter or digit. Blocks must contain non-whitespace source text and a
source location. Chunk IDs and document-wide block IDs must be unique.

### Outcomes and safe next actions

| Status | Meaning and allowed next action |
| --- | --- |
| `ready` | Selected work remains; explicitly advance at the current revision. |
| `completed` | All selected chunks committed; inspect only. This is not a review/quality verdict. |
| `failed` | A declared model or structural validation failure committed; only an explicit `Action.RESUME` may attempt the failed chunk again. |
| `in_progress_or_interrupted` | A durable unresolved claim exists. Inspect only; never blindly resume or retry inference. |

`ModelFailure` accepts only `MODEL_TIMEOUT` or `MODEL_REJECTED`, plus optional
observed `TokenUsage`. These declared outcomes commit a safe code, not a raw
provider error. A timeout may still have incurred provider work or cost.
Malformed response structure, evidence, or token usage commits a
`ValidationFailure` code. Unknown usage is `None`, never assumed to be zero.
Valid usage received alongside invalid record content is retained.

Other exceptions, cancellation, and SQLite publication errors **propagate**.
The durable claim remains unresolved, even when the model may have finished.
There is no claim expiry, takeover, automatic replay, or reconciliation
operation. An active and an interrupted process intentionally have the same
inspect state: the ledger cannot safely distinguish them. There is no
exactly-once provider-inference guarantee. A future operator reconciliation
design must not blindly delete these claims. Callers must avoid logging raw
unknown provider exceptions, which can contain sensitive diagnostics.

### Fixed records and source evidence

`synthetic_plan()` contains two chunks, each with two identified source blocks.
It is fictional financial text, not an SEC parser or proof of another domain.
The only supported schema is `financial-metrics-v1`. A model response payload
must be a dictionary with exactly this structure:

```json
{
  "records": [
    {
      "metric": "revenue",
      "value": 120,
      "unit": "USD_millions",
      "block_ids": ["block-1"]
    }
  ]
}
```

`metric` is `revenue` or `operating_income`; `value` is a finite Python integer
or float, never a boolean; `unit` is `USD_millions`. Zero records is allowed.
Unknown fields are rejected except optional `quote`, which is ignored and
never persisted. Raw JSON strings are not accepted: the adapter must supply
the structured object.

Each record must cite nonempty, nonrepeated block IDs from the **current chunk**.
The core reconstructs evidence text and locations from the persisted original
blocks, never from a model quotation. Successful attempt coverage records all
blocks supplied in that chunk; it does not prove every fact was extracted.
Candidates carry job/revision/plan metadata, `review_status=pending`, and
`semantic_validation_performed=False`. Location/shape checks are not semantic
validation, human approval, or measured accuracy. A zero-candidate chunk is
not evidence that a reviewer found no relevant facts.

## Optional Azure Foundry model adapter

Install the optional SDKs into your own environment, from this directory:

```powershell
& .\.venv\Scripts\python.exe -m pip install -e '.[azure]'
& .\.venv\Scripts\python.exe -m unittest discover -v
```

Import `FoundrySettings`, `FoundryModel`, and `open_foundry_model` explicitly from
`information_extraction.foundry_model`; the base package never imports this
module. `FoundryModel(settings, openai_client)` accepts a caller-owned actual
`openai.OpenAI` client. `open_foundry_model(settings, credential)` is a context
manager owning the `AIProjectClient`, OpenAI client, and HTTP transport; the
credential remains caller-owned. It uses project-scoped bearer authentication,
not API keys. Injected clients must target the configured project and must not
add their own retries, redirects, or request-mutating middleware.

Settings require an HTTPS project endpoint and deployment identifier.
`max_output_tokens` is an integer from 1 to 32768 (default 2048), and `timeout`
is finite and positive (default 180 seconds). These are request controls, not a
total wall-clock deadline or cost budget. Optional `reasoning_effort` accepts
`none`, `minimal`, `low`, `medium`, `high`, or `xhigh`; **support depends on the
selected deployment**, and omission sends no reasoning setting. The adapter
does not discover deployments or assume that every model supports strict
structured output, Responses, or a particular reasoning setting.

Prompt version `financial-extraction-v2` includes the same output schema in the
instructions as in the strict response-format request, with explicit enum
spelling. This improves guidance; it does not substitute for local validation
or prove provider-side schema enforcement. Invalid values are never silently
normalized. Changing the prompt changes the binding and requires a new job.

- The binding hashes the explicit endpoint, deployment, profile, schema,
  prompt/version, and request settings. Only the hash enters the plan, not the
  endpoint. A deployment identifier is **not proof of an underlying model
  version**; a deployment can be changed outside this ledger.
- Requests send only the current chunk's blocks and relevant profile/schema
  fields, with source data separated from instructions. Strict JSON Schema
  requests the fixed metrics structure without a `quote` field. No tools are
  supplied, `store=False`, and SDK retries are disabled even for injected
  clients. The factory disables HTTP redirects and environment-derived proxy
  settings. `store=False` is not a claim about all provider retention policies.
- Refusal, incomplete output, and malformed JSON become structural validation
  failures, retaining reported usage. Duplicate keys, nonfinite numbers, and
  trailing JSON are rejected. Missing/partial usage remains unknown.
- Timeouts commit `model_timeout`; explicit rejection statuses
  400/401/403/404/405/413/415/422/429 commit `model_rejected`. Neither causes
  an automatic retry. Connection failures, server errors, redirects, and
  unclassified statuses (including 408) raise the safe
  `ProviderOutcomeUnknown("provider_outcome_unknown")` and leave the claim
  unresolved. Other Python errors propagate unchanged. Never log raw unknown
  exceptions or enable provider HTTP/debug logging around real requests.

### Explicit developer smoke path

This is an operator validation CLI, **not the final user's UI**, a batch driver,
or a live-validation claim. It accepts only the two-chunk fictional fixture and
refuses to print a ledger containing a different source plan. You must separately
select and verify your Azure CLI identity, authorization, project, and deployment.
The script uses only `AzureCliCredential`, never a default chain that silently
switches identity. It does not install the CLI, log you in, discover models, or
provision resources.

Set `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_MODEL_DEPLOYMENT` privately in your
operator environment, or pass `--project-endpoint` / `--deployment` explicitly.
Prefer environment variables to keep resource names out of shell history.
Do not commit their actual values. From `information-extraction`:

```powershell
$python = '.\.venv\Scripts\python.exe'
$job = 'fictional-smoke-001'
$modelOptions = @('--max-output-tokens', '2048', '--timeout', '180')
# Only when the selected deployment supports it; use identical settings each time:
# $modelOptions += @('--reasoning-effort', 'low')

# Freezes the fixture and binding; no credential acquisition or inference.
& $python .\scripts\model_smoke.py --action create --job-id $job --request-id create-001 @modelOptions

# Read-only, no Azure extra, endpoint, deployment, or credentials required.
& $python .\scripts\model_smoke.py --action inspect --job-id $job

# Explicitly permits at most ONE current-chunk model attempt.
& $python .\scripts\model_smoke.py --action advance --job-id $job --request-id advance-001 --expected-revision 0 @modelOptions
& $python .\scripts\model_smoke.py --action inspect --job-id $job

# Only after inspecting a committed FAILED revision and choosing another attempt:
# & $python .\scripts\model_smoke.py --action resume --job-id $job --request-id resume-001 --expected-revision 1 @modelOptions
```

`--ledger` defaults to the ignored `.local-data/model-smoke.sqlite3`. Use the
same ledger, settings, and durable request identifiers across restarts. Each
invocation performs only its named action. A repeated consumed request returns
the historical result without inference; a new request for an unresolved claim
is blocked. **Never auto-resume an unresolved claim**, including after a timeout
in the operator process. Inspect first. To finish the second chunk, separately
choose `advance` at the newly inspected ready revision with a new request ID.

Output contains only state/revision, safe failure codes, counts, known token
totals with unknown/unresolved counts, and fictional candidate records/evidence.
It omits endpoint, deployment, tenant, credentials, and raw provider errors.
Exit codes: 0 ready/completed, 1 failed/unresolved snapshot, 2 safe domain or
argument error, 3 local storage error requiring inspection, 130 interrupted.
Before claiming an attempt, the script checks CLI token acquisition so a
missing login does not strand a new claim. Authentication failure is explicit
and does not print credential diagnostics. The CLI suppresses SDK logging and
reports known domain/storage failures without raw exception details. Unexpected
programming errors still propagate; inspect the ledger rather than assuming
rollback, and do not share unsanitized tracebacks.

Tests cover requests, SDK decoding, usage retention, no retries, safe failure
classification, factory resource closure, and create/inspect/advance/replay/resume
against a fake HTTP transport. They do **not** verify live identity/RBAC,
deployment capabilities/version, service billing, or extraction accuracy.
The separate [live smoke record](docs/model-smoke-results.md) documents the
limited observed outcome. No semantic validation, approval, full G0 pass,
or completed live batch is claimed.

## Storage and scope limitations

`Store` is the narrow internal storage seam; `SQLiteStore` is its sole concrete
adapter. Its contracts concern transactional create/read/claim/publish, not
Blob object names or hosted SDK sessions. SQLite uses a local file, fresh
connections, full synchronous commits, and digest-checked plan/checkpoint
payloads. Digests detect accidental payload changes, **not malicious tampering
by someone who can rewrite the database and hashes**.

The ledger contains plaintext source text, evidence, configuration, and
historical snapshots. **It is not encrypted and has no application-level
authentication or authorization.** Keep it on a trusted local filesystem with
appropriate OS permissions; do not commit or expose it. Do not supply secrets
as identifiers or source fixtures. Do not use a network share or assume this is
distributed/cloud coordination. Large-document scale, backup/migration,
power-loss behavior on particular storage hardware, and retention policies
have not been validated. Remove only your own generated ledger after use.

Not implemented: Foundry hosting, Agent Framework/Invocations integration,
Azure/Blob storage adapters, managed-identity deployment, browser/UI/HTTP transport, a daemon or
bounded batch driver, deadlines/budgets, input normalization, generalized
schemas, evaluation, semantic validation, or review operations.

The stdlib suite provides local synthetic evidence relevant to G0-02 through
G0-06 and the identity/staleness portion of G0-07. It does **not** pass the full
[G0 validation gate](docs/g0-validation-plan.md), package/deployed startup,
Blob artifact integrity, or any cloud, browser, authentication, lifecycle,
cost, maintainer-alignment, or cleanup-of-cloud-resources probe.
