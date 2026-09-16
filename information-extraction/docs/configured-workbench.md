# Local configurable extraction workbench

This is a separate **local-only, single-user** UI. The existing `workbench.py`,
cloud workbench and financial preview remain unchanged. It is not a multi-user
authentication service: do not expose either loopback port or share its token.

## Launch on Windows

From `information-extraction`, with the project's workbench dependencies available:

```powershell
python scripts\run_configured_workbench.py --state-dir .local-data\configured-workbench --backend-port 8766 --ui-port 8502
```

The equivalent module command is `python -m scripts.run_configured_workbench`
with the same arguments. Ports default to 8766 (backend) and 8502 (UI).
Use a dedicated local state directory: the launcher's owner marker rejects a
nonempty foreign directory, preserving existing G0/native workbench state.

The default is **prepare-only**: creating or inspecting jobs cannot call a model.
For an explicitly configured existing project/deployment, the launcher also accepts:

```powershell
python -m scripts.run_configured_workbench --state-dir .local-data\configured-workbench --backend-port 8766 --ui-port 8502 --real-model --project-endpoint <existing-project-endpoint> --deployment <existing-deployment> --azure-config-dir <local-azure-config-directory> --model-call-limit 5
```

Omit the optional `--reasoning-effort` flag unless its support and value have been
verified for the chosen deployment. The default leaves reasoning effort unset.

No new Azure resource or deployment is created by the UI. The launcher supplies
`INFORMATION_EXTRACTION_CONFIGURED_BACKEND_URL` (literal loopback URL) and
`INFORMATION_EXTRACTION_CONFIGURED_TOKEN` to the UI process. These are not form
inputs, URL parameters, or Streamlit session-state credentials. Starting the
entry page without the connection configuration shows a safe setup error.
Real-mode startup checks an `AzureCliCredential` token without model inference.
Azure/OpenAI credential environment variables are stripped from the UI process;
the bearer IPC token is supplied only through its environment and never logged.

Prepare-only plans bind to `prepare-only-v1`. After switching to real-model mode,
click **Create job (no model call)** again to create a new immutable job with the
real model binding. Existing prepare-only plans are never promoted or rewritten.
Each named budget grant allows 1–5 admitted calls and persists across jobs and
restarts. The launcher's `--budget-id` defaults to `initial`; the same named grant
cannot reset its consumption or change its settings/limit. Only an explicit
operator restart with a **new** CLI `--budget-id` creates a fresh grant, retaining
all previous jobs and call receipts in the same state directory. No UI or HTTP
operation renews grants, and unknown claims remain blocked. The policy maximum
is five calls per named grant; a particular grant can have a lower configured cap.
The controlled pilot retained its first failed admission and used a new four-call
grant, keeping its combined allowance at five. The model description includes
the active budget label; there is no budget-grant UI.

## Prepare, then explicitly authorize

1. Choose **Financial** or **Customer support**. Edit the profile JSON's schema
   and extraction instructions if needed. This is the bounded flat-profile format
   accepted by `schema.load_profile`, not unrestricted JSON Schema: text, number,
   integer, boolean, enum and calendar date fields; nullable fields are supported.
   The backend derives its output JSON Schema from that profile.
2. Upload a UTF-8 `.txt` or ABCD `.json` file, or paste source content. Upload takes
   precedence over paste. Plain text is limited to **32 KiB**, raw ABCD JSON to
   **128 KiB**, and selected original dialogue text to **16 KiB**, measured in UTF-8
   bytes. The launcher sets Streamlit's upload transport ceiling to **1 MiB**
   (`--server.maxUploadSize=1`); this does not increase the authoritative 32/128 KiB
   application limits. Empty/invalid UTF-8, invalid JSON and oversized input are rejected before
   job creation. PDF, OCR, gzip, remote URLs and arbitrary server file paths are
   not supported. Plain text accepts an optional UTF-8 BOM and preserves original
   line endings and line locations. The backend forms chunks of at most 8 KiB
   without splitting lines, rejecting any single oversized line. A selected ABCD
   conversation is one chunk.
3. For ABCD, choose the split and conversation. A top-level list is a training
   sample; a dataset split map contains train/dev/test. The preview renders only
   normalized original customer/agent turns, never scenario/delexed/action fields.
   The exact imported source bytes plus the selected conversation ID and split
   are submitted; the backend independently validates and freezes original evidence.
4. Click **Create job (no model call)**. Source and profile freeze in a new durable
   job. Changing profile selection explicitly resets the editor to that preset;
   ordinary refresh preserves manual edits. Editing never changes an existing job.
5. In real-model mode, explicitly click **Start extraction**, or **Resume with a
   new bounded round** after a failed/limited round. Each round allows 1–5 attempts
   and an admission window of 10–300 seconds (default 120). The UI also caps the
   allowance at the grant's currently reported remaining calls. Each named grant's
   lifetime limit is at most five admitted calls across jobs and restarts, not five
   calls per refresh, browser session, job, or round. Admission deadlines do not cancel provider calls;
   neither attempt nor token counters guarantee billed cost.

## Durable progress and evidence

The separate authenticated loopback backend owns execution and native background
tasks. Streamlit never runs a model, Azure SDK, extraction engine, or native task.
Closing/reloading the UI does not authorize work or stop an already authorized
round. Use **Saved jobs** to rediscover persisted jobs in a new browser session.
Automatic polling and **Refresh status (read only)** use reads only.

The current job shows committed revision, status, chunk progress, known token
usage, remaining call budget, round allowance and its saved deadline. Generic field
tables and field-to-block evidence come from the **frozen backend snapshot**, not
the current editor. Evidence displays original source text, location and dialogue
speaker, not model-supplied quotations. Missing nullable fields show `null` and no
evidence. Every candidate remains **Pending**; structural validation is not semantic
correctness, accuracy measurement, human approval, or an export workflow.

Queued/running, completed and unknown/interrupted states cannot authorize a new
round. Completed jobs are read-only. Unknown claims are inspection-only; do not
delete claims to bypass them. A pending request is never retried automatically:
**Retry saved request** sends exactly the saved body/ID/deadline, not a renewed
budget. On a mutation error or timeout, the UI removes its success notice; inspect
status before deciding whether to explicitly retry. A missing acknowledgement is
not proof that the backend did not persist or start work.
