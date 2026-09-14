# G0 Blob ledger (bounded, optional adapter)

`information_extraction.blob_store.BlobStore` implements the same `Store` seam
as SQLite. `Execution.create`, `read`, and one-attempt `advance`/explicit
`Action.RESUME` do not depend on a host or browser. This is a real create-only
Blob coordination ledger, **not an uploaded SQLite database**.

**Evidence:** offline synthetic tests, real `azure-storage-blob` SDK pipeline
tests using an in-memory HTTP transport, and an explicitly authorized
[live storage smoke](#observed-live-storage-evidence) with a synthetic model.
This is not a Foundry-hosted deployment, managed-identity lifecycle test,
production authorization design, or a complete G0 gate.

## Injection and limits

Install the existing optional extra, from `information-extraction`:

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[azure]'
```

It includes `azure-storage-blob>=12.30,<13`. Base imports and SQLite remain
standard-library-only. The adapter deliberately is not imported by the package
`__init__`.

```python
from azure.storage.blob import ContainerClient
from information_extraction import Execution
from information_extraction.blob_store import BlobStore

# Supply an explicitly chosen TokenCredential. Caller owns client/credential.
with ContainerClient(account_url, container_name, credential=credential) as client:
    execution = Execution(BlobStore(client, prefix=experiment_prefix), model)
```

No account/container creation, key lookup, shared-key fallback, role changes,
leases, expiration, overwrite, or deletion is implemented. The injected client
must target the **primary** account endpoint with normal SDK policies; custom
transports/policies that themselves retry writes or redirect reads are outside
the contract. Every upload overrides `retry_total=0`, even when the caller's
SDK client has its default retry policy. Pipeline reads also disable retries
and secondary failover; the SDK can perform its bounded internal download-body
retries. A HEAD supplies size and ETag before a range-bounded, `If-Match` download.

Each **entire encoded blob** is capped at 8 MiB, including the JSON envelope.
The frozen normalized plan and cumulative snapshots are stored in full.
Reads validate the entire committed history; cumulative storage/read costs
grow with revisions. This is intentionally only for a small G0 sample, with
no scaling or exactly-once provider-execution claim. An oversized plan is
rejected before writes; an oversized model result leaves its existing claim
unresolved and cannot authorize another inference attempt.

## Immutable layout and commit point

All names are beneath `<prefix>/g0-blob-v1/`. Prefixes are single safe path
components; a prefix defines the **ledger-wide request-ID namespace**, not an
authorization/tenant boundary. Job and request names use SHA-256 identifiers.
The full logical identity remains inside verified JSON:

| Object | Purpose |
| --- | --- |
| `requests/<request-hash>.json` | Immutable receipt binding job, plan fingerprint, action, expected revision and historical result revision; create receipts can also save an observed claim |
| `jobs/<job-hash>/manifest.json` | Immutable full frozen plan, job identity and plan fingerprint |
| `jobs/<job-hash>/claims/<20-digit-revision>.json` | Unique revision owner and binding to the previous checkpoint |
| `jobs/<job-hash>/snapshots/<20-digit-revision>.json` | Full immutable cumulative result |
| `jobs/<job-hash>/checkpoints/<20-digit-revision>.json` | **Commit marker written last**, referencing snapshot, previous checkpoint (manifest for revision zero), and revision claim |

Objects use canonical JSON envelopes bound to their name, kind and format,
with payload byte length and SHA-256. References additionally bind the exact
outer bytes, length and name. Downloaded lengths/digests are checked, as are
job/plan identity, contiguous revision order, claim/receipt identity, attempt
progression, preserved successful candidates and original source evidence.
Hashes detect corruption; they are not authentication against a principal
able to replace every blob and hash. Protect storage access independently.

There is **no cross-blob transaction and no mutable HEAD**:

1. Create checks conflicting existing job identity, reserves a global request,
   writes the manifest and initial snapshot, then commits checkpoint zero.
2. Advance reserves a global request before attempting the revision's
   conditional create-only claim. Only a definitively successful claim upload
   authorizes the caller to invoke its model. A duplicate claim, even with
   identical bytes, never grants ownership.
3. Publish validates ownership/progression, writes the snapshot, then creates
   the checkpoint. Exact duplicate snapshot/marker bytes are safe to accept;
   different results cannot overwrite them.
4. Request replay derives the saved result from its immutable reference and
   committed history. **No final receipt update can strand a committed result.**
   Replays return historical snapshots, not necessarily the latest state.
   A historical create may include the claim observed at that time; use
   `read` for current state.

## Crash and conflict behavior

| Window | Observable result / permitted continuation |
| --- | --- |
| Interrupted create before initialization completes | `NotFound` if no job objects exist, otherwise visible integrity failure until explicit compatible `create` finishes no-model initialization |
| Competing incompatible creates | One manifest wins; losing calls fail explicitly, and any losing request reservation remains immutable, never resolving to the other plan |
| Receipt reserved, no claim committed | Same request is blocked forever; another request can compete if no claim exists, because no inference was authorized |
| Claim timeout, whether created or not | Original call fails; same request cannot infer ownership from a matching reservation/claim |
| Durable claim, model unknown/cancelled, or snapshot without marker | `IN_PROGRESS`; no automatic inference replay, takeover, deletion, or timeout recovery |
| Handled model/validation failure and committed marker | `FAILED`; explicit resume at the new revision retries the same chunk, retaining successful earlier records |
| Marker committed but response lost | Repeated request returns the exact saved result without a model call |
| Corrupt/missing committed references, checkpoint zero missing, or an interior checkpoint gap | `IntegrityError`; no model call |

A missing newest marker plus a snapshot is indistinguishable from an
interrupted publication: it remains unresolved rather than being treated as
success or a safely retryable model failure. Administrative deletion/repair,
external reconciliation, and automatic restart of unresolved claims are not
provided. Reads never invoke a model.

## Developer storage smoke (authorization required)

Use a dedicated approved container and a **new prefix per experiment**. Supply
the endpoint and container privately, not in fixtures or checked-in logs.
`AzureCliCredential` is the explicit CLI default. The script also accepts an
injected credential/client for callers/tests. It has no real model adapter:
its fixed fictional model emits 120 revenue / 18 operating income and can
raise a controlled failure. It creates ledger blobs but never provisions
infrastructure or deletes blobs. Provision the
[storage slice](storage-deployment.md) separately if needed.

From `information-extraction`, set `BLOB_SMOKE_ACCOUNT_URL`,
`BLOB_SMOKE_CONTAINER`, and a unique `BLOB_SMOKE_PREFIX` in the environment
(or use `--account-url`, `--container`, `--prefix`):

```powershell
$env:BLOB_SMOKE_PREFIX = 'g0-' + [guid]::NewGuid().ToString('N')
.\.venv\Scripts\python.exe scripts\blob_smoke.py run
.\.venv\Scripts\python.exe scripts\blob_smoke.py inspect
.\.venv\Scripts\python.exe scripts\blob_smoke.py run
```

`run` creates, advances chunk one, commits an injected chunk-two failure,
explicitly resumes, checks original evidence, and replays all saved requests.
Expect revision **3**, **3 attempts**, **2 candidates**, completed status.
First run: **3 synthetic model calls** (including the failure). Repeated run:
**0 calls**, same snapshot hash. Each command is a separate process; no local
state file is created or needed.

For finer-grained process-restart evidence, use a different fresh prefix:

```powershell
.\.venv\Scripts\python.exe scripts\blob_smoke.py create
.\.venv\Scripts\python.exe scripts\blob_smoke.py advance --expected-revision 0
.\.venv\Scripts\python.exe scripts\blob_smoke.py inspect
.\.venv\Scripts\python.exe scripts\blob_smoke.py advance --expected-revision 1 --inject-failure
.\.venv\Scripts\python.exe scripts\blob_smoke.py resume --expected-revision 2
.\.venv\Scripts\python.exe scripts\blob_smoke.py inspect
.\.venv\Scripts\python.exe scripts\blob_smoke.py resume --expected-revision 2
```

Partial `inspect` and injected failure intentionally exit **1**, not success.
Expected bounded `create`/first-`advance` steps may exit 0 while READY; they
prove only that step. Completed verification exits 0. Domain/auth/network
errors exit 2 with a fixed safe message; raw SDK errors, URLs, request headers,
credential details and resource IDs are never printed. Output contains only
safe statuses, counts, hashes, and fictional candidate/evidence values.
If an unknown interruption occurs, do not rerun with a new request to force
progress; preserve the prefix for investigation. No cleanup is performed.

## Observed live storage evidence

On September 14, 2026, the fine-grained smoke commands ran against a dedicated,
approved Azure Storage account and private container. Each operation used a
fresh local Python process and `AzureCliCredential`; no SQLite ledger, hosted
worker, or real model was involved. Runtime versions were Python 3.13.15,
`azure-storage-blob` 12.30.1, and `azure-identity` 1.25.3.

| Operation | Observed durable result | Synthetic model calls in that process |
| --- | --- | --- |
| Create | Ready, revision 0; no attempts or candidates | 0 |
| Advance at revision 0 | Ready, revision 1; chunk one committed with revenue 120 | 1 |
| Inject failure at revision 1 | Failed, revision 2; two attempts, first candidate retained; expected exit 1 | 1 |
| Explicit resume at revision 2 | Completed, revision 3; three attempts, two completed chunks, operating income 18 added | 1 |
| Fresh-process inspect, then full `run` replay | Same completed snapshot; all saved requests replayed without new attempts | 0 |

Both records retained the original synthetic evidence, exact `USD_millions`
unit, and pending review status. The completed snapshot SHA-256 was
`3dbf98102cddf15ce2ef3f54f67e1b9ac063ef965b1cb3bc9501e6a2ea5ffa29`;
inspection and full replay returned the same hash. **Zero Foundry model calls**
were made in this storage experiment.

This proves the small fixture's create/read/advance/failure/resume/replay path
against actual Blob persistence across process restarts. Concurrency,
corruption, ambiguous claim writes, and unknown interruptions were tested
offline, not injected into this live account. No hosted lifecycle,
managed-identity access, real-model-plus-Blob integration, or scale claim is
made. The account and synthetic ledger prefix are intentionally retained for
ongoing G0 work; storage transactions/capacity remain billable. Environment
identifiers and raw logs are excluded from the contribution.

## Reproduce offline evidence

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
# Base interpreter, no optional Azure packages:
$env:PYTHONPATH = 'src'
$basePython = Join-Path (& .\.venv\Scripts\python.exe -c 'import sys; print(sys.base_prefix)') 'python.exe'
& $basePython -m unittest discover -s tests -q
```

Shared Execution contract methods run against SQLite and independent Blob
adapters sharing a thread-safe fake backend. Additional tests inject failures
before/after object writes, race requests/jobs, restore without local files,
corrupt payloads/references, enforce payload caps and reject forged
publication. An offline real-SDK transport verifies `If-None-Match: *`,
bounded `If-Match` reads, 409/412 claim conflicts, and no automatic retry or
ownership after an ambiguous claim timeout. These are not live Azure tests.
