# Bounded hosted analysis: prepared, not cloud-validated

The `business-investigator` service is separate from the verified `sql-probe`.
It packages the shared `analysis/` engine from the project root instead of
copying a second implementation into the agent directory. Local artifacts,
Azure profiles, environment files and local configuration are excluded from
the source package. The runtime exposes Responses/2.0.0; its internal adaptive
model transport is explicitly Chat Completions.

**No new cloud experiment or actual DeepSeek analytical evaluation has been
performed for this milestone.** Previous connectivity approval expired with
its experiment. A new disposable group, resource/cost scope, deadline and
exact temporary shared-model grant require fresh approval. The proposed next
scope is Central US infrastructure with the existing East US DeepSeek
deployment; it is not an authorization or a reservation.

## Request contract

The trusted packaged [policy](../analysis/hosted-policy.json) fixes the sample,
November/December 2013 periods, explicit completeness attestation and expected
source hash/counts/totals. A request cannot replace periods, SQL, a view,
credentials or execution limits.

```json
{"mode":"baseline","question":"Compare the approved periods."}
```

```json
{"mode":"adaptive","question":"Investigate the largest declining territory and its products."}
```

A plain question selects adaptive mode. Duplicate keys, unknown fields, missing
fields and oversized questions are rejected before SQL or model access.
Baseline mode invokes no model. Adaptive mode delegates only to the
[bounded investigation engine](adaptive-evaluation.md); free-form model prose
is not authoritative analytical evidence.

The response ends with exactly one `BPI_ANALYSIS_RESULT=` JSON marker.
Reserved-marker text inside values is escaped without changing decoded values.
Failures use the same marker with `status: failed` and a sanitized error code,
not a fabricated successful result. Successful SQL cleanup is required before
a completed report can be emitted.

## Private SQL boundary

Use only the [separately approved disposable initialization path](analysis-initialization.md).
It loads a normalized sample snapshot, not a restored full AdventureWorksDW
database and not an existing customer's database. The proposed
`sql/analysis-view.sql` full-DW projection remains a distinct integration path.

Each request opens one managed-identity SQL connection, rejects non-private
DNS candidates, verifies the normal Azure SQL hostname against the CA bundle,
requires encryption of the full session and disables connection retry/pooling.
Developer-credential fallback is rejected. It explicitly begins a SNAPSHOT
transaction, verifies the dedicated user and database, checks the approved
manifest and actual row count/monetary totals, and validates required and
prohibited permissions before exposing the cursor to analytical tools.

The approved read surface is `reporting.v_internet_sales` and
`reporting.v_analysis_manifest`. The backing tables are
`reporting.internet_sales_snapshot` and
`reporting.analysis_snapshot_manifest`. SELECT on backing tables, DML, schema
ALTER and checked database DDL/CONTROL permissions must be absent; NULL
permission results are failures, not interpreted as denial. These are explicit
checks of the named permissions, not an exhaustive audit of every SQL privilege.

Both modes share a ten-analytical-request budget, a Top-K ceiling of 5 and a 120-second analytical
budget. The snapshot-begin operation, identity/manifest/permission query and
rollback are separately reported control overhead, not hidden inside those ten
data requests. Query/connect timeouts are configured at 15 seconds each.
Model transport timeout is 30 seconds with no SDK retries. Budgets stop further
dispatch; they are not a process-kill guarantee or a monetary spending cap.

Every exit attempts rollback and closes both cursor and connection, including
setup failures. Cleanup failure prevents reporting successful completion.

## What still needs live evidence

`scripts/validate-agent.ps1` is still a probe-only validator and explicitly
rejects analytical service/mode bindings. Use the separate
[analytical acceptance entrypoint](cloud-analysis-validation.md), which verifies
live context and both reports against the pinned reference. Its implementation
has been exercised locally with doubled cloud boundaries, not run in Azure.
Do not reuse a successful probe marker to declare the new service validated.

The metadata hash is an initializer attestation, corroborated with runtime
counts/totals. It is **not** a runtime cryptographic hash of every SQL row.
The separate cloud experiment must additionally verify:

- The deployed agent's actual application/client ID matches the returned SQL SID.
- SQL public access is disabled and the approved private endpoint is in use.
- Source remote build includes the shared engine and policy.
- Actual DeepSeek tool calls, usage and latency under the bounded protocol.
- Both modes run the approved sample and periods, and recorded aggregate
  evidence agrees with the independently checked offline reference.
- The exact new model role is revoked and owned active resources are deleted.

Offline replay measures harness behavior only. It establishes neither model
quality nor an advantage over the deterministic baseline. Unknown token usage,
prices or delayed Azure charges must remain explicitly unknown.
