# G0 technical validation plan

## Goal and current status

Prove that a small authenticated browser workbench can start, observe, and
explicitly resume a durable Foundry-hosted extraction job without making the
UI or a conversational model responsible for batch progression.

This document defines the complete G0 validation plan. The local execution
subset now has synthetic evidence, alongside separate live model, Azure Blob,
and hosted probes, as recorded below; the full G0 gate has not passed. A dedicated
storage slice has been deployed. Foundry native resilient tasks Preview is
selected for a [model-free batch feasibility slice](batch-hosting-feasibility.md).
A [bounded hosted probe](hosted-smoke-results.md) completed and its agent was
disabled afterward. Web hosting remains unselected,
and maintainer alignment is also still pending.

Read alongside the [implementation plan](implementation-plan.md) and
[source migration inventory](migration-inventory.md).

### Local execution evidence: September 14, 2026

The [offline execution core](../README.md) is a new, standard-library Python
implementation using a real local SQLite ledger and an injected synthetic
model. The base offline path does not use Azure; optional model and Blob
adapters are exercised separately. This initial core evidence does not cover
the later Invocations integration or Agent Framework.

Separately, the optional Responses model adapter has
[bounded live evidence](model-smoke-results.md): both synthetic chunks
completed after a prompt revision and a later explicitly authorized resume
of the second chunk's timeout. The first candidate was unchanged, and saved
resume replay made no model call. Persistence and execution were still local,
not Foundry-hosted.

The optional Blob adapter also has [live storage evidence](blob-store.md#observed-live-storage-evidence):
separate processes created and advanced the fixture, committed a controlled
failure, resumed to revision 3, and replayed all saved requests with no new
model work. This used real Azure Blob storage and a synthetic model, not the
real Foundry model. The [storage deployment](storage-deployment.md) confirmed
Entra operator access and anonymous denial. Hosted identity/gateway
observations are recorded separately below; workbench operator authorization
remains unverified.

The suite covers one-attempt commits, two explicitly advanced chunks,
historical request replay, independent connection ownership, subprocess
restoration, handled failure/resume, process exit, and publication rollback.
It also checks input/model identity, stale revisions, payload digest
corruption, source evidence resolution, and unknown versus observed usage.

| Probes | Current evidence | Remaining scope |
| --- | --- | --- |
| G0-01 | Isolated source build/import, platform remote build, and deployed Invocations startup succeeded. | Complete clean-environment Bicep/azd deployment remains unverified. |
| G0-02 through G0-06 | Offline ownership/failure/interruption contracts; live hosted commits, saved-request replay, and replacement-instance restoration after a known limit. Earlier Blob smoke covers controlled failure/resume. | No live concurrency or unknown-interruption injection; hosted failure/resume is not established by the limit/resume case. |
| G0-07 | Offline identity/revision and Blob integrity checks; valid history restored in a replacement hosted application. | No live corruption injection. |
| G0-08 | Native hosted task reached a persisted limit; explicit resume completed the remaining chunk through real Blob persistence. | Two chunks from one uninterrupted cloud start and browser-disconnect timing remain unverified. |
| G0-09 | Local Streamlit page/client recreation restores current progress and evidence; a separate native-task process and process restart preserve the job. | Hosted authenticated browser reconnect and live disconnect timing remain unverified. |
| G0-10 | Scoped runtime-identity Blob grant followed by successful hosted Blob/task operations; authenticated gateway calls and unauthenticated HTTP 401. | No designated web-operator allowlist, unauthorized signed-in-user test, or full effective-permissions audit. |
| G0-11 | Owned session stop, different hosted application UUID, unchanged durable status, explicit resume, and endpoint disable observed. | Unexpected in-flight crash/lease recovery, hard cancellation, and real-model lifecycle remain unverified. |
| G0-12 | Probe endpoint disabled and four session stops acknowledged; records report `idle`. | Source version, role, sessions and storage intentionally retained; deletion and final billing are not verified. |

Run the exact local command from the README to reproduce the suite. The
offline evidence alone does not establish Azure behavior; the live probes
cover only their stated paths. Neither establishes exactly-once model execution.

### Native batch evidence: September 15, 2026

The [native batch slice](native-batch.md) passed the local suite with the
actual installed AgentServer Core 2.1.0 SDK. Its model-free smoke moved from
`limited` to `completed` through explicit resume, reaching revision 2 with
two synthetic calls and zero real model calls. The task runtime and temporary
files were cleaned up after the command.

The developer smoke uses the public `AgentServerHost` lifespan with an
explicitly local JSON-file provider, without starting an HTTP server. Its
compatibility test rejects network/DNS/server-bind operations and verifies
cleanup after success and controlled failure. This proves local host
startup/shutdown, not managed provider availability. Separate private
task-manager tests wait for terminal SDK task-record deletion and confirm
that application inspection and duplicate start still do not repeat work.

Offline SQLite/Blob contracts exercise persisted deadlines and attempt
allowances, registration uncertainty, concurrent requests, handled
failure/resume, and old-round redelivery after a newer round advances.
Subprocess checks distinguish recovery after a known committed attempt from
blocking an unresolved claim. The Blob batch checks use a fake data plane;
the earlier live Blob evidence covers the one-attempt execution ledger, not
these new batch authorization records.

No new cloud resource or real model call was used for this local slice.
Subsequent hosted observations are recorded separately below.

### Synthetic Invocations and packaging evidence

The [hosted entry point](hosted-deployment.md) adds in-process ASGI evidence
through the actual Invocations 1.1.0 SDK, strict request validation, a single
configured synthetic job, and sanitized start/status/resume responses.
SQLite and fake-Blob tests restore status in a newly constructed application
before explicit resume; distinct application UUIDs identify those local
instances without exposing Azure resource identifiers.

Pre-upload review found two native SDK gaps: developer credential fallback
in its independently constructed async credential, and incomplete hosted
resource shutdown. Production-only credential policy and a pinned hosted
lifecycle adapter now cover both. Offline checks exercise effective
credential chains and resource ownership during normal shutdown, startup
failure, and cancellation. These are local SDK findings and fixes, not
evidence that the managed task service is available.

The source archive excludes real-model code and private environment state.
Its isolated build/import check does not install fresh cloud dependencies or
pass the deployed-startup portion of G0-01.

### Hosted evidence: September 15, 2026

The [hosted smoke record](hosted-smoke-results.md) documents the actual source
deployment and gateway/native-task/Blob path. A one-attempt round reached
`limited` at revision 1. After the owned session was stopped, a new session
returned a different application UUID and the identical first candidate.
Explicit resume completed revision 2; saved start/resume replay changed no
committed result. No real model calls were made.

The agent was disabled and its four listed sessions stopped, with preserved
records reporting `idle`. This is bounded live evidence, not a full G0 pass
or a claim of automatic recovery from an unknown in-flight outcome.

### Local workbench evidence: September 15, 2026

The [local Streamlit workbench](local-workbench.md) uses an independent
Invocations/native-task process with SQLite and the SDK's local-file provider.
Its actual process/HTTP/page flow reaches a one-attempt limit, restores the
first candidate in a fresh Streamlit `AppTest`, explicitly resumes to revision
2, then restarts the backend and restores both unchanged candidates with a
different application UUID. A fresh completed page offers no new-work button.

Separate page/client checks cover read-only initial render and refresh, exact
saved-request recovery/retry, pending-review evidence, visible backend errors,
and inspection-only unresolved claims. Backend SQLite/fake-Blob checks cover
current-job chain integrity, legacy ownership records, competing intents,
uncertain registration, and expired uncommitted requests. The two-process
launcher checks readiness without authorizing work and stops its owned
services while retaining normal workbench state.

No Azure resource, deployment, or real model was used. This is local UI and
reconnect evidence, not hosted authentication, an unexpected in-flight crash
probe, a live browser-disconnect timing test, or a completed G0 gate.

## 1. Smallest demonstration

Use a pre-registered, approved sample, a fixed extraction configuration, and
a deliberately small multi-chunk plan. Start with the existing supported
document path; generic schemas and the second domain remain G1 work.

The browser demonstration is:

1. Sign in as the designated operator.
2. Select the sample and fixed profile.
3. Start one job and observe durable progress.
4. Refresh or reconnect without starting additional work.
5. Observe a controlled failure and explicitly resume when safe.
6. Inspect candidate records with source evidence.

Candidates remain unreviewed. G0 does not claim approved business results,
complete review functionality, measured extraction accuracy, or full-document
format coverage.

Do not build schema generation, feedback editing, evaluation dashboards, a
Responses wrapper, or a full deployment template merely to prove this path.

## 2. Decisions to resolve before live execution

| Decision | Candidate direction | Evidence needed before selection |
| --- | --- | --- |
| Web hosting | Evaluate an Azure-managed web host for the existing Streamlit process; App Service is a candidate, not a selection. | Startup/dependency support, interactive connection behavior, Entra integration, identity, restart behavior, costs, and cleanup |
| Batch driver lifetime | Prefer deterministic bounded progression outside browser-request and page-rerun lifetimes. | A supported host lifecycle that survives client disconnect and has documented cancellation/deadline behavior |
| Driver placement | Operator selected Foundry native resilient tasks Preview for model-free feasibility; Durable Functions remains a fallback, not an approved deployment. | Real SDK compatibility, persisted application limits, and later hosted start/status/resume and process recovery; approve resource changes separately |
| Deployment interface | Preserve the existing Invocations approach unless evidence requires a change. | Clean package readiness and a supported source deployment/invocation path; confirm what azd can express |
| Identity | Entra operator access plus server-side managed identities. | Separate operator authorization and downstream resource roles; do not assume login alone grants mutation permission |

An in-memory background task, a thread launched from Streamlit, or a longer
HTTP timeout is not evidence of durable batch execution. If the hosting
contract cannot meet the lifecycle requirement, report G0 as blocked and
revise the design instead of silently introducing a UI-driven loop.

The live model and storage probes used separately approved environment
settings kept outside the repository. Those approvals do not select a
workflow/web host or authorize new recurring compute. Obtain the remaining
hosting choices, limits, and explicit approval before adding cloud resources.

## 3. Proposed execution interface

The following operations describe desired caller behavior, not methods that
already exist in DataFlowMVP:

| Operation | Inputs | Required behavior |
| --- | --- | --- |
| Start | Registered sample/profile version, durable request identifier, processing limits | Create or return the same job for a compatible repeated request; reject conflicting reuse |
| Inspect | Job identifier | Return durable progress, last committed revision, safe next action, and candidate/artifact availability; never trigger inference |
| Rediscover current job | Server-configured job; no browser-held run identifier | Read owned root/successor history and any pending HTTP intent; never create, schedule, reconnect, or renew work |
| Resume | Job identifier, expected revision, explicit request identifier | Advance only a safely resumable job with unchanged execution identity; reject stale or incompatible requests |
| Read candidates | Job identifier and committed result version | Retrieve verified artifacts server-side and return sanitized candidate/evidence views |

Persist request identity before scheduling work. An operator must be able to
rediscover the active job after browser state is lost; deduplication cannot
depend on a token that exists only in `st.session_state`.

Keep source/configuration/model/parser bindings stable during resume. A changed
binding requires a new job or an explicit future migration design, not a
silent continuation.

The existing `result` action can supply the initial inspect implementation.
The existing immutable revision contract can underpin resume. Start-once
progression and the workbench-facing projection are new work.

### Durable outcomes

Distinguish at least: queued/advancing work, partial committed progress,
completed selected plan, paused at a limit, committed handled failure, and
unresolved interruption. These are proposed display semantics, not a promise
to reuse the source's status strings unchanged.

Unknown model completion and incomplete checkpoint publication must not look
like either success or an automatically safe retry. No automatic claim
deletion, timeout takeover, or inference replay should be added to make a
demonstration pass.

### Bounded progression

The driver should sequence one-attempt commits and check limits before
scheduling another attempt. Define maximum attempts, elapsed time, and token
reservations for the experiment. Record usage when available.

Distinguish observed usage from estimates. A response timeout may leave model
usage unknown; a deadline is not a guarantee of provider-side cancellation or
an exact monetary cap. Pause and expose uncertainty rather than accounting
unknown usage as zero.

## 4. Probe sequence and acceptance matrix

Begin offline with synthetic inputs, a deterministic model adapter, and a
storage test adapter. Use the real workflow/execution module rather than a
fake UI demo. Move to live probes only after authorization and infrastructure
choices are recorded.

| ID | Probe | Required evidence and pass condition |
| --- | --- | --- |
| G0-01 | Package and startup | Build only explicitly allowed files. Clean runtime imports and readiness succeed using the deployed dependency manifest; record resolved versions and artifact hash. |
| G0-02 | One revision | One request produces at most one model attempt, preserves the remaining plan, and commits verified artifacts before its checkpoint. |
| G0-03 | Fresh execution process | Discard local working files and recreate clients. Inspect the same durable result, then advance from restored state without redoing a committed chunk. |
| G0-04 | Duplicate and concurrent mutation | Repeat a committed request and race two requests for one expected revision. One owner advances; duplicates return saved results or an explicit conflict, never another successful competing attempt. |
| G0-05 | Handled failure | Inject an explicit model/validation failure. Persist failure accounting, stop automatic progression, and verify explicit resume preserves completed work. |
| G0-06 | Unknown interruption | Interrupt execution or publication before commit. Show unresolved ownership and refuse blind replay; retain sufficient evidence for reconciliation. This passes by blocking safely, not by auto-recovering. |
| G0-07 | Integrity and stale state | Alter an input, configuration binding, artifact hash/length, or expected revision. Reject invalid restoration/continuation with a visible reason. |
| G0-08 | Bounded backend batch | One start advances at least two chunk revisions without browser-driven mutation. Stop at a configured limit or failure. A refreshed page cannot advance the job. |
| G0-09 | Browser reconnect | Close/reopen the browser connection while work is active. Rediscover the job, observe durable progress, and inspect evidence without leaking internal deployment metadata. |
| G0-10 | Operator and downstream access | The designated operator can mutate; unauthenticated and unauthorized users cannot. Server-side identity can perform only the required Foundry/Blob operations. |
| G0-11 | Live lifecycle and limits | Observe actual host deadline/cancellation/session behavior, process restart, pacing, and managed-identity calls. Confirm the chosen lifecycle supports G0-08/09; record unknown model outcomes explicitly. |
| G0-12 | Cleanup | Remove only experiment-owned resources and generated local artifacts. Retain sanitized findings; verify no continuing driver or recurring cost was unintentionally left behind. |

For a controlled two-chunk success fixture, require two committed chunk
attempts, expected block coverage, and no increase in model-call count after
duplicate inspect/start/revision requests. Count calls at the test adapter;
in live execution reconcile application attempts with available provider
observations rather than claiming exactly-once inference.

Run the smallest relevant migrated tests first. Existing source regression
anchors are listed in the migration inventory; their existence is not proof
that newly extracted code passes.

## 5. Evidence to record

Each executed probe should record its status as passed, failed, blocked, or
not run, with:

- Source/configuration versions, environment category, and execution time.
- Expected versus observed state, revision/attempt counts, and coverage.
- A sanitized failure explanation and any unresolved lifecycle assumptions.
- Whether observations came from a fake adapter, local real runtime, or Azure.
- Resource/cost observations and cleanup outcome for live probes.

Keep detailed operational identifiers and raw logs in an approved local or
private location, not the public template. Commit only sanitized reusable
findings, public/synthetic fixtures, and reproducible verification instructions.
Do not record a credentials-bearing URL as a convenient reproduction link.

## 6. Stop conditions and G0 exit

Stop and revisit the design if:

- Progress depends on a live browser connection or Streamlit rerun.
- Unknown interruption is treated as an automatically safe retry.
- A generic input is made to pass by pretending it has a financial identity.
- Authentication cannot restrict job mutation to the designated operator.
- A new hosting/coordination resource is required but not approved.
- Maintainers reject the intended scope.

G0 is complete only when contribution fit and technical feasibility are both
established. Technical exploration can proceed independently, but do not
claim maintainer acceptance or migrate a finished product before that
conversation occurs.

The exit deliverable is a small proven browser-to-cloud path, its actual
hosting/driver choices, a bounded execution contract, and evidence for the
probe matrix. It is not the full workbench. G1 then generalizes document and
schema handling and proves reuse with the second domain.
