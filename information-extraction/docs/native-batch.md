# Bounded native batch execution (G0 Preview)

`Batch` supplies a host-independent start/status/explicit-resume interface
around the existing one-attempt `Execution`. The optional native adapter
registers that work with Foundry resilient tasks. Application authorizations,
attempt admissions, committed results, and terminal decisions remain in the
SQLite or Blob ledger, not SDK task outputs.

This slice has **model-free local SDK evidence**. It is not a deployed hosted
agent, an authenticated workbench endpoint, or proof of managed Foundry task
recovery. See the [hosting decision and primary sources](batch-hosting-feasibility.md)
and the [remaining G0 probes](g0-validation-plan.md).

## Install and run the synthetic smoke

From `information-extraction`, with the project virtual environment created:

```powershell
& .\.venv\Scripts\python.exe -m pip install -e '.[hosted]'
& .\.venv\Scripts\python.exe .\scripts\batch_smoke.py
```

For Blob and the existing Azure model adapters, install `.[azure,hosted]`
instead. The hosted extra pins `azure-ai-agentserver-core==2.1.0`. Base
package dependencies remain empty; batch types are explicitly imported from
`information_extraction.batch`, and the optional SDK adapter from
`information_extraction.native_batch`.

The bounded smoke has no real model or Azure data plane. It enters the
public `AgentServerHost` lifespan with the SDK's local JSON-file task
provider and a temporary SQLite execution ledger,
reaches a one-attempt limit, and explicitly resumes the second chunk.
Expected output includes:

```json
{
  "lifecycle": "AgentServerHost",
  "provider": "native-local-file",
  "first_round": "limited",
  "final_round": "completed",
  "revision": 2,
  "synthetic_model_calls": 2,
  "real_model_calls": 0,
  "cloud_recovery_verified": false,
  "sdk_version": "2.1.0"
}
```

The command shuts down its local task runtime, restores temporary environment
settings, and removes its temporary files. It does not bind an HTTP server.
SDK experimental-feature warnings are expected; they are not cloud
validation or errors to bypass by disabling resilience.

## Interface and wiring

The same store can implement the extraction and batch-record interfaces:

```python
import time

from information_extraction import Execution, ModelResponse, SQLiteStore
from information_extraction.batch import BatchLimits
from information_extraction.native_batch import create_native_batch
from information_extraction.sample import synthetic_plan


class SyntheticModel:
    binding = "synthetic-model-v1"

    def complete(self, request):
        return ModelResponse({"records": []})


store = SQLiteStore("ledger.sqlite3")
execution = Execution(store, SyntheticModel())
execution.create("example-job", synthetic_plan(), "example-create")

# Configure once, before the native host lifespan starts.
batch = create_native_batch(execution, store)


async def start_from_initialized_host():
    limits = BatchLimits(max_attempts=5, deadline=time.time() + 60)
    return await batch.start("example-job", 0, "example-batch-start", limits)
```

This is wiring, not a standalone host or an HTTP operation. The factory
enables resilience and registers the task handler; it does not start a host,
create credentials, select a model, or provision resources. A later hosted
entry point must independently authenticate and authorize the operator.

For cloud application persistence, substitute
`BlobStore(container, prefix=...)`, using an already configured authenticated
`ContainerClient`, and pass that store to both `Execution` and the factory.
The current batch tests use a fake Blob data plane; live validation of these
new authorization records remains separate from the earlier
[one-attempt Blob smoke](blob-store.md#observed-live-storage-evidence).

| Operation | Result and contract |
| --- | --- |
| `await batch.start(job_id, expected_revision, request_id, limits)` | Returns a frozen `Authorization`. New starts require an existing READY execution at that revision; authorization is persisted before scheduling. |
| `batch.status(run_id)` | Returns `BatchStatus` without scheduling, reconnecting a native task, or invoking a model. |
| `await batch.resume(previous_run_id, expected_revision, request_id, limits)` | Returns one new `Authorization` after a durably closed FAILED or LIMITED round. Repeated compatible requests retain the same successor and allowance. |

`Batch.run` is the worker entry point used by the scheduler, not a
browser-driven per-chunk advance operation.

`Authorization` contains `run_id`, `job_id`, `request_id`, `plan_fingerprint`,
`expected_revision`, `limits`, and optional `previous_run_id`. Preserve the
request identifier and exact limits at the caller. **Do not recompute the
deadline or generate another request ID on a transport retry.** Compatible
saved requests retain their original deadline even after it expires.

## Limits, status, and errors

`BatchLimits` requires an explicit absolute Unix timestamp in `deadline`.
Although its constructor has a `0.0` sentinel, `BatchLimits()` alone is
invalid. `max_attempts` defaults to 5 and accepts integers **1 through 5**,
excluding booleans. New authorizations require a future finite deadline no
more than seven days away.

The attempt allowance includes declared failures and unresolved reservations.
It is a per-authorization-round cap, not a job-lifetime allowance, and is
never reset by task restart. There is no automatic new round after a limit.
The absolute deadline controls admission of new work; it does not forcibly
cancel an already running model call.

`BatchStatus` contains the authorization, `state`, cumulative execution
`snapshot`, `attempts_reserved`, and `registration_confirmed`:

| State | Meaning |
| --- | --- |
| `queued` | Authorized work has not yet progressed. |
| `running` | The round has ongoing progression; status is not a liveness guarantee. |
| `completed` | The selected execution completed; candidates still require review. |
| `failed` | A declared failure was committed and this round closed; explicit resume may authorize another attempt. |
| `limited` | The round closed at its processing limit; explicit resume is required for further work. |
| `in_progress_or_interrupted` | An unresolved admission or execution claim exists; do not blindly retry inference or authorize a successor. |

`registration_confirmed` is a historical acknowledgment, not current SDK task
liveness. A blocked state cannot reliably distinguish active inference from
an interrupted process.

Round-level `known_input_tokens`, `known_output_tokens`, and
`unknown_usage_attempts` preserve usage uncertainty. The snapshot retains
cumulative candidates and execution history. This is not a token reservation
estimator, a total-token cap, or an exact billed-cost control.

Errors use the existing `ExecutionError` hierarchy. Invalid inputs,
conflicting/stale requests, missing rounds, and integrity failures remain
explicit. Safe storage/execution error codes avoid exposing raw diagnostics.
An unknown execution outcome never rolls back its claim to permit inference.

`RegistrationUnknown` has safe message `batch_registration_unknown` and an
`authorization` attribute containing the saved authorization. Inspect that
round, then explicitly retry the original start/resume arguments if needed.
Scheduling uncertainty must not be treated as a new authorization.

## Persistence and concurrency

The batch ledger contains only create-only records:

| Record | Purpose |
| --- | --- |
| Authorization | Frozen round identity, starting revision, limits, and predecessor |
| Root / successor slot | One initial round per job and one successor per closed round |
| Registration receipt | Acknowledged scheduling of the saved identity |
| Step decision | Immutable attempt admission or terminal decision |
| Result | Complete committed execution snapshot for an admitted attempt |

Admissions bind a stable execution request ID, expected revision, action,
and admission time. Terminal decisions preserve a historical snapshot.
Recovered handlers replay closed steps; an old round cannot acquire new
work after a successor resumes. Execution claims are never overwritten,
expired, or deleted by this module.

SQLite uses a separate `batch_records` table with digest-checked payloads.
Blob stores integrity-enveloped objects beneath
`<prefix>/g0-blob-v1/batch/<hashed-record-key>.json`. Its existing **8 MiB per
encoded object** cap also applies here. Results and terminal decisions contain
full snapshots, so cumulative history affects storage and read costs.
There is no separate total-job size cap, compaction, or maximum count of
explicitly authorized rounds. SQLite adds no application-defined record-size
cap. These remain small G0 ledgers, not a scale claim.

Configure **one batch ledger per named handler/host**. The fixed native
handler is `information-extraction-batch-v1`; generated run IDs hash the
request ID, not the database path or Blob prefix. Do not reuse request IDs
across independent ledgers sharing native task infrastructure. Prefixes are
not tenant or authorization boundaries.

## Native SDK behavior and remaining verification

The adapter passes only a JSON string run ID as task input, with stable task
and input identifiers. It sets a five-minute cooperative task timeout and
`retry=None`; crash recovery is still possible and must respect the
application's persisted limits.

SDK task records can disappear after completion, and starting the same ID
can then create a fresh handler. The application receipts make that handler
harmless; native task identity alone does not establish exactly-once work.
The adapter uses `get_active_run` only during scheduling conflict recovery,
never for public status: that SDK method may reenter a handler.

Offline tests include real SDK task lifecycle and terminal-record deletion,
SQLite/Blob authorization contracts, concurrent requests, registration
uncertainty, preserved limits/deadlines, stale-round delivery, and subprocess
known-commit recovery versus unresolved-claim blocking.

The developer smoke and a public-host compatibility test exercise the public
`AgentServerHost` startup/shutdown lifecycle with an explicitly local provider.
The test rejects network connections, DNS resolution, and server socket
binds. Success and controlled-failure paths check environment/runtime cleanup.
Additional focused SDK tests retain private task-manager injection to inspect
terminal-record deletion; production task registration uses public SDK
exports.

Neither local harness establishes managed preview availability, cloud lease recovery,
authenticated hosted entry points, live Blob batch records, and downstream
managed identity. Those remain unverified. The string task input makes no claim to
restore the original operator's delegated caller identity.
