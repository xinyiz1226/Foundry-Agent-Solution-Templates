# Minimal migration inventory

## Scope and evidence

This document supports [G0 technical validation](g0-validation-plan.md) and the
[implementation plan](implementation-plan.md). It is an inventory, not a source
transfer or an implemented architecture.

The DataFlowMVP source was inspected on September 14, 2026, at commit
`9439a0381767e18a42106c77ae864fbc477a5077`, then the default branch head.
Paths below are relative to that source repository unless stated otherwise.
Tests were read, not executed; cloud resources were not inspected.

Only architectural findings are recorded here. Do not copy existing operational
archives, resource identifiers, credentials, deployment receipts, databases,
or input bundles into this public template. Before moving source or sample
material, verify redistribution rights and attribution requirements.

## 1. Smallest useful migration

Use the full-document host's one-revision execution design as the starting
point, not the older first-chunk smoke host. Preserve the following behavior:

1. Bind a job to immutable inputs and execution configuration.
2. Claim one expected revision.
3. Restore verified inputs and the previous execution checkpoint.
4. Process at most one model attempt for that revision.
5. Publish artifacts and commit the checkpoint last.
6. Read results without advancing execution.

For G0, use one fixed sample and configuration. Do not require generic schemas,
natural-language configuration, full record review, or two-domain extraction
before proving browser-to-cloud execution. Those belong to G1 through G3.

The existing full-host runtime has a transitive closure of 14 source modules.
Copying only its entry point and Blob helper will not produce a working host.
Prefer a narrow, tested extraction of useful behavior over importing the
entire application and hiding its domain assumptions.

## 2. Source disposition

Names in this table describe existing files and symbols, not proposed target
interfaces. "Reuse" means preserve verified behavior after migration checks,
not copy without inspecting its dependencies.

| Existing source | Disposition | Minimum action and rationale |
| --- | --- | --- |
| `dataflow/hosted_full.py`: `run_full_job`, `read_full_result`, `create_host` | Adapt for G0 | Preserve revision claims, restore/execute/publish ordering, and explicit failed states. Separate browser-facing results from internal checkpoint metadata. |
| `dataflow/hosted_cloud.py`: `CloudSettings`, `main` | Adapt for G0 | Isolate startup/configuration and select the full host explicitly; the existing default selects the older smoke path. Inputs are currently deployment-configured. |
| `dataflow/blob_artifacts.py`: `BlobArtifacts` | Reuse behavior, adapt contract | Preserve create-only writes, verified materialization, bounded reads, and hash checks. Replace domain-specific input allowlists only when a new contract is defined. |
| `dataflow/extraction_run.py`: `run_extraction`, `export_run` | Adapt | Preserve chunk selection, attempt accounting, and explicit resume. Separate hard-coded model checks, request preparation, and domain reports. |
| `dataflow/extraction_store.py`: `ExtractionStore` | Reuse behavior, adapt records | Preserve transactional attempt/candidate updates. SQLite is a restored execution artifact, not a shared cloud coordination database. |
| `dataflow/extraction.py`: `prepare_inputs`, `plan_chunks`, `build_request`, `resolve_candidates` | Split incrementally | Keep chunk/evidence behavior; replace fixed business schema and freeze dependencies in G1, not by changing a prompt alone. |
| `dataflow/parser.py`: `parse_filing` and document types | Retain as a domain adapter | Preserve SEC parsing and evidence locations. Do not fabricate SEC identities to make plain text pass; add a genuine text adapter in G1. |
| `dataflow/snapshot.py`, `dataflow/preflight.py` | Adapt | Preserve source freezing and revalidation. Existing snapshot identity, filenames, parsing, and manifest checks are filing-specific. |
| `dataflow/foundry.py`: `complete_json`, configuration/errors | Adapt | Keep explicit model failures and disabled automatic inference retries. Inject the hosted model client rather than requiring local CLI authentication. |
| `dataflow/taxonomy.py`, `dataflow/revisions.py` | Extract only required behavior | Evidence eligibility, category validation, and reporting currently create import dependencies. Full taxonomy generation/revision is not required for G0. |
| `dataflow/simulation.py` | Decouple | Currently imported eagerly by the execution module even on the hosted path. Retain only until tests prove that the dependency can be removed. |
| `dataflow/__init__.py` | Retain package support | Required by the current module layout; target packaging may change after import verification. |
| `dataflow/hosted_package.py`, `deploy/requirements.txt` | Adapt for G0 | Preserve explicit package allowlisting. Verify the real runtime manifest through clean imports and startup, not just ZIP creation. |
| `review_app.py`, `dataflow/review_ui.py`, `dataflow/results_ui.py` | Adapt incrementally | Reuse presentation where practical. Add a cloud run/status view first; existing review assumes local completed runs and domain fields. |
| `dataflow/review.py`, `dataflow/results.py` | Defer full integration to G3 | Preserve source/run binding and review-version semantics. Do not assume a downloaded candidates file is a complete review workspace. |
| `dataflow/research_contract.py`, `dataflow/research_extraction.py` | Defer | Three-year research and specialized analysis are not prerequisites for the template. They remain in the unchanged source package allowlist until deliberately removed. |
| `dataflow/hosted_local.py`, broad existing CLI | Reference only | Local simulation and developer commands are not the browser/cloud durability implementation. |
| Migration utilities, migration archives, existing result bundles | Exclude | These extend a private development environment; they are not portable sample inputs or runtime dependencies. |

### Packaging and dependency implications

The inspected package includes the 14-module full-host closure, two optional
research modules, a generated entry point, and the deployed requirements file.
The package builder itself is build-time code.

Runtime dependencies cover HTML parsing, model access, identity, HTTP,
tokenization, Agent Framework/Invocations hosting, and Blob storage. The
source deployment manifest pins direct dependencies, not the entire transitive
dependency graph. The broader development manifests are not interchangeable
with the deployed manifest.

Keep web and hosted-worker dependency sets distinct. Inspect actual clean-build
resolution before carrying version pins forward. Historical source runtime
and deployment notes are evidence to investigate, not proof that a new target
environment supports the same configuration.

## 3. Existing execution contract: important limitations

The full host accepts `run`, `resume`, and `result`. Mutations include an
expected revision; `result` serves as both progress and latest-checkpoint
retrieval. There is no separate status operation, upload operation, or
per-request document/schema selector.

Results contain metadata and artifact references, not the complete inline
candidate dataset. A browser needs server-side verified artifact retrieval
and a deliberately limited display representation.

| Existing behavior | Migration implication |
| --- | --- |
| One attempt per committed revision | Do not simply increase chunk count: checkpoint validation ties cumulative attempts to revisions. |
| Chunk-level commits with block coverage | Do not claim independently durable checkpoints for every source block. |
| Immutable revision claim and create-only Blob writes | This is not a lease with automatic expiry or takeover. |
| Checkpoint published after artifacts | Partial publication must not look completed; some orphaned artifacts may need investigation. |
| Matching duplicate consumed revision returns saved output | Preserve idempotency for known committed work and reject incompatible replays. |
| Handled model failure can be committed | Explicit resume is possible, but a timed-out model request may already have incurred work or cost. |
| Unknown interruption can leave a blocking claim | Show an unresolved state; do not automatically delete the claim or replay inference. |
| No backend multi-revision driver | A browser-only change cannot provide start-once batch execution. |
| Selected SEC sections form the processing plan | "Full document" in the source does not mean every section of a filing. |

The inspected model client has a 180-second timeout and disables automatic
model retries. The host has no explicit overall workflow deadline, and
subsequent revisions include pacing. Local token/rate accounting is not
deployment-wide coordination. G0 must measure the actual hosting lifecycle
before selecting batch limits or promising recovery.

## 4. Proposed modules and seams

These are design responsibilities, not existing classes or a mandate to
introduce a separate deployable tier for each row.

| Proposed module | Interface callers should learn | Behavior hidden in its implementation |
| --- | --- | --- |
| Execution module | Start a fixed input/configuration, inspect a job, explicitly resume a paused job | Revision ownership, bounded advancement, checkpoint verification, attempt accounting, and durable states |
| Workbench module | Operator actions and readable job/candidate views | Display state, authenticated transport, artifact projection, and polling without mutation |
| Document module, G1 | Normalize a supported source into stable evidence blocks | SEC HTML and plain-text adapters; format-specific validation and locators |
| Extraction module, G1 | Extract schema-conforming candidates from frozen blocks/configuration | Model interaction, evidence reconstruction, and explicit validation failures |
| Configuration/evaluation/review modules, G2-G3 | Versioned proposals, explicit evaluation runs, and record decisions | Their distinct persistence and validation rules; no silent cross-workflow updates |

Do not make the browser learn claim names, SQLite filenames, checkpoint-chain
validation, or framework sessions. Those details should have locality inside
the execution module.

The document seam has two concrete adapters planned for G1. Use existing
model/Blob test substitutes to exercise execution through its interface; do
not create speculative storage abstractions or a generic plugin platform.

## 5. Verification anchors to preserve

| Source tests | Behavior to carry into target tests |
| --- | --- |
| `tests/hosted/test_full_host.py` | Fresh-worker restoration, duplicate revisions, competing writers, failures, cancellation, integrity, and pacing |
| `tests/hosted/test_blob_artifacts.py`, `test_blob_sdk_contract.py` | Create-only operations, bounded verified reads, and SDK call assumptions |
| `tests/hosted/test_cloud_entry.py`, `tests/test_hosted_package.py` | Host selection and package allowlist; supplement with real clean import/startup checks |
| `tests/test_extraction_run.py`, `test_extraction_store.py` | Attempt accounting, completed-chunk preservation, and transaction guards |
| `tests/test_parser.py`, `test_preflight.py`, `test_extraction.py` | Source locators, input binding, coverage, and evidence validation |
| `tests/test_review_ui.py`, `test_results.py` | Review/source consistency, stale-state rejection, and export behavior |

Rebuild fixtures using approved public or synthetic data. Preserve behavior
tests rather than private runtime snapshots. G0 acceptance details and the
unresolved design decisions are in the companion validation plan.
