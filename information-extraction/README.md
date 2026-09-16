# Information extraction: configurable core and workbench preview

This is a **new implementation** of the execution invariants described in
the [migration inventory](docs/migration-inventory.md), not a copy of DataFlowMVP
or a drop-in replacement for its hosted SDK interface. It is one step toward the
[implementation plan](docs/implementation-plan.md). **G0 is not complete.**

The core uses an injected storage and model interface. Transactional SQLite
is the standard-library local implementation; an optional **Azure Blob ledger**
provides create-only cloud persistence. An optional **Foundry Responses adapter**
can invoke an explicitly selected deployment. Azure SDKs are opt-in. A
[storage-only Bicep template](docs/storage-deployment.md) and a
[synthetic hosted source-deployment path](docs/hosted-deployment.md) are
available. A repeatable full-workbench deployment template is not implemented.

A [bounded live model smoke](docs/model-smoke-results.md) completed both
synthetic chunks on an existing DeepSeek deployment after an explicit prompt
revision and a later, separately authorized timeout resume. First-chunk
progress was preserved. This is local execution with real model calls, not
cloud-hosting or automatic batch-progression validation.

A separate [live Blob smoke](docs/blob-store.md#observed-live-storage-evidence)
used a synthetic model with real Azure persistence. Fresh processes restored
committed progress, resumed a handled failure, and replayed saved requests
without repeating model work. Real Foundry calls and Blob persistence have
not yet been exercised together.

An optional [native batch driver](docs/native-batch.md) now provides durable
start/status/explicit-resume semantics around the execution core, using
Foundry resilient tasks Preview. A [bounded hosted smoke](docs/hosted-smoke-results.md)
reached an attempt limit, restored committed state in a replacement
application instance, and completed through explicit resume with no real
model calls. The probe agent was then disabled and its sessions stopped.
**G0 remains incomplete.**

## Second domain: ABCD customer support

ABCD is the selected second domain alongside financial reports. A
[bounded offline importer](docs/abcd-support-sample.md) converts local
ABCD-format conversation subsets into stable source blocks, preserving speakers
and original turn locations while excluding hidden scenarios, task labels and
action events from dialogue evidence. An independently authored format fixture
is included; no upstream conversations are bundled.

The [configurable core and two-domain rehearsal](docs/configurable-extraction.md)
now run financial and support profiles through the same schema/evidence
validation and durable execution path. Profiles are frozen into versioned
plans; candidates contain flat business values plus framework-owned per-field
source references. The JSON profile loader rejects unsupported constructs.
SQLite and Blob codecs support these plans without changing legacy G0 plan or
request identity.

The rehearsal uses **scripted fixture responses, not real support extraction
or an accuracy benchmark**. The optional Foundry Responses adapter can derive
its prompt/schema from a frozen profile, but that configured provider path has
only offline transport coverage. The existing synthetic cloud/local workbench
is unchanged; support UI, general document upload, review/export, held-out
evaluation, and full G1 remain open. No Azure resources or real-model calls are
needed for the local rehearsal.

## Try the local workbench

The [Streamlit workbench](docs/local-workbench.md) runs against an independent
local Invocations/native-task process with SQLite persistence. It supports
explicit start/resume, read-only current-job discovery, progress, candidate
records, and original source evidence. Browser refresh/reopen does not need
a saved run ID and does not authorize new work.

From `information-extraction`, using a Python 3.13+ virtual environment:

```powershell
& .\.venv\Scripts\python.exe -m pip install -e '.[hosted,workbench]'
& .\.venv\Scripts\python.exe .\scripts\run_workbench.py
```

Open `http://127.0.0.1:8501`. The default one-attempt allowance deliberately
pauses after the first of two fictional chunks; explicitly resume to complete
the second. All results remain pending review. Ctrl+C stops the launcher's
own services while retaining `.local-data\workbench`; restarting with that
directory restores the job.

For a new demonstration without resetting that history, use the
[fresh acceptance manifest and repeatable local rehearsal](docs/local-workbench.md#prepare-independent-acceptance-jobs).
They cover bounded start/limit/resume, two chunks from one start, evidence
inspection and completed-process restoration in independent job namespaces.
Preparation does not deploy, open a public endpoint or call a real model.

This preview is **local and synthetic only**: no Azure resources, credentials,
or real models. Both listeners bind to `127.0.0.1`. It has no operator
authentication and must not be exposed through a tunnel or shared host.
Hosted deployment, end-to-end authorization, uploads, configurable schemas,
and approval/export are not part of this slice.

The next cloud slice is scoped in the
[hosting and authorization plan](docs/workbench-hosting-auth-plan.md), with
[primary-source findings](docs/workbench-hosting-auth-research.md). It is a
selected architecture and resource/permission checklist, not approval to
create resources. A separate [cloud entry point and authorization/client
implementation](docs/cloud-workbench.md) now has local signed-token,
HTTP, and UI-fixture coverage, plus the bounded live read-only browser
evidence described below. WebSocket expiry/reconnect and exhaustive
effective-access validation remain open. The
[read-only preflight](docs/workbench-hosting-preflight.md) records the runtime,
scoped resource/role inventory and indicative B1 price. An
[empty web-host slice](docs/web-host-deployment.md) was created in approved
West US 2 after East US quota rejection, in the same existing resource group.
The site remains stopped with public access disabled; its retained B1 plan
continues billing. A subsequent [approved identity slice](docs/web-identity-configuration.md)
configured single-operator Easy Auth, its protected login credential, and an
agent-scoped web managed identity. Application deployment and live
authorization checks remain separate gates. A [guarded deployment slice](docs/guarded-deployment.md)
added distinct web packaging and created backend version 2 with the
`current` interface and an explicit Invocations `2.0.0` declaration, while
keeping its endpoint disabled. After explicit private-staging approval, the
web ZIP completed remote Oryx build and ARM OneDeploy deployment through a
dedicated private container and container-scoped operator grant. The web
app remains stopped/public-access-disabled. A later bounded private probe
confirmed platform startup, then stopped the site and restored Always On
to false. A subsequent real-caller test returned HTTP 200 for the operator's
read-only version-2 `current` request and HTTP 403 for an unapproved user's
identical request; the agent and new session were closed afterward.
A subsequent [bounded anonymous-login diagnosis](docs/guarded-deployment.md#anonymous-login-precheck-aborted-window-and-diagnosis)
returned HTTP 401 with no redirect for both tested Accept profiles, then
closed the web-only probe. A separately approved
[browser comparison](docs/guarded-deployment.md#browser-versus-script-and-explicit-login-comparison)
observed Edge HTTP 302 to the configured tenant, unlike Requests HTTP 401;
the private precheck now uses a browser. The site is closed again.
An initial human window closed without results. A later
[confirmed human window](docs/guarded-deployment.md#human-acceptance-protected-current-job-read-and-unapproved-user-denial)
provided screenshots of the unapproved identity's Entra `AADSTS50105`
denial and the protected cloud page showing the historical completed job
at revision 2, with 2/2 chunks. This supports the deployed browser and
managed-identity current-read path, not new extraction or an exhaustive
identity audit. The sole new session was stopped, leaving six idle sessions.
A later [fresh execution acceptance](docs/guarded-deployment.md#human-execution-acceptance-start-limit-resume-and-source-evidence)
demonstrated protected Start, limit at revision 1, explicit Resume to
completed revision 2, and expanded evidence for both Pending candidates.
That window stopped its one new session and preserved the six baseline
sessions. All seven retained sessions are idle and the web app/agent are
closed again. WebSocket expiry/reconnect, single-start two-chunk cloud
progression and broader route/access acceptance remain outstanding.
Protecting only
the web login does not protect a separately callable Foundry endpoint.

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
network access, or model service. Tests use temporary directories, including
unique folders under `.test-data`, and remove them on completion. They launch
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

With `.[hosted,workbench,test]` installed, additional tests exercise Streamlit
`AppTest`, actual loopback HTTP listeners, an independent native-task process,
and local process restart. They make no Azure or real model calls. These
optional checks require permission to bind local ports; they are distinct
from the dependency-free, no-network core route above.

## Small execution interface

The caller supplies a `Model` adapter with a stable `binding` string and a
synchronous `complete(ModelRequest) -> ModelResponse` method. The binding is a
non-secret versioned identifier for the actual deployment/model/settings, not
an endpoint, credential, or an automatically discovered provider identity.
The adapter is responsible for honoring it and disabling automatic retries.
The core rejects an adapter whose binding differs from the persisted plan.

Legacy G0 library usage with your adapter (not a configured live-model example):

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
process. `Execution.create` and inspection do not schedule work. Use the
separate optional batch interface below for bounded task-backed progression.

### Identity, replay, and ownership

Identity and replay rules apply to both stores. The transaction details below
describe SQLite; the [Blob protocol](docs/blob-store.md) instead publishes
immutable objects with a final checkpoint commit marker.

- `create` freezes the entire pre-normalized source plan before inference.
  Identity hashes bind document/chunk/block identifiers, text, source
  locations, ordering, schema version, profile version, parser version,
  and model binding. Configured plans additionally freeze the entire
  schema/instructions and any dialogue speaker labels. Legacy plan encoding is
  unchanged. There is no normalization or mutable configuration lookup.
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

Other exceptions, cancellation, and storage publication errors **propagate**.
The durable claim remains unresolved, even when the model may have finished.
There is no claim expiry, takeover, automatic replay, or reconciliation
operation. An active and an interrupted process intentionally have the same
inspect state: the ledger cannot safely distinguish them. There is no
exactly-once provider-inference guarantee. A future operator reconciliation
design must not blindly delete these claims. Callers must avoid logging raw
unknown provider exceptions, which can contain sensitive diagnostics.

### Legacy G0 records and source evidence

`synthetic_plan()` contains two chunks, each with two identified source blocks.
It is fictional financial text, not an SEC parser or proof of another domain.
The legacy `Plan` wire format supports only `financial-metrics-v1`. Its model
response payload must be a dictionary with exactly this structure. New
`ConfiguredPlan` jobs instead use the
[flat fields/evidence envelope](docs/configurable-extraction.md):

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

The default legacy prompt `financial-extraction-v2` includes the same output schema in the
instructions as in the strict response-format request, with explicit enum
spelling. This improves guidance; it does not substitute for local validation
or prove provider-side schema enforcement. Invalid values are never silently
normalized. Changing the prompt changes the binding and requires a new job.

For configured extraction, pass `profile=selected_profile` and the matching
`profile_version=selected_profile.version` to `FoundrySettings`. Build the
`ConfiguredPlan` from that same profile and `settings.binding`. This uses
`flat-extraction-v1`, deriving both instructions and output schema from the
frozen profile. Configured and legacy model bindings cannot be interchanged.
Only offline mocked transport has exercised this new provider path so far.

- The binding hashes the explicit endpoint, deployment, profile, schema,
  prompt/version, and request settings. The model-settings hash, not the
  endpoint, enters `model_binding`; configured plans also retain their full
  extraction profile. A deployment identifier is **not proof of an underlying model
  version**; a deployment can be changed outside this ledger.
- Requests send only the current chunk's blocks and relevant profile/schema
  fields, with source data separated from instructions. Strict JSON Schema
  requests either the legacy metrics structure or configured fields/evidence,
  without model-supplied framework quotes. No tools are
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
or hosted background batch execution is claimed.

## Optional bounded native batch driver (Preview)

`Batch` adds durable authorization rounds with **at most five attempts per
round**, an absolute scheduling deadline, and explicit resume after a
committed failure or limit. Both SQLite and Blob support its create-only
records. Limits are not reset by task recovery or transport retry; ambiguous
execution claims stay blocked rather than triggering another model call.

The native adapter uses pinned `azure-ai-agentserver-core==2.1.0` with
resilience explicitly enabled and framework exception retries disabled.
The application ledger, not SDK task-record retention, protects completed
work. Status is read-only and does not call an SDK reconnection method.

From `information-extraction`, run the bounded **synthetic-only** SDK smoke:

```powershell
& .\.venv\Scripts\python.exe -m pip install -e '.[hosted]'
& .\.venv\Scripts\python.exe .\scripts\batch_smoke.py
```

This uses the actual SDK's public `AgentServerHost` lifespan with its local
JSON-file task provider and local execution ledger. It demonstrates a one-attempt limit followed by explicit
resume: `limited` then `completed`, revision 2, two synthetic calls, zero
real model calls. It shuts down its local runtime and removes temporary
files. It needs no Azure login or resource configuration.

The harness explicitly selects local state and does not bind an HTTP server.
It validates local host startup/shutdown, not a deployed invocation route,
managed task-service recovery, browser disconnection, or managed-identity
authorization. See [native batch usage and limitations](docs/native-batch.md)
and the [hosting feasibility decision](docs/batch-hosting-feasibility.md).

## Synthetic hosted entry point and source package

The [Invocations entry point](docs/hosted-deployment.md) exposes strict JSON
start/status/resume operations for one configured synthetic job. Production
uses Blob and the hosted task backend only; no real-model switch, arbitrary
document input, or local fallback is provided.

Local checks exercise the actual Invocations SDK over in-process ASGI,
including replacement-application inspection and explicit resume. The
allowlisted ZIP excludes the real-model adapter, credentials, local ledgers,
tests, and documentation:

```powershell
& .\.venv\Scripts\python.exe -m pip install -e '.[hosted,test]'
& .\.venv\Scripts\python.exe .\scripts\invocations_smoke.py
& .\.venv\Scripts\python.exe .\scripts\package_source.py `
    --output .\.local-data\synthetic-agent.zip --check
```

The package check builds a wheel and imports the entry point in isolated
Python using installed dependencies, with network access blocked. It is
not a remote-build or cloud-recovery result. The initial deployment probe
uses existing Foundry gateway permissions, not a designated-operator web
allowlist. The [deployment guide](docs/hosted-deployment.md) covers approval,
runtime identity, pinned SDK lifecycle ownership, session affinity, and stop
semantics.

## Storage and scope limitations

`Store` is the narrow internal storage seam implemented by `SQLiteStore` and
the optional `BlobStore`. Its contracts concern create/read/claim/publish,
not hosted SDK sessions. SQLite uses a local file, fresh
connections, full synchronous commits, and digest-checked plan/checkpoint
payloads. Digests detect accidental payload changes, **not malicious tampering
by someone who can rewrite the database and hashes**.

The SQLite ledger contains plaintext source text, evidence, configuration, and
historical snapshots. **It is not encrypted and has no application-level
authentication or authorization.** Keep it on a trusted local filesystem with
appropriate OS permissions; do not commit or expose it. Do not supply secrets
as identifiers or source fixtures. Do not use a network share or assume this is
distributed/cloud coordination. Large-document scale, backup/migration,
power-loss behavior on particular storage hardware, and retention policies
have not been validated. Remove only your own generated ledger after use.

The Blob adapter stores the same sensitive content in Azure and relies on
separately configured storage access controls. The provided storage slice uses
Entra authorization, disables anonymous/Shared Key access, and enables
Microsoft-managed encryption. It does not add application-level user
authorization. Blob payloads are capped at 8 MiB per encoded object, snapshots
are cumulative, and reads verify full history: this is a bounded G0 ledger,
not a large-document storage design. See [Blob contracts and smoke commands](docs/blob-store.md)
for ambiguous-write handling, integrity checks, and retention limitations.

Not yet verified or completed: unexpected-crash recovery in the managed host,
real-model-plus-hosted-Blob execution, Agent Framework integration, browser/UI,
designated-operator authorization, total-token or billed-cost enforcement, input normalization, generalized
schemas, evaluation, semantic validation, or review operations.

The offline suites and bounded live model, storage, and hosted probes provide
partial evidence for the [G0 matrix](docs/g0-validation-plan.md), including
hosted startup, persistence, and replacement-instance restoration. They do
**not** pass the full gate, browser/operator authorization, unknown-outcome
recovery, cost limits, maintainer alignment, or full resource cleanup.
