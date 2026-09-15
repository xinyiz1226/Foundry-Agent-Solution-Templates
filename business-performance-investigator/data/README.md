# Local AdventureWorksDW acquisition and audit

This directory contains provenance/configuration only, not raw sample records.
`adventureworks-manifest.json` pins Microsoft's official DW install-script ZIP
(release asset 318027345, November 2025), its published SHA256, selected member
hashes, source schema, MIT license, reviewed counts and demonstration periods.
The SQL script says the data is fictitious. Its release date is **not** the fact
coverage date. The repository-level license is reproduced in
`MICROSOFT-SAMPLE-LICENSE.txt`; the manifest pins the upstream license revision.
The license SHA256 refers to the upstream LF bytes; Windows checkout line endings
may differ without changing the copied notice.

## Run locally

From `business-performance-investigator`, using an existing Python 3 environment:

```powershell
.\.venv\Scripts\python.exe .\scripts\prepare_sample_data.py
.\.venv\Scripts\python.exe .\scripts\prepare_sample_data.py --offline
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_sample_data.py
.\.venv\Scripts\python.exe -m analysis --csv .\.artifacts\adventureworks\internet_sales.csv --config .\.artifacts\adventureworks\analysis-config.json --output .\.artifacts\adventureworks\analysis
```

The first command downloads the public Microsoft archive if absent. The second
uses only cached bytes. No packages, SQL instance, Azure resource or model calls
are needed. `--manifest` and `--artifacts-dir` override defaults. The public Python
seam is `prepare_sample_data(manifest_path, artifacts_dir, offline=False)`, returning
the audit dictionary or raising `SampleDataError`. The CLI exits nonzero with an
explicit error when verification/preparation fails.

Default ignored artifacts:

- `.artifacts\adventureworks\AdventureWorksDW-data-warehouse-install-script.zip`
- `.artifacts\adventureworks\internet_sales.csv`
- `.artifacts\adventureworks\audit.json`
- `.artifacts\adventureworks\analysis-config.json` (parent analysis-tool contract)

Only the archive is downloaded; **nothing is extracted**. The four analytical tables,
the nonpersonal `DimCurrency` authority and schema script are read in memory;
other ZIP contents (including fictitious
customer/employee columns) are never read or projected. Keep the entire artifact
directory ignored. Do not commit or redistribute the raw ZIP from this project.

The downloader has a 20 MB ceiling, 30-second socket timeout, 120-second checked
elapsed-time budget and no retries. A blocking socket read can extend the elapsed
budget by at most its timeout. It checks expected size and SHA256 before caching.
Cached bytes are always reverified. ZIP processing rejects duplicate/unsafe names,
symlinks, encrypted entries and excessive member counts, expansion or compression
ratios. No SQL is executed. A changed upstream release fails closed: investigate
and deliberately review a new pin rather than bypassing hash verification.

## Normalized contract

UTF-8, comma-delimited CSV with a header and LF records, preserving source row
order and exactly these eight columns:

```text
order_date,sales_order_number,product_id,product_name,territory_id,territory_name,sales_amount,total_product_cost
```

- Grain is **one Internet Sales order line**, not one order. Count distinct
  `sales_order_number` for orders; do not deduplicate projected lines. The default
  scope is **`FactInternetSales.CurrencyKey = 100`**, verified as **USD / US Dollar**
  against the official pinned `DimCurrency.csv`, not guessed from the key.
- `order_date` is ISO `YYYY-MM-DD`, joined from `DimDate` by `OrderDateKey`.
  The fact's explicit midnight `OrderDate` must agree. Ship/due dates are not used.
- Product and territory IDs are **surrogate keys**, not business alternate keys
  or labels. `product_name` is `EnglishProductName`; `territory_name` is
  `SalesTerritoryRegion`. Names need not uniquely identify a dimension member.
- The two monetary fields retain exact four-place source SQL `money` text:
  use `Decimal`, never binary floating point. In 1,768 output rows the source cost is
  `.8565` (without a leading zero); this is intentional and preserved.
- Sales excludes source tax/freight. All 60,398 source quantities are one and
  discounts zero. Preparation validates unit/extended sales and cost conventions.
- **Currency scope:** the eight-column projection does not carry currency because
  every output row is in the verified USD-key subset. No FX conversion is performed.
  Official `DimCurrency` verifies key 100, code `USD`, name `US Dollar`; its 2,104
  bytes / 105 rows have SHA256
  `9ff911e2d0447204806722e736d74e9686faad7c68b9fe896446ed83264239f6`.
  Source `CurrencyKey` counts before filtering are **100: 33,400; 6: 12,988;
  19: 7,135; 98: 6,740; 29: 76; 39: 59**. Filtering excludes **26,998** rows,
  retaining **33,400**. The audit retains pre/post counts, the exact filter, and
  rechecked per-period coverage. Currency identity is verified, but no general
  common-base-currency semantics or production accounting certification is claimed.
  All-key source totals remain separately labelled **source-unit experimental
  totals, not certified financial amounts**. The ignored full official ZIP is
  retained for later wider-scope support.
- No names of people, emails, customer IDs, addresses, tracking numbers or purchase
  order numbers are emitted.

## Reviewed observations and completeness

| Observation | Exact value |
|---|---:|
| Source FactInternetSales rows / filtered output rows | 60,398 / 33,400 |
| Rows explicitly excluded by currency scope | 26,998 |
| DimDate / DimProduct / DimSalesTerritory rows | 3,652 / 606 / 11 |
| DimCurrency rows | 105 |
| Output distinct orders / sold product keys / sold territory keys | 14,860 / 158 / 10 |
| Fact order-date range | 2010-12-29 through 2014-01-28 |
| Date dimension range | 2005-01-01 through 2014-12-31 |
| USD-key subset SalesAmount total | 14693465.3186 |
| USD-key subset TotalProductCost total | 8611268.3850 |
| All-key source-unit experimental sales / cost totals | 29358677.2207 / 17277793.5757 |
| CSV SHA256 | `45d1a25c2b301f730e635fc789fc3ee08c6bb7a9a946159105be7ad00997259f` |

The audit includes exact monthly/yearly rows, distinct orders, monetary sums,
calendar-day activity, dates without fact rows, input/output hashes, dimension
uniqueness, missing-key checks, order-line uniqueness and date consistency.
Dates without activity alone cannot distinguish zero sales from missing records.

The chosen USD-key baseline is **2013-11-01 through 2013-11-30**: 2,966 rows,
1,164 orders, sales 1032823.6600, cost 599198.8073. The comparison is
**2013-12-01 through 2013-12-31**: 3,091 rows, 1,203 orders, sales
1033955.1800, cost 600965.0916. Each still has activity on every calendar day
after filtering. These are subset observations, not worldwide/all-currency sales.

These are **reviewed interior-period assumptions for an official fictitious
sample snapshot**, not production completeness certificates. Their choice combines
pinned provenance, reviewed calendar activity and validated joins/counts; it is
**not inferred solely from the latest fact date**. December 2010 (facts begin
December 29) and January 2014 (facts end January 28) are partial boundary months
and deliberately excluded. Broad coverage in DimDate does not certify fact coverage.
There is no data-owner sign-off, extract watermark, source reconciliation or
late-arrival policy. Obtain those before asserting production period completeness.

### Analysis-tool coverage contract

The audit exposes these **exclusive-end `[start,end)`** intervals:

```json
{
  "baseline": {"start": "2013-11-01", "end": "2013-12-01"},
  "current": {"start": "2013-12-01", "end": "2014-01-01"},
  "coverage": {
    "start": "2013-11-01",
    "end": "2014-01-01",
    "attestation": "Reviewed official sample snapshot assumption; not a production data completeness guarantee."
  }
}
```

The actual audit carries a longer, nonempty attestation stating the supporting
evidence and limitations. Pass these objects directly to the local analysis tools;
reject requests outside this explicit coverage even though the CSV contains other
dates. This coverage is deliberately narrower than the fact-date range.
`demonstration_periods` retains its separately labeled inclusive source-review dates.
Preparation validates that the chosen periods are contiguous full calendar months.

`analysis-config.json` is generated with the exact parent-tool keys `dataset_id`,
`csv_sha256`, `coverage`, `baseline`, `current`, `top_k`, `limits` and `view`.
It pins this CSV hash, uses top 5, limits of 10 requests / 1,000 groups / 30 seconds,
and logical view `reporting.v_internet_sales` (no SQL connection or mutation).
The dataset ID is
`adventureworksdw-2025-install-snapshot-internet-sales-currencykey-100-usd`;
the attestation explicitly identifies the verified USD-key sample scope.
Use its path with the parent CLI's `--config`, the CSV path with `--csv`, and a
separate result directory with `--output`.

For the parent's proposed SQL view, retain the same four analytical joins and
apply the exact predicate **`WHERE [fis].[CurrencyKey] = 100`**, where `[fis]`
aliases `[dbo].[FactInternetSales]`. No date restriction belongs in this projection:
the separate analysis coverage/config restricts requests. Verify the deployed
database's `DimCurrency` key/code/name correspondence before reusing this sample
predicate against a different database/version.

The matched proposal is **`sql\analysis-view.sql`**, explicitly **not deployed**.
It joins `DimDate.DateKey` to `FactInternetSales.OrderDateKey` and casts the calendar
date to SQL `date`; both monetary measures are cast to `decimal(19,4)`. Surrogate
keys and the eight normalized aliases match the local projection. It contains only
the proposed view statement. Optional schema creation is commented out in a
separate manual-approval section; no grants, users, identities, networks or
databases are provisioned. Neither local command executes this SQL.

The focused tests check the complete executable SQL projection against the
manifest's filter and verify all join/date/amount expressions. When an installed
SqlServer module exposes ScriptDom, tests also inspect its parsed AST (no SQL
execution). For a nonstandard existing installation, set `SCRIPT_DOM_ASSEMBLY`
to the full `Microsoft.SqlServer.TransactSql.ScriptDom.dll` path before running
the same tests. Without that assembly, only the parser-specific test is skipped;
the complete static projection contract still runs. No parser packages are installed.

Preparation is deterministic and does not include wall-clock timestamps in output.
Validation failures preserve the last verified output. Each output file is replaced
atomically, but the pair is not a transaction: consumers should verify the CSV's
SHA256 against `audit.output.sha256` before use, especially during concurrent runs.
Tests use clearly synthetic tiny transport fixtures; the cached-official-data test
also checks the actual Microsoft projection when the archive is present and skips
without downloading when it is absent.
