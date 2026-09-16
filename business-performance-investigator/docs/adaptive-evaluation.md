# Bounded adaptive investigation and honest local comparison

## What was implemented—and what was not

This documents the local implementation of steps 1–2: a single-agent,
tool-selecting Chat Completions loop and a comparison harness against the
existing fixed baseline. Its original implementation performed no Azure
requests or real model inference. The subsequent separately authorized
[cloud experiment](cloud-analysis-validation.md#recorded-live-experiment-2026-09-16)
verified the baseline but did not complete adaptive acceptance. No dependencies
were added for the local engine. Hosted runtime and credential transport remain
the integrating caller's responsibility.

Replay fixtures are **scripted choices at the external model boundary**, not
DeepSeek reasoning, intelligence, quality, latency, or price measurements.
The real `Investigator` still executes every analytical operation on local data.

## Public interfaces

```python
from analysis.adaptive import AdaptiveLimits, run_adaptive

report = run_adaptive(
    investigator, baseline, current, question,
    client, model,
    limits=AdaptiveLimits(),
)
```

* `investigator`: a **fresh** `analysis.core.Investigator`. The caller supplies
  the trusted source, complete coverage attestation, `Limits`, and approved view.
  Periods are validated before model access. No model-selected periods, views,
  identity, data limits, or SQL are accepted.
* `client`: a synchronous Chat Completions **resource** exposing
  `create(**kwargs)`, such as an already-authenticated SDK client's
  `chat.completions`. It is not the SDK root client or a Responses client.
  `ReplayClient(steps)` provides the offline implementation.
* `model`: a caller-selected deployment/model identifier. Nothing is discovered
  from credentials or environment variables by these modules.
* A JSON-serializable dictionary is returned. Invalid caller configuration
  raises `ValueError`; execution failures return explicit error/exhaustion
  reports without raw exception messages.

Configure the SDK with **`max_retries=0`**. Observable nonzero SDK retry
configuration is rejected. Custom transports must likewise guarantee no hidden
retries and honor the supplied timeout; the loop does not retry.

```python
from analysis.evaluate import PriceConfig, run_evaluation, validate_report

evaluation = run_evaluation(
    fresh_csv_investigator, baseline, current, question,
    replay_or_approved_client, model,
    limits=AdaptiveLimits(), top_k=5,
    target_territory_ids=["1"],
    prices=None,
)
```

The evaluation API accepts only an exact local `CsvSalesSource`, never a SQL
source. It captures one private deep copy and provides a read-only source facade
to two fresh investigators. The source hash, dataset, periods, attested
coverage, approved view, and data limits are therefore matched. Neither run
changes the caller's investigator or reopens a potentially changed CSV file.
Both paths have the same `top_k` ceiling: evaluation narrows the adaptive cap to
its `top_k` argument. The fixed baseline always uses that value.

The default data budget is the existing **10 requests**: comparison costs two,
each breakdown costs four. The fixed baseline remains question-agnostic; the
harness records the same question for both paths but does **not** pretend
`run_baseline` interprets it. Target territory IDs are evaluator-supplied labels,
not an automatic understanding of the question. Coverage means observed
product drilldown of those IDs, not an answer-quality score.

`validate_report` checks references and reconstructs facts from their captured
aggregate evidence by invoking the existing analytical engine. It does not
implement another margin/contribution algorithm or claim an independent
mathematical oracle. The existing **12 hand-worked cases** in
`tests\test_business_analysis.py` remain that reference suite. The existing
optional AdventureWorks SQLite oracle is also reused.

## Tools and authoritative facts

By default, exactly one function call is accepted per model turn.
`AdaptiveLimits(max_tool_calls_per_response=2)` explicitly permits up to two
independent analytical calls, executed **serially**, never in parallel. The
hosted service selects this bounded compatibility mode after a real DeepSeek
response returned two calls despite `parallel_tool_calls=False`.
All calls, IDs, arguments and the whole turn's data-request cost are validated
before any data request. Filters cannot depend on IDs first discovered in the
same turn. `finish` must be alone. No call is silently discarded and the total
data budget is unchanged. The default local replay/evaluation mode remains one.

Available tools:

| Tool | Model-supplied arguments | Data requests |
|---|---|---:|
| `compare` | `filters` | 2 |
| `breakdown` | `dimension`, `filters`, `top_k` | 4 |
| `finish` | `result_ids`, `evidence_ids`, `stop_reason` | 0 |

Dimensions and filter keys are restricted to `territory` and `product`.
Filters must be bounded string IDs previously **displayed in a breakdown in
this run**; unseen IDs, including groups only present in undisplayed raw
evidence, are rejected. This is intentionally conservative: discover a scope
before drilling into it. If the desired territory is outside the caller's
top-k ceiling, the model must finish with insufficient evidence rather than
invent or retrieve an undiscovered ID.

Tool responses contain bounded deterministic summaries: top-k segments,
reconciled `other` totals, and result/evidence IDs. Full group evidence and SQL
query plans are retained in the returned report, **not sent to the model**.
Oversized summaries stop the run rather than silently dropping facts. The
report itself may be larger than model context because it retains bounded
source evidence for auditing.

`finish.stop_reason` is only `complete` or `insufficient_evidence`.
The selected result IDs must exist and be unique, and selected evidence IDs
must equal their exact union. A `complete` selection needs a comparison.
The runner copies those deterministic tool results into `facts`; there is
**no free-text model answer, numeric fact generation, or causal narration**.
All result/evidence IDs are local to a report; identify them with the report's
source snapshot and run, not as globally unique IDs.

The runner checks repeated scope totals and parent-to-child sales
reconciliation across tools. Such checks catch observable snapshot
inconsistency but do not prove that a caller-supplied remote source is a
transactionally consistent snapshot. SQL snapshot isolation remains a host
and source contract.

Assistant `content`, `tool_calls`, and DeepSeek `reasoning_content` are
preserved in the bounded, in-memory continuation. Reasoning and model prose
are never published in reports, logged, or saved by these modules. Treat
source labels and model input as untrusted data even though no free SQL is
available.

## Limits and stopping behavior

`AdaptiveLimits` defaults:

| Limit | Default |
|---|---:|
| Model calls, including finish | 6 |
| Completion tokens per call | 1,024 |
| Total conservative token reservation | 100,000 |
| Serialized context characters, including tools | 24,000 |
| Tool argument characters | 2,048 |
| Tool summary characters | 16,000 |
| Assistant response/continuation characters | 24,000 |
| Question characters | 4,000 |
| Maximum top-k | 20 |
| Overall wall-time budget, seconds | 60 |
| Per-model-call timeout, seconds | 30 |

Constructor validation also imposes finite upper bounds on caller
configuration. Data request, group, and elapsed-time limits come from the
existing `Investigator`; no partial breakdown is started when its complete
request cost would exceed the remaining request budget.

Before each request, the runner reserves serialized ASCII context bytes,
1,024 framing tokens, and the full output cap. This is a conservative
**byte-level-BPE budgeting assumption**, not measured token usage or a
provider billing guarantee. Reservations are not refunded when reported
usage is smaller. SDK-reported overruns stop the run. Omitted usage stays
`null`/`unknown`, including after a failed request; it is never recorded as
zero or estimated from character counts. Per-call observed usage and
reservation totals are separately exposed.

**Timeouts are cooperative.** The model transport receives the smaller of the
remaining timeout and `max_model_seconds`; elapsed time is checked before/after calls, and late results are
not accepted as successful facts. The source's own time budget is also
respected. Python cannot interrupt an arbitrary synchronous injected client
or source that ignores its timeout. The host must supply bounded transport
and database timeouts (or process isolation for a hard kill deadline).
Provider-internal hidden tokens, hidden retries, and ignored deadlines cannot
be guaranteed by this local library.

Expected terminal outcomes:

* `ok / complete`: a valid finish selection, **not proof of question
  sufficiency or causal correctness**.
* `insufficient_data / insufficient_evidence` or `no_data`.
* `exhausted`: `model_call_limit`, `data_request_limit`, `token_limit`,
  `context_limit`, `tool_summary_limit`, or `time_limit`.
* `error`: `invalid_model_response`, `model_error`, `data_error`,
  or `inconsistent_evidence`.

Duplicate JSON keys, NaN/infinities (including overflowed numbers),
malformed/unknown/multiple calls, duplicate or stale call IDs, stale result
or evidence IDs, invalid finish reasons, refusals, incomplete completions,
and unsupported legacy calls are rejected. On failure/exhaustion, `facts`
is empty; completed tool `results` and captured `evidence` remain available
for diagnosis. The evaluator also preserves baseline failure explicitly
rather than comparing against a success-shaped placeholder.

## Run entirely offline

From `business-performance-investigator` on Windows:

```powershell
py -3 -m analysis.adaptive_cli `
  --csv evaluation\worked_sales.csv `
  --config evaluation\worked-example.json `
  --output .artifacts\adaptive-replay-synthetic
```

The default replay is synthetic **North, ID `10`**. It uses the same one-segment
ceiling as the worked-example baseline. No credentials or network are needed.
The persisted [synthetic report](../evaluation/replay-reports/synthetic.json)
contains the complete tool results and evidence from a local run. Its measured
elapsed times are incidental CPU/wall times, not stable expected values or
model speed measurements.

With an **already prepared**, hash-verified official snapshot (the command
does not download anything):

```powershell
py -3 -m analysis.adaptive_cli `
  --csv .artifacts\adventureworks\internet_sales.csv `
  --config .artifacts\adventureworks\analysis-config.json `
  --replay evaluation\replays\northwest.json `
  --output .artifacts\adaptive-replay-northwest
```

Official **Northwest is ID `1`**, not synthetic North `10`. The fixture
requires the matching official dataset identifier, and loading the CSV
verifies its configured SHA-256. The checked-in
[Northwest summary](../evaluation/replay-reports/northwest-summary.json)
records a real local replay on that pinned snapshot:

| Observable harness result | Fixed baseline | Scripted adaptive replay |
|---|---|---|
| Product drilldown scope | France (`7`) | Northwest (`1`) |
| Data requests | 10 | 10 |
| Model-boundary calls | 0 | 4 replay calls |
| Actual inference requests | 0 | 0 |
| Numeric/evidence validation | Valid | Valid |
| Northwest product scope covered | No | Yes |
| Model tokens | No model: 0 | Unknown/not measured |
| Model price/cost | No model | Unknown |

This proves that **the harness can execute a supplied Northwest-focused
trajectory**, not that DeepSeek would choose it, outperform the baseline,
or provide a better business answer. The summary intentionally contains
metrics only; regenerate the full evidence report with the command above.
The fixture IDs derive from their respective source data, not interchangeable
territory names.

Output is `evaluation.json`. CLI exit codes are `0` when both analytical
reports are `ok`, `1` for incomplete/failed execution, and `2` for missing
inference authorization/configuration. Existing files are overwritten only
at the caller-selected output path.

## Explicit inference gate and host handoff

The CLI's default is always replay. Supplying an injected client, model,
identity, or price configuration without `--approve-model-inference` is
rejected. Conversely, that switch alone does **not** create a client, obtain
credentials, infer identity, deploy resources, or run a model.

An approved host can invoke the existing CLI function:

```python
from analysis.adaptive_cli import main

exit_code = main(
    approved_argv,  # Must include --approve-model-inference and --question.
    client=already_authenticated_sdk.chat.completions,  # max_retries=0
    model=approved_deployment,
    caller_identity=authenticated_subject,
)
```

Identity is a caller attestation at this library boundary, not an authentication
mechanism. It is not passed to the model or written into the report. The host
must verify authorization and scope before invoking the lower-level API.
`--approve-model-inference` authorizes only that explicitly requested inference
invocation; **it never authorizes Azure provisioning or a new paid cloud
experiment**. User unavailability is not approval.

Optional `PriceConfig(model, input_per_million, output_per_million, currency)`
uses explicitly supplied finite decimal-string rates for that exact model.
An estimate is produced only with complete SDK token usage and a non-replay
client. No prices are fetched or assumed. Platform cost stays unknown.
Flat-rate estimates exclude caching, discounts, taxes, and infrastructure.

## Validation and remaining gaps

Run the new loop/CLI/evaluation contracts and reuse the existing mathematical,
workflow, and optional official-data oracle tests:

```powershell
Set-Location tests
py -3 -m unittest test_adaptive test_adaptive_cli test_adaptive_evaluate `
  test_business_analysis test_analysis_workflow test_adventureworks_baseline -q
```

The focused command passed **45 tests** locally, including the available
official-snapshot replay and existing independent SQLite oracle.

Tests use real investigators and public synthetic/official fixtures. Doubles
are only at the external model boundary (plus time/network guards); the
existing arithmetic is not mocked. Development used red-then-green slices
for the basic loop, malformed protocol, budgets/usage, evaluation, CLI gating,
cross-tool consistency, and retry rejection.

Not validated here: real DeepSeek tool-choice behavior or endpoint compatibility,
provider tokenization/billing, real-model quality, streaming, asynchronous
transports, Azure identity/credential transport, hosted packaging, networking,
database snapshot deployment, hard process cancellation, or cloud costs.
Those require separately approved integration work. Nothing in these replay
results constitutes approval for that work.
