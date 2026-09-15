# Deterministic business-analysis baseline

This milestone is separate from the deployed connectivity probe. The default
workflow runs locally, calls no model, and creates no Azure resources. Its
purpose is to establish a correct reference before adding adaptive analysis.
The hosted `sql-probe` remains unchanged; it does not yet expose these tools.
The preparation script and offline analysis use Python 3.13's standard library.
For a new checkout, create `.venv` with `py -3.13 -m venv .venv`; Azure SDKs
and Bicep are needed for the full probe validation suite, not this local report.

## Run the official AdventureWorksDW sample

```powershell
.\.venv\Scripts\python.exe .\scripts\prepare_sample_data.py
.\.venv\Scripts\python.exe -m analysis `
  --csv .\.artifacts\adventureworks\internet_sales.csv `
  --config .\.artifacts\adventureworks\analysis-config.json `
  --output .\.artifacts\adventureworks-baseline
```

Use `prepare_sample_data.py --offline` to reprocess an already verified local
archive without a download. The pinned official Microsoft archive, projected
CSV, audit and generated configuration remain ignored under `.artifacts`.
The [source manifest](../data/adventureworks-manifest.json) records version,
hashes and license; changed source bytes fail validation rather than silently
updating the demonstration.

The official source has 60,398 Internet Sales lines across six currency keys.
The default **single-CurrencyKey 100 subset** has 33,400 lines and 14,860 orders.
The pinned `DimCurrency` identifies key 100 as USD / US Dollar. No FX conversion
is performed, and a verified currency key is not an accounting certification.
The SQL view must use the same `[fis].[CurrencyKey] = 100` scope.
The proposed [analysis view](../sql/analysis-view.sql) matches that projection.
It is not applied by preparation or probe deployment; schema creation, loading
the DW and view grants require a separate approved SQL deployment.

The chosen comparison is November versus December 2013. Completeness is an
explicit reviewed interior-snapshot assumption, supported by validated source
joins, counts and daily activity, not a production ingestion guarantee.
December 2010 and January 2014 are partial boundary periods and are not used.

See the [recorded sample investigation](../examples/adventureworks-baseline.md).
The complete generated report includes all query plans, parameter values and
aggregate evidence. The global monthly numbers agree with the independently
computed extraction audit. A separate test-only SQLite oracle uses exact
integer monetary units to verify global and dimension results independently;
SQLite is not a supported application backend and does not validate T-SQL.

## Run the independently worked example

From `business-performance-investigator`, using the existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -m analysis `
  --csv .\evaluation\worked_sales.csv `
  --config .\evaluation\worked-example.json `
  --output .\.artifacts\worked-baseline
```

This ledger is deliberately synthetic, not a substitute for AdventureWorks.
The command writes `report.md` and `report.json`. It verifies the exact CSV
SHA-256 before analysis and returns a nonzero exit code on invalid inputs or
budget/reconciliation failures. Raw data is not included in the report.

January sales are 400.0000, with three distinct orders and gross profit
130.0000. February sales are also 400.0000, but profit is 124.0000. North falls
by 30.0000 and South rises by 30.0000. The fixed workflow selects North by
largest absolute change, breaking ties by surrogate ID; Alpha contributes
-20.0000, with the remaining -10.0000 retained as Other.

## Analysis contract

- Sales = sum of `sales_amount`; cost = sum of `total_product_cost`.
- Orders = distinct `sales_order_number`, not sales-detail rows.
- Gross profit = sales minus cost; margin = aggregate profit divided by sales.
- Dates are order dates. Periods are disjoint, baseline first, with exclusive ends.
- Coverage is an explicit declaration with an attestation. A maximum transaction
  date alone never establishes a complete period.
- Money remains exact Decimal, reported to four places with half-even rounding;
  ratios use six places. Margin changes are percentage points.
- Zero/nonpositive sales baselines have no relative-growth result. Zero sales
  have no margin. An empty period is `no_data`, not a fabricated zero margin.
- Territory/product IDs, not display names, identify groups.
- Breakdowns reconcile each period and its change against separate overall
  aggregates. Top-K always retains an additive Other total.
- Contribution shares are omitted when the absolute net change is at most
  0.01 source monetary units. Absolute offsets remain visible.
- Distinct-order counts and margins are not summed across product groups.

The fixed workflow calls `compare`, territory `breakdown`, then product
`breakdown` within the territory with the largest absolute sales change.
No nonzero territory change means no speculative product drilldown. A report
with an empty comparison period is explicitly `insufficient_data`.

## Evidence and limits

Every fact links to data-request IDs containing the source hash (for CSV),
period, exact filters, result, timing and parameterized Azure SQL plan.
Offline reports explicitly mark those plans **not executed**. Replaying CSV
aggregations does not prove SQL Server execution, query plans, joins, or latency.

There are ten data requests for the full fixed workflow, or six without a
product drilldown. Offline mode executes zero SQL statements and zero model
requests. Each breakdown uses separate period aggregates and reconciliation
totals; this is a correctness baseline, not a claim of optimized query count.

Pilot defaults are 10 requests, 1,000 groups per request, Top-K 5 (allowed
1-20), and 30 seconds of cooperative execution time. These are explicit initial
limits, not production performance guarantees. CSV input is bounded to 64 MiB
and 200,000 records. A group overflow fails rather than silently dropping
unreported contributions. The clock is checked around each request; blocking
SQL must also have a driver-enforced timeout.

## SQL boundary

`analysis.queries.plan_query` emits only approved SELECT aggregates on a
configured view, with `%s` value parameters for `python-tds`. Only territory
and product dimensions/filters are accepted. View identifiers must be simple
approved schema/name identifiers; never accept them from model output.

The normalized view must expose:

```text
order_date, sales_order_number, product_id, product_name,
territory_id, territory_name, sales_amount, total_product_cost
```

Join keys must be unique, labels stable per surrogate ID, and monetary scope
must be consistent. Sales and cost should be `decimal(19,4)`; SQL aggregates
must preserve exact decimal values.

`analysis.sql_source.SqlSalesSource` accepts a **caller-owned cursor** in an
approved read-only snapshot transaction with a driver query timeout. It
validates columns, types, cardinality and group limits; it does not open
connections, acquire credentials, enable snapshot isolation or change grants.
Its snapshot attestation records the caller's obligation, not a technical
verification of transaction/network configuration.

The offline CLI intentionally has no SQL connection or Azure deployment switch.
The adapter is covered at its DB-API boundary, but actual analytical SQL,
private execution, snapshot configuration and performance still require a
separately approved cloud run. Reuse the verified private/TLS/identity approach;
do not grant broader rights or route SQL publicly for convenience.

## Twelve independent analytical reference cases

`tests/test_business_analysis.py` uses a hand-worked eight-line ledger and
explicit reference values, not expectations generated by the analysis engine.

| Case | Reference / required result |
|---|---|
| Overall metrics | Sales 400 -> 400; profit 130 -> 124 |
| Offsetting territories | North -30, South +30; shares undefined at zero net |
| Scoped product Top-K | North: Alpha -20, Other -10; total -30 |
| Distinct orders | Four lines but three orders in each period |
| Weighted margin | 0.325000 -> 0.310000; change -1.500000 points |
| Empty complete period | `no_data`, zero sales, undefined margin |
| Zero baseline | +400 absolute, undefined relative growth |
| Incomplete period | Reject a request extending beyond attested coverage |
| Exclusive end | A February 1 sale belongs only to February |
| Sales/profit divergence | Modified ledger: sales +40, profit -110 |
| Near-zero change | Preserve +0.0050; suppress unstable contribution shares |
| Duplicate labels | Different territory IDs remain distinct despite equal names |

Additional workflow/adapter cases cover source hash changes, malformed
numbers/labels, input/query budgets, SQL parameterization, large exact
decimals, report generation and inconsistent period totals. SQL cursor doubles
test transport contracts, not actual SQL arithmetic.
`tests/test_adventureworks_baseline.py` runs the independent official-data
oracle when the prepared data/configuration are present; it explicitly skips
when they have not been prepared.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*analysis*.py' -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_adventureworks_baseline.py -v
```

## Recorded local validation

On 2026-09-15, the complete package passed **202 tests without skips**, dependency
consistency checks and both existing Bicep compilations. This included the
prepared official dataset, independent integer-SQL oracle and Microsoft
ScriptDom AST validation of the proposed view against the projection contract.
For AST checks on another workstation, set `SCRIPT_DOM_ASSEMBLY` to an installed
compatible `Microsoft.SqlServer.TransactSql.ScriptDom.dll`; no assembly is
bundled with this template. Absent optional parser/sample inputs are reported
as skips, not live validation.
Final packaging also caught a Windows CRLF/LF mismatch in the checked-in
worked-ledger hash. Its Git format is now pinned to LF; all 11 focused
workflow tests passed after the correction, including portable-checkout
reproduction. Both local sample reports were regenerated.

The reports are local analytical evidence. They do not extend the earlier
hosted connectivity proof to the new sales queries or constitute a deployment
of the business-analysis agent.

## Not yet part of this baseline

Adaptive DeepSeek investigation, business tools hosted in Foundry, App Service
and Entra UI, customer-existing database onboarding, and a second-schema
configuration-only portability evaluation remain later milestones. A
synthetic arithmetic fixture is not that portability evaluation.
