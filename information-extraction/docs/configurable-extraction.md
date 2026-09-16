# Configurable extraction: two-domain offline rehearsal

This is a **fixture-only plumbing rehearsal**, not a real extractor or a model
accuracy evaluation. It exercises the same generic configured-schema execution
path for financial facts and support conversations. No Azure resources, provider
credentials, network access, or real model calls are needed.

## Run on Windows

From the repository root, using the existing environment:

```powershell
Set-Location information-extraction
.\.venv\Scripts\python.exe -m scripts.configurable_smoke --state-dir .local-data\configurable-smoke
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_configurable_smoke.py -v
```

The default state directory is `.local-data\configurable-smoke`. The first command
prints a safe JSON summary without conversation text. A fresh run has **5 scripted
fixture calls, 0 real model calls**, 2 financial records at revision 3, and 2 support
records across two documents at revision 1 each. Each candidate remains **Pending**
with `semantic_validation_performed=false`.

Running the identical command again replays the saved request sequence with
**0 additional fixture calls**. A dedicated `configurable-fixture-v1.sqlite3`
execution ledger and `configurable-fixture-v1` job/request namespace avoid the
older `synthetic-job` ledger. Existing state is never deleted or reset. Changed
profiles, sources, incompatible request identities, and unresolved claims fail
explicitly; choose a new directory for a deliberately different experiment.

## Profiles and source boundaries

`information_extraction.profiles` supplies frozen dataclass configurations:

| Profile / schema version | Fields |
| --- | --- |
| `financial-example-v1` / `financial-flat-v1` | `metric`: enum `revenue`, `operating_income`; `value`: number; `unit`: enum `USD_millions` |
| `abcd-support-v1` / `support-flat-v1` | `customer_issue_or_request`: required text; `product_or_service`, `attempted_action`, `stated_outcome`: nullable text; `outcome_status`: nullable enum `resolved`, `unresolved`, `pending` |

The financial source is the original `sample.synthetic_plan()` fixture: fictional
ExampleCo revenue of USD 120 million and operating income of USD 18 million, in
two chunks. The instructions prohibit conversion, calculation, and invention.

The support source is **only the repository-owned original synthetic**
`samples\abcd-format-synthetic.json`, not the upstream ABCD corpus. `import_abcd`
excludes action turns and never promotes scenario, delexed, policy, or hidden-label
content to evidence. Customer/agent speakers survive as `DialogueBlock.speaker`.
Each full conversation becomes one chunk in a separate configured plan.

Support records consolidate repeated references to a distinct concern. The lamp
fixture distinguishes a suggested socket test from the customer's actual attempt,
and an unapproved replacement request from a completed replacement. The chair
fixture is an information request, not a product defect. Its guide-finding is
represented as the stated outcome; no separate troubleshooting attempt is stated,
so that field is null with empty evidence. These are predetermined illustrative
annotations for plumbing tests, not adjudicated gold labels.

## Model response envelope and stored evidence

Configured responses use this envelope (example financial response):

```json
{
  "records": [{
    "fields": {
      "metric": "revenue",
      "value": 120,
      "unit": "USD_millions"
    },
    "evidence": {
      "metric": ["block-1"],
      "value": ["block-1"],
      "unit": ["block-1"]
    }
  }]
}
```

Every schema field must occur in both objects, with no unsupported extra fields.
Field values are scalars or permitted nulls. Every nonnull field needs at least
one unique current-chunk block ID. A nullable null needs `[]`; all-null records
are invalid. `{"records":[]}` is valid. Models do not supply quotations. The
framework resolves source text and locations, while `FlatRecord.to_dict()` exposes
business values and `field_evidence` retains each field's block references.

Instructions and schemas are frozen into each `ConfiguredPlan`, rather than
looked up dynamically during replay. These examples use the same schema path;
there are no domain-specific branches in `Execution`.
Configured plans identify their format as `configured-plan-v1`. The optional
`information_extraction.schema.load_profile(payload: bytes)` loader accepts
dataclass-shaped JSON with `version`, `schema`, and `instructions`; schema keys
are `version`, `fields`, and `max_records`, and field keys are `name`, `kind`,
`description`, `nullable`, `choices`, and `date_format`. This rehearsal uses the
frozen Python profiles directly. The loader accepts strict UTF-8 JSON of at most
256 KiB and rejects duplicate or unsupported keys.

### Configured-path bounds

- A schema has at most 32 fields. Its `max_records` is configurable from 1 through
  100 per chunk; this is a ceiling, not a minimum result count. Empty results
  remain valid.
- Text values have at most 4,096 Unicode codepoints. Numbers must be finite;
  Python `int` values must fit signed 64-bit range. Integer fields require Python
  integers, not floating-point values.
- Date fields explicitly declare `date_format="YYYY-MM-DD"`; values must match
  that format and represent valid calendar dates.
- A configured plan has at most 16 chunks and occupies at most 256 KiB of
  canonical JSON.
- The aggregate of newly resolved candidates from one attempt occupies at most
  128 KiB of canonical JSON (`MAX_CANDIDATES_BYTES`). This includes resolved
  source evidence, not just business fields. Oversized output becomes a handled
  `malformed_output` failure, rather than partially publishing candidates.

### Foundry adapter and packaging boundary

Outside this offline CLI, `FoundrySettings` accepts an optional `profile` together
with a matching explicit `profile_version`. The existing real Responses adapter
derives its output schema and prompt from the frozen profile. The legacy default
model binding is preserved exactly. **No live generic model call was made** to
validate these changes; this rehearsal always injects the scripted fixture model.

Shared-core source allowlists now contain 17/18 files rather than 14/15, adding
`legacy_financial.py`, `outputs.py`, and `schema.py`. These are local packaging
changes only; deployed cloud source remains untouched.

## What the rehearsal verifies

The injected `ScriptedFixtureModel` declares binding
`offline-configurable-fixture-v1`. Canonical source digests and exact expected
plan/chunk/job/request/revision comparisons reject arbitrary input. It returns
fixed records; it does not extract via heuristics or contact a provider.

The financial sequence persists the first successful chunk, persists a handled
timeout on the second chunk, requires explicit `Action.RESUME`, and completes
without losing the first record. Both support documents then complete. Checks
cover values, nullable facts, field-level references, exact framework-resolved
source text/locations, and pending-review state.

The script replays every historical request, including the failed revision,
checks equality with its original snapshot, reopens the SQLite store, and repeats
the history with a model that raises on any attempted call. An interrupted run
between completed requests can continue its same frozen sequence; an unresolved
in-flight claim is not silently reset or re-inferred.

## Current limits

This is not a UI, real extraction, semantic validation, review/export workflow,
SEC parser, cloud recovery proof, or full G1 implementation. The fixed examples
do not measure generalization or accuracy. Runtime schema checks establish
structure and traceable references, not whether a cited sentence actually entails
a claimed fact. Human review remains required. This CLI never autoexecutes a cloud
adapter and does not use normalized import artifacts as an execution ledger.

Changes to these sources or the generic extraction package are **local source
changes, not deployed cloud changes**. Running this rehearsal does not publish,
deploy, or update any hosted agent, Azure resource, or existing cloud application.
