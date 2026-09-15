# Owned-pilot analysis snapshot initializer

This is an **opt-in normalized reporting snapshot**, not an AdventureWorksDW
restore and not the full-DW view proposal in `sql/`. It loads only the eight
nonpersonal normalized fields already produced by `scripts/prepare_sample_data.py`.
The full-DW proposal is unchanged. No customer database is adopted.

## Current execution gate

Local preparation is supported and verified. **Cloud execution remains gated**:
the new experiment's cloud budget/scope confirmation was unavailable. Do not
interpret this implementation, a preparation marker, or compiled ARM as approval
to provision, initialize, connect to SQL, deploy/invoke a model, or change shared
resources. Obtain a fresh explicit experiment approval before any cloud step.

## Reproduce locally without Azure, tokens, DNS, or SQL

From the template directory, with the existing official sample cache:

```powershell
.\scripts\initialize-analysis.ps1 -PrepareOnly -Offline `
  -CacheDirectory .artifacts\adventureworks `
  -OutputDirectory .artifacts\analysis-initialization `
  -AgentClientId 11111111-2222-3333-4444-555555555555 `
  -AgentPrincipalId aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee
```

These illustrative GUIDs are suitable only for local SQL batch construction.
For a real deployment, `deploy.ps1` still discovers the hosted agent and verifies
its supplied object ID against its directory service principal/client ID.
The initializer never substitutes the project or initializer identity.

`-PrepareOnly` exits before module installation, Azure authentication, DNS, or
database connection. `-Offline` forbids download on cache miss. Omitting `-Offline`
permits a bounded HTTPS download of the **public official source ZIP only**;
bad cached bytes fail closed instead of being silently replaced.

The .NET projection checks the pinned ZIP and six allowed member hashes,
dimensions, widths/row counts, all fact joins, order-line uniqueness, midnight
order dates, currency identity, order currency consistency and exact SQL-money
conventions. It projects CurrencyKey 100 only, retaining source ordering and
four-decimal monetary text. No ZIP members are extracted to disk, no Python or
other OS runtime is installed, and no personal source columns reach the output.
It reproduces the Python-generated CSV byte for byte:

| Evidence | Expected value |
| --- | --- |
| Normalized rows | 33,400 |
| Distinct orders | 14,860 |
| Sales amount | `14693465.3186` |
| Total product cost | `8611268.3850` |
| CSV SHA256 | `45d1a25c2b301f730e635fc789fc3ee08c6bb7a9a946159105be7ad00997259f` |
| Source ZIP SHA256 | `73c27309d17cd30bf5351665401106abf649d9f9a9ecb0c770682f6be965aba8` |

Output contains `internet_sales.csv`, `preparation.json`, and `guard.sql`,
`snapshot.sql`, `create.sql`, `finalize.sql`. A `BPI_ANALYSIS_PREPARATION` marker has
`initialized=false` and `snapshotIsolationState=0`; **it proves no SQL execution**.
Keep the sample's MIT notice and provenance in `data/`. November/December 2013
remain reviewed demonstration periods, not production-certified completeness.

## Future approved first Initialize

After a separately approved fresh experiment has provisioned its own private SQL
`pilot` and deployed its actual hosted-agent identity, select the mode at its
**first** Initialize:

```powershell
# NOT authorization to execute: requires new approved cloud budget/scope first.
.\scripts\deploy.ps1 -ConfigPath .\approved-new-experiment.json `
  -Stage Agent -AgentName business-investigator -ApproveAzureChanges
.\scripts\deploy.ps1 -ConfigPath .\approved-new-experiment.json `
  -Stage Initialize -AgentName business-investigator -InitializationMode AnalysisSnapshot `
  -AgentPrincipalId '<actual-deployed-agent-object-id>' -ApproveAzureChanges
```

Omitting `-InitializationMode` retains `Probe`. The flag is invalid on other
stages. Initialization mode is persisted in ownership state; switching modes,
adopting an old probe ACI, or converting an already initialized pilot is refused.
`-AgentName` defaults to `sql-probe` and is accepted only on Agent/Initialize.
The selected service is saved as `state.agentName` before Agent deployment and
checked before subsequent deployment or identity lookup. Analysis initialization
requires `business-investigator` **and** explicit `AnalysisSnapshot`; neither is
silently inferred from the other. Legacy already-deployed states without
`agentName` remain bound to `sql-probe`, never adopted as the new service.

`analysis-bootstrap.bicep` uses exactly the original planned
`bpi-<owned-prefix>-bootstrap-aci` name, `sql-initializer` container, pinned
Microsoft AzurePowerShell 14 image digest, initializer UAMI, private initializer
subnet, inherited existing NAT, and original ownership tags. It adds no storage,
public endpoint, firewall exception, identity, model, or shared-resource change.
The small script and public manifest are packaged in ARM; the ZIP is downloaded
in-container over existing approved egress. No data-sized base64 delivery exists.
The pinned `SqlServer` PowerShell module `22.4.5.1`, as in the probe initializer,
provides `Microsoft.Data.SqlClient`; no new OS runtime is assumed.

## Database contract and permissions

Only the owned empty new `pilot` is accepted. Existing user objects or an existing
`bpi_probe_agent` cause refusal, never overwrite/truncate/adoption. Snapshot
isolation is explicitly enabled on this disposable database, without disconnecting
other sessions. A bounded transaction creates the snapshot and original probe
fixture, loads typed data with token-authenticated `SqlBulkCopy` (no row-value SQL),
reconciles rows/orders/monetary totals, creates views, and verifies the runtime SID,
permissions and snapshot state before committing.
The CSV hash identifies the verified bulk-copy input; SQL reconciliation checks
typed rows, distinct orders and exact totals, not the database's physical storage
bytes or a CSV reconstructed from an unordered table.

- Backing table: `reporting.internet_sales_snapshot`.
- Approved normalized view: `reporting.v_internet_sales`, with the existing eight
  snake-case analytical columns.
- Original `reporting.pilot_probe` / `reporting.v_pilot_probe` and amount `42.00`
  remain available to the existing connectivity validator.
- Manifest backing table: `reporting.analysis_snapshot_manifest`; SELECT-only approved view:
  `reporting.v_analysis_manifest(source_sha256, dataset_id, row_count)`.
  It has exactly one row, populated in the same load transaction. `source_sha256`
  is the normalized CSV SHA256 shown above, **not** the source ZIP hash.
  `dataset_id` is
  `adventureworksdw-2025-install-snapshot-internet-sales-currencykey-100-usd`;
  `row_count` is `33400`. The runtime can independently verify this view and its
  own SQL SID in its snapshot transaction.
- Runtime database user remains `bpi_probe_agent`, with Entra external-user SID
  from the actual agent **client ID**, not its object ID.
- Grants are `CONNECT`, `SELECT` on the three approved views, and object-scoped
  `VIEW DEFINITION` on those views and backing tables to make explicit
  `HAS_PERMS_BY_NAME` checks non-null. No backing-table SELECT, writes, database
  roles, schema grants, database-wide metadata grants, or DDL rights are granted.
- Snapshot isolation support does not itself make all sessions read-only:
  the runtime must open its own snapshot transaction and use approved-view SELECT.

## Completion, retries and cleanup

ARM success is insufficient. The lifecycle checks original ownership/image/UAMI/
subnet guards plus the exact planned ACI name, mode tag and identity/SQL environment.
Only a zero exit code and exactly one `BPI_ANALYSIS_INITIALIZER_RESULT` marker with
matching source/normalized hashes, 33,400 rows, exact totals, view/table names,
manifest view/table and dataset identity, both runtime IDs, probe amount and
`snapshotIsolationState=1` permits initialized
state. Evidence and resource inventory are saved in the existing ownership state.

The original 900-second owned-container wait/stop bound remains; download, SQL
connection, SQL commands, locks and bulk copy also have explicit bounds.
`-RetryInitialization` refuses active work, wrong mode, and successful analysis
runs. Failed terminated runs may be explicitly retried in the same mode. A rolled
back load leaves no committed tables. Enabling snapshot isolation occurs outside
that transaction and can remain enabled after failure. A committed load with lost
completion evidence **cannot** be blindly rerun: the empty-database guard refuses.
Inspect and clean up/recreate that disposable experiment rather than weakening
the guard. Reusing a completed ACI verifies its original evidence; runtime
validation remains necessary before claiming current connectivity or data access.

Cleanup guards and planned resources are unchanged; there is no second untracked
ACI to remove. Use the existing ownership-checked teardown and verify deletion.
`deploy.ps1` has no Validate stage. The existing `validate-agent.ps1` is
probe-specific and explicitly rejects analysis service/mode bindings before any
cloud calls; it cannot set an analysis experiment to `validated` based on the old
probe fixture or `BPI_PROBE_RESULT`. A dedicated approved analytical cloud
validator and live-run evidence remain outstanding.

## Offline validation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_analysis_bootstrap.py
```

Tests use the actual cached official sample without download, compare the exact
Python CSV, and exercise the real Initialize entrypoint with intercepted CLI
boundaries. Set `SCRIPT_DOM_ASSEMBLY` to an existing ScriptDom DLL to additionally
parse every generated SQL batch and nested view/schema definition. Compile
`infra-bicep\analysis-bootstrap.bicep` with an existing Bicep executable; neither
operation establishes live SQL/Entra/ACI success.
