# Bounded live model smoke: September 14, 2026

## Scope

An operator authorized use of an existing Foundry project and selected an
existing DeepSeek V4 Flash deployment. The project deployment listing reported
model `DeepSeek-V4-Flash-0731`, version `2026-07-31`; this is deployment metadata,
not an independent verification of model internals.

The operator signed in through Azure CLI using an isolated local configuration.
The model adapter used the project-scoped Responses interface and Entra
authentication. No new Azure resources, hosted agent, storage account, web
application, or upstream pull request was created.

Only the two-chunk fictional financial fixture was eligible for submission.
The ledger remained local SQLite. Private endpoints, tenant identifiers,
credentials, provider request identifiers, and raw operational logs are not
part of this document or its regression fixtures.

## Initial rounds

The original two-call allowance was followed by an explicitly approved
two-call allowance for the revised prompt. SDK model retries were disabled
throughout. Each request allowed at most 2,048 output tokens and used a
180-second client timeout.

| Attempt | Prompt | Chunk | Outcome | Observed input/output tokens |
| --- | --- | --- | --- | --- |
| 1 | `financial-extraction-v1` | First | Committed `malformed_output`; raw response not retained | 207 / 47 |
| 2, explicitly approved diagnostic resume | `financial-extraction-v1` | First | HTTP 200/completed envelope, but invalid `unit` enum; committed `malformed_output` | 207 / 36 |
| 3, new job | `financial-extraction-v2` | First | One valid candidate with reconstructed original-source evidence | 364 / 31 |
| 4 | `financial-extraction-v2` | Second | Committed `model_timeout`; first chunk preserved | Unknown |

There were four application-level model attempts. Known usage totals are
778 input tokens and 114 output tokens, excluding the unknown timed-out
attempt. These are not an invoice or a total-cost guarantee; a timeout does
not prove that the provider performed no work.

No further inference was attempted in those rounds after the timeout. A
separately authorized follow-up round is recorded below.

## Root cause of the captured format failure

The diagnostic response had a completed Responses envelope and valid JSON.
It returned `"unit": "USD millions"` while the requested schema required the
literal `"USD_millions"`. The local validator correctly rejected it.

This observation does not prove the cause of the first attempt, whose raw
response was not retained. It also does not establish whether the deployment
generally supports or enforces every strict JSON Schema feature.

The revised prompt includes the full output schema and exact enum spelling
in its instructions, while retaining the strict response-format request.
The local validator was not relaxed and no field normalization was added.
The revision changes the model binding; the old failed job was preserved,
and a new job was created rather than silently changing a resumable plan.

Regression tests exercise the actual SDK decoding/execution path with
synthetic HTTP responses. They verify that the observed spaced unit still
fails, the exact enum succeeds, usage survives rejection, and the schema in
the instructions matches the response-format schema.

## State after the initial rounds

The revised job stopped at revision 2 with one of two chunks committed successfully,
one pending-review candidate, and one committed timeout failure. The valid
candidate is revenue of 120 `USD_millions`, linked to its original fictional
source block. It is not a human-approved record.

## Explicit resume: follow-up round

The operator authorized a new validation round with a maximum of five model
calls, including diagnostics, failures, and retries. The round used one call.
The model, prompt, timeout, and schema checks were unchanged.

An explicit resume processed only the second chunk. It completed in
approximately 14.12 seconds including local startup/authentication, with
366 observed input tokens and 33 output tokens. The job advanced to revision
3 and `completed`, retaining the previous successful candidate and the failed
timeout attempt.

| Final candidate | Value | Unit | Original evidence |
| --- | --- | --- | --- |
| `revenue` | 120 | `USD_millions` | First chunk, first source block |
| `operating_income` | 18 | `USD_millions` | Second chunk, first source block |

A separate local process read the persisted job and replayed the saved resume
request using an adapter that would raise if model execution were attempted.
Replay returned the same completed snapshot. The first candidate exactly
matched its earlier committed version; the two candidate identifiers were
unique. Attempt history showed one first-chunk attempt and two second-chunk
attempts, including the original timeout.

The completed v2 job has 730 known input tokens and 64 known output tokens,
plus one attempt with unknown usage. Across both prompt versions and the
follow-up, five application-level attempts have 1,144 known input tokens and
147 known output tokens, excluding the timed-out attempt. The five-call
authorization limit applies per validation round, not over the job lifetime.

## Conclusions and remaining limits

The two-chunk synthetic model smoke is complete, with an explicit timeout
resume and preserved first-chunk progress. Both candidates remain pending
human review; completion is not approval or a quality score.

The original timeout's provider-side cause is still unverified. A later
success does not establish that the provider performed no work during the
timeout, and its usage must remain unknown.

This evidence concerns local execution and SQLite persistence with a real
Foundry model. It does not establish extraction accuracy, cross-domain reuse,
bounded background progression, Blob persistence, hosted-agent recovery,
browser authentication, or complete G0 acceptance.
