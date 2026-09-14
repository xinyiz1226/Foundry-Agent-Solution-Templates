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

## Observed attempts

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

No further inference was attempted after the final timeout.

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

## Final state and limitations

The revised job is at revision 2 with one of two chunks committed successfully,
one pending-review candidate, and one committed timeout failure. The valid
candidate is revenue of 120 `USD_millions`, linked to its original fictional
source block. It is not a human-approved record.

The timeout's provider-side cause is unverified. The client observed no usage
for that attempt. A future explicitly approved resume could incur additional
work or cost; it must not be treated as an automatic retry.

This run demonstrates a successful small model request and durable failure
accounting in the local execution module. It does not establish full-batch
success, extraction accuracy, cross-domain reuse, bounded background
progression, Blob persistence, hosted-agent recovery, browser authentication,
or complete G0 acceptance.
