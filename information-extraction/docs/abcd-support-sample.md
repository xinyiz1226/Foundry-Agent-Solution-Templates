# ABCD: second-domain input preparation

ABCD customer-support conversations replace the previously proposed
customer-adoption meeting sample. Financial reports remain the first domain.
The purpose is to demonstrate reusable, evidence-linked extraction, not to
implement ABCD's original dialogue-agent benchmark.

**Implemented:** a bounded, offline ABCD-format importer, an original synthetic
format fixture, a [shared configured-core rehearsal](configurable-extraction.md),
and a [configured local workbench](configured-workbench.md) with support-profile
editing, bounded JSON upload, explicit execution and field-level evidence.
A [real-model pilot](configured-workbench-pilot.md) extracted one support
candidate from the owned lamp fixture. **Not implemented:** durable review/export
or a second-domain corpus accuracy result. These local slices do not complete
G1 or any remaining G0 cloud acceptance gate.

## Data selection and provenance

The [ASAPP Research repository](https://github.com/asappresearch/abcd) describes
over 10,000 human-to-human support dialogues, 55 intents, and fictional customer
scenarios. These are role-play conversations, not production support tickets.
The [README](https://github.com/asappresearch/abcd/blob/master/README.md) defines:

- `abcd_v1.1.json`: a map of `train`, `dev`, and `test` conversation lists,
  distributed as `data/abcd_v1.1.json.gz`.
- `abcd_sample.json`: three training conversations in a top-level list.
- Each conversation has `convo_id`, `original`, `scenario`, and `delexed`.
  Original turns are `[speaker, text]` pairs; speakers include `customer`,
  `agent`, and `action`.

The repository has an [MIT license](https://github.com/asappresearch/abcd/blob/master/LICENSE)
and explicitly offers original utterances for other purposes. Dataset
redistribution and required notices still need contribution review before raw
conversations are bundled in this template; this is not a claim that ABCD has
no license. No upstream conversations are committed here.

[`samples/abcd-format-synthetic.json`](../samples/abcd-format-synthetic.json)
is an independently authored format fixture, not an excerpt of ABCD or an
extraction-quality benchmark. Real ABCD files are supplied locally by the
operator after reviewing the upstream terms. The importer does not download
files or fetch URLs.

The official three-dialogue sample at upstream revision
[`6b8700ce67c6b37b062dd7a60abc76d7ef832a97`](https://github.com/asappresearch/abcd/blob/6b8700ce67c6b37b062dd7a60abc76d7ef832a97/data/abcd_sample.json)
was normalized in memory during adoption: 63 customer/agent blocks and nine
excluded action turns, with original indices, speakers and text preserved.
Its 38,934 source bytes have SHA-256
`151e0c487493ab376bb5115538f3bfd6d2f460c94f9daa5cdf04e55bccdf4808`.
No raw or normalized upstream conversation file was retained. This establishes
sample-format compatibility, not extraction accuracy or full-corpus coverage.

## Run locally

From `information-extraction`, with Python 3.13+ and the base package installed
(`pip install -e .`), run:

```powershell
& .\.venv\Scripts\python.exe -m scripts.import_abcd `
  --input .\samples\abcd-format-synthetic.json `
  --split train `
  --output .\.local-data\abcd\synthetic-normalized-v1.json
```

This produces two normalized documents, seven dialogue blocks, and an explicit
count of one excluded action turn. It makes **no model calls, Azure changes,
execution-ledger writes, or review decisions**. No additional Azure cost is
introduced by this local operation.

For a locally supplied upstream subset, substitute its `.json` or `.json.gz`
path and select the intended split. A top-level sample list is training data;
using it with `--split dev` or `--split test` is rejected. Split maps retain
the explicit train/dev/test boundary; only the selected split is normalized.
Never relabel the three training examples as a held-out evaluation set.

Output is create-only: an existing path is an error, including the input path.
Use a new output name to repeat a run. Publication uses a same-directory
temporary file and an atomic hard link; a filesystem without hard-link support
returns an error rather than falling back to an overwrite. Runtime errors
return a nonzero exit code and a safe error code. Keep raw and normalized
corpus files in ignored `.local-data`, not in source control.

### Supported bounds and output

This is a small-subset importer, **not a full-corpus streaming loader**:

- At most 8 MiB of input file bytes and 8 MiB after gzip decompression.
- At most 100 conversations in the selected split, with unique nonnegative
  64-bit integer conversation IDs.
- At most 1,000 original turns per conversation and 32 KiB of UTF-8 text per
  turn. Customer/agent turns must be nonblank.
- Strict UTF-8 JSON, valid turn pairs, and known speaker values. Malformed
  selected conversations fail the import; nothing is silently skipped.
- Local regular input files; symbolic links, junctions and Windows UNC paths
  are rejected. No arbitrary URL or archive expansion support.

The JSON artifact uses `information-extraction.abcd-source.v1`. It contains the
source-file SHA-256, parser version, selected split, and normalized documents.
Each document preserves `convo_id` as `conversation_id`, and each dialogue turn
preserves its speaker, verbatim text, and zero-based `original` array index.
Its nested `block` reuses the existing `Block` contract, with IDs scoped to
the document. For example,
`original[4]` maps to block `turn-5`; skipping an action does not renumber later
turns.

Document identity hashes the parser version, split, conversation ID, and
ordered visible turns with their original indices and speakers. JSON
formatting, unrelated conversations, `scenario`, `delexed`, and excluded
action text do not change that document identity. The source-file hash still
identifies the exact supplied file, including compression and metadata.
Neither identity implies that two different conversations describe different
real-world customers.

## Evidence and support profile

Only customer/agent utterances from `original` are eligible textual evidence.
Do not copy `scenario`, delexicalized text, intent labels, action targets,
guidelines, or original `action` turns into extraction input. Action events
are deliberately excluded in this dialogue-only profile: they may describe
system state, but they do not prove that a customer or agent stated an outcome.
Their count is reported so this omission is visible.

The following flat profile is implemented as `SUPPORT_PROFILE` in
`information_extraction.profiles`. Both the scripted rehearsal and the separate
bounded real-model pilot use it; neither is human-labeled corpus evaluation:

| Field | Type | Evidence rule |
|---|---|---|
| `customer_issue_or_request` | Required text | An explicitly stated customer concern or request; consolidate restatements of the same concern. |
| `product_or_service` | Nullable text | Use only a product/service named in the dialogue. |
| `attempted_action` | Nullable text | An explicitly reported action taken, not merely a suggested step or required policy action. |
| `stated_outcome` | Nullable text | What a speaker actually reports; an accepted request is not proof of fulfillment. |
| `outcome_status` | Nullable enum: `resolved`, `unresolved`, `pending` | Populate only when explicitly supported; otherwise null, not assumed success. |

One conversation can yield zero or multiple records. Split unrelated concerns;
do not emit a new record for every turn. Evidence, speaker/source references,
configuration versions, execution identity, and review status remain
framework-owned, outside this business schema. The configured plan and model
prompt preserve speaker information. New records remain pending review,
and default downstream queries/exports must use approved records only.

## Next G1 acceptance

1. Extend the working text/ABCD planning and local workbench path toward the
   remaining supported inputs and deployment gates. The bounded real-model
   trial is complete, but only on owned synthetic sources.
2. Implement durable human review and approved output; current candidates
   remain Pending and cannot stand in for approved records.
3. Freeze a small development subset and a distinct official dev/test subset;
   retain file hashes and conversation IDs. Author field values, record
   counts, and original-turn evidence as gold labels. Existing ABCD intent,
   action, or scenario labels are not extraction gold.
4. Include missing facts, suggested-but-not-attempted actions, unresolved
   outcomes, multiple concerns, and no-record cases. Report missed records
   and field/evidence errors with denominators, not just JSON validity.

The deployed synthetic hosted factory and financial workbench are unchanged.
New local source archives include the shared validator and legacy compatibility
adapter needed by their imports (17 hosted files and 18 web files). They still
exclude the local ABCD importer and real-model adapter. No new archive has been
deployed as part of this work.
