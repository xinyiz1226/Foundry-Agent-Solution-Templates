# AdventureWorksDW: sales nearly flat, profit lower

Recorded on 2026-09-15 using the deterministic offline baseline. No LLM, Azure
resource creation, SQL connection or model invocation was used for this report.

**Scope:** official Microsoft AdventureWorksDW Internet Sales, filtered to
`CurrencyKey = 100` (verified USD / US Dollar identity). Source monetary values
are preserved without FX conversion. This is fictitious sample data, not
certified financial/accounting evidence.

- Baseline: `[2013-11-01, 2013-12-01)`.
- Current: `[2013-12-01, 2014-01-01)`.
- Normalized CSV SHA-256:
  `45d1a25c2b301f730e635fc789fc3ee08c6bb7a9a946159105be7ad00997259f`.
- Source/version/license: [pinned manifest](../data/adventureworks-manifest.json).
- Completeness: reviewed interior-snapshot assumption, not a production
  watermark, late-arrival policy or data-owner certification.

## Observed metrics

| Metric | November | December | Change |
|---|---:|---:|---:|
| Sales | 1032823.6600 | 1033955.1800 | +1131.5200 |
| Distinct orders | 1164 | 1203 | +39 |
| Product cost | 599198.8073 | 600965.0916 | +1766.2843 |
| Gross profit | 433624.8527 | 432990.0884 | -634.7643 |
| Gross margin | 0.419844 | 0.418771 | -0.107338 percentage points |

Sales increased slightly while profit fell. Margin changes use unrounded
aggregate ratios, not subtraction of already-rounded displayed margins.
The underlying sales/cost/order/line totals agree with the separate source
extraction audit. These facts are backed by generated evidence `q1` and `q2`.

## Offsetting territory changes

| Territory | Sales change |
|---|---:|
| France | +35748.0100 |
| Northwest | -30090.9900 |
| Southwest | -9230.8500 |
| Germany | +7590.2400 |
| Southeast | -2400.9300 |
| Other five territories | -483.9600 |
| **Total** | **+1131.5200** |

These are arithmetic contributions, not established business causes.
Evidence `q3`-`q6` reconciles both period totals and the change.

## Fixed-rule product drilldown: France

France had the largest absolute territorial change, so the fixed baseline
selected it for one product drilldown. It did not independently decide which
business explanation was most likely.

| Product | Sales change |
|---|---:|
| Mountain-200 Black, 38 | +18359.9200 |
| Mountain-200 Silver, 42 | +13919.9400 |
| Mountain-200 Silver, 46 | -9279.9600 |
| Road-350-W Yellow, 44 | +8504.9500 |
| Road-550-W Yellow, 40 | +5602.4500 |
| Other 92 products | -1359.2900 |
| **France total** | **+35748.0100** |

Evidence `q7`-`q10` retains the remainder rather than treating Top-5 as the
whole result. A separate, test-only integer SQL oracle independently confirms
the dimension values and selected territory.

## What remains unexplained

No campaign, availability, pricing, demand or causal evidence was supplied.
The two months have different lengths and are not seasonally adjusted.
The fixed workflow did not explore Northwest's offsetting decline or every
material territory. Whether an adaptive agent adds useful coverage under
comparable budgets is the next evaluation question.

## Reproduce

Follow the [official-data baseline commands](../docs/baseline.md#run-the-official-adventureworksdw-sample).
The full local Markdown and JSON reports are written to
`.artifacts/adventureworks-baseline/`, with source hash, exact periods/filters,
results, parameterized SQL plans and timings. Every SQL plan is marked
**not executed** in this offline run.

The workflow used ten data requests and no model requests. On this workstation,
the recorded data-request operations totaled approximately 0.05 seconds;
this excludes download/loading and is not an Azure SQL or hosted-agent latency
claim. Initial group/time limits require remeasurement before production use.
