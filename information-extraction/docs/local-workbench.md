# Local synthetic information-extraction workbench

This is the first browser workbench slice, not a hosted or authenticated
application. It uses the actual execution engine, SQLite ledger, Invocations
server, and native local-file task provider. Streamlit is only an HTTP client:
it does not own extraction loops, task threads, or the durable request identity.

## Start

From `information-extraction`, with Python 3.13+:

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e '.[hosted,workbench]'
& .\.venv\Scripts\python.exe .\scripts\run_workbench.py
```

The launcher prints the UI URL, backend URL, and state directory after
read-only readiness checks. Defaults are:

| Item | Default |
| --- | --- |
| Streamlit | `http://127.0.0.1:8501` |
| Local Invocations backend | `http://127.0.0.1:8765` |
| Server-owned job (`--job-id`) | `synthetic-job` |
| Durable extraction/batch/HTTP receipts | `.local-data\workbench\ledger.sqlite3` |
| Native local-file task state | `.local-data\workbench\native-state` |
| Diagnostics | `.local-data\workbench\backend.log` and `streamlit.log` |

Azure/Foundry/telemetry settings inherited by the child processes are replaced
with explicit local settings. The backend uses `create_offline_app`, never
the production hosted factory. No Azure credentials, cloud resource, or real
model is needed. Dependency installation may download packages.

Both services bind only to `127.0.0.1`; the client accepts only explicit
`http://127.0.0.1:PORT` backend URLs and does not follow redirects or use an
environment proxy. Streamlit CORS and XSRF protections stay enabled.
**There is no operator authentication.** This is for a trusted local machine,
not an untrusted multi-user host. Do not expose either port through a tunnel,
reverse proxy, container port publication, or public interface.

If a port is occupied, the launcher reports it without stopping that service:

```powershell
& .\.venv\Scripts\python.exe .\scripts\run_workbench.py `
    --backend-port 8766 --ui-port 8502
```

Use only one backend per state directory. Changing ports does not create
another job. `--state-dir` selects a different local directory for an
independent synthetic demonstration; it is not recovery or reconciliation
of an unresolved job. Never delete an old ledger or claim to make retry safe.

## Prepare independent acceptance jobs

Preparation creates a new manifest, not a job authorization or an Azure
deployment. Every invocation allocates a create-only directory with two
different job IDs, local state directories, and proposed Blob prefixes.
Existing ledgers and the historical hosted job are not reset or reused.

```powershell
$prepared = & .\.venv\Scripts\python.exe .\scripts\prepare_workbench_acceptance.py | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Acceptance preparation failed." }
$manifest = Get-Content -Raw $prepared.manifest | ConvertFrom-Json
$case = $manifest.scenarios | Where-Object name -eq 'pause-resume'
& .\.venv\Scripts\python.exe .\scripts\run_workbench.py `
    --job-id $case.hosted_environment.EXTRACTION_JOB_ID `
    --state-dir $case.local_state_dir --backend-port 8766 --ui-port 8502
```

The explicit job ID is passed to the independent backend, not selected from
browser state. Leave an existing preview on its own ports and state directory.
On reopen, reuse the same manifest and state, not another prepared job.

The repeatable local rehearsal uses Streamlit's AppTest, real loopback HTTP,
the separate native-task process, and durable SQLite, rather than a mocked
page projection. It consumes its own fresh manifest and uses shorter
60-second rounds inside the prepared 120-second ceiling. The JSON result
reports the actual duration and separates UI clicks from exact transport
replays; repeated saved requests must preserve the complete durable ledger:

```powershell
& .\.venv\Scripts\python.exe .\scripts\workbench_acceptance.py
& .\.venv\Scripts\python.exe -m unittest tests.test_prepare_workbench_acceptance tests.test_workbench_acceptance tests.test_local_workbench -q
```

| Prepared manual scenario | Explicit commands | Expected observation |
| --- | --- | --- |
| Pause/resume | Start with allowance 1, then Resume with allowance 1; each round 120 seconds | First round `limited`, revision 1, revenue 120. Reads/reopen do not advance. Resume completes revision 2 with operating income 18 and the original revenue candidate unchanged. |
| Single start | Start with allowance 2, 120 seconds | Backend completes both chunks without another mutation, revision 2, two committed attempts. |
| Read/restart | Refresh/recreate the page; restart the completed backend | Same run, revision, candidates, evidence and no new authorization. Process instance changes after restart. |
| Isolation | Run the second scenario in its own state directory | Prior completed ledger and candidates remain unchanged. |

All values use `USD_millions`; evidence is `block-1` / `synthetic:line:1`
and `block-3` / `synthetic:line:3`. Both records remain Pending. A `limited`
round is an admission-limit pause, not a manual cancel or hard interruption.
The rehearsal stops its own processes and removes only its temporary state;
manifests prepared separately above are retained.

### Subsequent cloud execution

The manifest's `hosted_environment` contains only the two changed bindings;
it is **not** a complete hosted configuration or permission to open ingress.
Preserve all existing identity, task-backend and Blob account/container
settings. Apply job ID and prefix together on a new hosted version, keeping
the previous version/configuration for rollback. Do not retarget existing
sessions or erase old Blob state. Configure one scenario at a time with fresh
session affinity, and require `current` to return its exact job ID with no
round or pending intent before Start. A mismatch blocks the test.

For a future approved execution window: maximum 10 minutes public exposure,
at most two new owned sessions across the two scenarios, four committed
synthetic attempts total, and no real model calls. Set an absolute cleanup
deadline when the window opens; do not extend it. Each click freezes its
own 120-second admission deadline; retries retain that exact request and
deadline. Stop on an unknown claim or transport outcome rather than issuing
a new mutation. Capture the initial session set, close ingress and stop the
owned site/agent/new sessions at the deadline, restore the approved Always On
setting, and leave baseline sessions and historical ledgers untouched.
Cleanup must have one authoritative receipt writer so a stale poll cannot
overwrite a closed result.

Local rehearsal does not establish cloud managed-identity mutations, actual
browser/WebSocket disconnect timing, or token expiry/revocation. Those are
still live acceptance gates; another successful login-only check is not a
substitute.

## Use and reconnect

1. Review the built-in fictional ExampleCo source blocks. There is no upload
   or profile editor in this slice.
2. Set an attempt allowance from **1 through 5** and a round time limit from
   **10 through 300 seconds**. The defaults are one attempt and 120 seconds.
3. Click **Start extraction**. With the default allowance, the first chunk
   commits revenue `120 USD_millions` and the round reaches `limited`.
4. Refresh or reopen the page. Read-only current-job discovery restores the
   current round, progress, candidates, and evidence without copying a run ID.
5. Click **Resume with a new bounded round**. The remaining chunk commits
   operating income `18 USD_millions`; the first candidate is unchanged.

Status refreshes every two seconds while the page is connected. Reads,
widget changes, and browser reopening never create authorizations. Closing
the browser does not stop the independent backend. A new round requires an
explicit button click; it is never created automatically at a limit.

Attempts reserved and the allowance are **per round**. Committed attempts,
revision, completed chunks, and candidate records are **cumulative**. Known
token counts are synthetic accounting, not bills or a total-token cap.
An absolute deadline limits new admissions, not hard cancellation of an
already running operation.

All candidates remain **Pending**. Evidence is reconstructed from persisted
source blocks, not a model quotation. Structural validation does not establish
semantic correctness, accuracy, human approval, or approved business results.

## Saved requests and failure states

The backend saves the first start intent per configured job and the first
resume intent per predecessor before scheduling. Its read-only `current`
operation can discover an intent even if the browser disappeared before the
HTTP response or initial batch ownership record. Request identity does not
depend on `st.session_state`.

| State | Workbench behavior |
| --- | --- |
| No current round or pending intent | Offer explicit start. |
| Saved intent | Offer **Retry saved request**, preserving the exact action, request ID, revision, allowance, and original deadline. No automatic transport retry. |
| `limited` or `failed`, no pending intent | Offer explicit resume with a new bounded round. |
| `in_progress_or_interrupted` | Inspection only. No start, retry, or resume button. An unresolved claim cannot be safely classified as inactive. |
| `completed` | Show records/evidence without a new-work button. |
| Backend unavailable or invalid/corrupt response | Show an error, not an empty job or a fresh-start option. |

Competing tabs cannot allocate different budgets for the same transition.
After a timeout or lost acknowledgment, refresh first. A saved request that
expired before authorization fails closed with `saved_request_expired`;
retry never silently extends its deadline. No operator reconciliation or
intent reset is implemented here.

The workbench accepts a maximum 64 KiB response for this fixed small sample.
Oversized or inconsistent responses fail visibly rather than showing partial
progress. Current-job traversal is bounded to 1,024 rounds; exceeding that
bound is an error, not silent truncation.

## Stop and retain state

Ctrl+C stops only services owned by the launcher. The Streamlit process is
stopped separately; the backend receives a control-pipe shutdown request
and exits its normal SDK lifespan. If cleanup times out, the launcher reports
the forced stop and retains state for inspection. A forced stop is not
evidence that an in-flight operation was cancelled without an outcome.

Launching again with the same directory rediscovers its job. Launch does not
authorize a new round or erase an old one. Native task reentry remains subject
to the original durable admissions, claims, allowance, and deadline.

For development, the backend can run separately:

```powershell
& .\.venv\Scripts\python.exe .\scripts\run_workbench.py --backend-only
```

The normal launcher is preferred because it checks both listeners and owns
their cleanup. The optional internal parent-pipe mode also shuts services
down when their owning launcher closes its pipe.

## Reproduce local evidence

```powershell
& .\.venv\Scripts\python.exe -m pip install -e '.[hosted,workbench,test]'
& .\.venv\Scripts\python.exe -m unittest `
    tests.test_workbench_client tests.test_workbench_ui tests.test_local_workbench -q
```

Tests cover read-only initial render/reopen, explicit start/resume, exact
saved-intent retry, blocked/error UI states, actual local native execution,
different backend instances restoring a completed job, occupied ports,
inherited hosted settings, and owned-process cleanup. Temporary test state
is removed; the normal launcher's state is intentionally retained.

This is not hosted browser-disconnect proof, an unknown in-flight crash
recovery result, end-to-end operator authorization, or a real-model browser
flow. No cloud deployment occurred for this workbench slice. Historical
[hosted evidence](hosted-smoke-results.md) remains tied to its original source
archive; **G0 is still incomplete**.

The separate [cloud workbench code](cloud-workbench.md) adds signed-operator
checks and authenticated gateway transport without changing this local
mode into a cloud fallback. Its local fixtures do not establish live Azure
authorization. Use its distinct entry point only after the documented
configuration/deployment approvals and acceptance gates.
