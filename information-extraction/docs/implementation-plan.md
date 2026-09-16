# Information Extraction Solution Template: Implementation Plan

## Status and purpose

This plan records the scope agreed on September 14, 2026. It is a planning
artifact, not a claim that all capabilities described below already exist.
The [execution core](../README.md) is implemented, and a
[bounded synthetic hosted probe](hosted-smoke-results.md) has completed.
A [local synthetic workbench](local-workbench.md) now supports current-job
rediscovery, explicit start/resume, and evidence inspection. The
[authenticated cloud workbench](cloud-workbench.md) is deployed: bounded
human acceptance demonstrated protected historical current-job content and
Entra rejection of the unassigned test identity. A subsequent fresh-job
window demonstrated protected Start/limit/Resume completion and expanded
source evidence through the deployed managed-identity path. Live disconnect
and expiry behavior, single-start two-chunk cloud progression, repeatable
provisioning, and complete G0 remain outstanding. See the bounded observations and
limitations in [guarded deployment](guarded-deployment.md), rather than
treating the earlier read-only preflight as the current deployment state.

The [configured-core slice](configurable-extraction.md) now supports frozen
flat schemas, field-level source references, and a shared financial/support
execution path. A scripted two-domain rehearsal exercises local persistence,
failure/resume and historical replay. Configured plans also round-trip through
the Blob adapter with offline clients, and the optional Responses adapter
derives its prompt/schema from the frozen profile. Legacy G0 serialization and
model bindings are preserved. This is not live support extraction, UI
integration, review/export, held-out evaluation, or complete G1.

Execution planning is detailed in the [minimal migration inventory](migration-inventory.md)
and [G0 technical validation plan](g0-validation-plan.md). The
[batch hosting feasibility decision](batch-hosting-feasibility.md) selects
Foundry native resilient tasks Preview for a model-free G0 implementation,
with a limited hosted result and explicit remaining probes. These documents
distinguish inspected source behavior from proposed work and unverified cloud
capabilities.

The goal is to contribute a standalone Microsoft Foundry solution template
for an intelligent document extraction workbench. All code and documentation
for this contribution will live under `information-extraction`.

The workbench will turn supported unstructured documents into configurable,
evidence-linked structured records. It will demonstrate the complete lifecycle
of configuring an extractor, trying it on samples, improving its configuration,
evaluating it, applying it to a batch, reviewing records, and querying or
exporting approved results.

The reference user journey is
[Agent Bricks Information Extraction](https://learn.microsoft.com/en-us/azure/databricks/agents/agent-bricks/info-extraction).
The implementation will not depend on Databricks, Unity Catalog, `ai_extract`,
Genie Code, or Lakeflow.

Broad parity with the reference product's observable capabilities is a
long-term roadmap goal, not a prerequisite for the first contribution.
Functional similarity does not imply equivalent accuracy, latency, cost,
scale, or service guarantees.

### Delivery priority: September 16, 2026

Prioritize the shortest path to a usable end-to-end MVP over minor Azure
cost savings. Reuse the existing working web/agent/storage deployment;
add modest resources when they materially accelerate delivery and disclose
the approximate incremental cost. Do not repeatedly block delivery for
small cost-only decisions, repeat completed login checks, or redesign the
frontend. This does not relax identity boundaries, historical-data
preservation, explicit execution budgets, or public-exposure limits.

The [fresh synthetic execution preparation](local-workbench.md#prepare-independent-acceptance-jobs)
and bounded human Start/limit/Resume/evidence acceptance are complete.
Move product implementation to configurable flat schemas, UTF-8 input,
the ABCD customer-support second domain, durable review and approved export;
track the remaining reconnect/expiry and single-start cloud probes
separately rather than repeating the completed login or mutation checks.
Maintainer alignment can proceed in parallel; no upstream PR is implied.

For development budgeting, public USD retail prices checked September 16:

| Component | Assumption | Approximate cost |
| --- | --- | --- |
| Existing Linux B1, West US 2 | 1 instance, 730 hours/month at $0.017/hour | $12.41/month; stopping the app does not remove this plan charge. |
| Another dedicated Linux B1 if actually needed | Same size and region | An additional $12.41/month, not provisioned by this preparation. |
| Hot LRS Block Blob, East US | First capacity tier, $0.0208/GB-month | About $0.21/month for 10 GB, plus transactions, transfer and any logging. |
| Hosted agent runtime and real inference | Depends on runtime allocation, active sessions and chosen model | Not included in the amounts above; no reliable hosted-runtime unit quote was established in this check. Synthetic execution has no real-model token charges. |

Sources: [App Service Linux retail meter](https://prices.azure.com/api/retail/prices?$filter=serviceName%20eq%20%27Azure%20App%20Service%27%20and%20armRegionName%20eq%20%27westus2%27%20and%20skuName%20eq%20%27B1%27)
and [East US Hot LRS retail meter](https://prices.azure.com/api/retail/prices?$filter=serviceName%20eq%20%27Storage%27%20and%20armRegionName%20eq%20%27eastus%27%20and%20skuName%20eq%20%27Hot%20LRS%27%20and%20meterName%20eq%20%27Hot%20LRS%20Data%20Stored%27).
These are component estimates, not an invoice, an all-in forecast or a
spending cap; discounts, taxes, traffic and model selection can change totals.
The [Foundry Agent Service pricing page](https://azure.microsoft.com/en-us/pricing/details/foundry-agent-service/)
confirms that hosted agents incur hourly container-compute charges, separate
from model tokens; it did not expose a numeric runtime rate in this check.
This preparation itself adds no Azure resource or real-model usage.

## 1. Positioning and intended user

The first release is a deployable, single-operator reference workbench for
developers who want to adapt a Foundry-hosted extraction workflow to their own
document domains.

It is not:

- A complete financial research product.
- A general-purpose RAG or knowledge-chat application.
- An arbitrary-file parsing platform.
- A production-certified, multi-tenant data processing service.

Financial reports are the primary reference sample, not the core product.
ABCD customer-support conversations are the selected second domain, replacing
the earlier customer-adoption meeting sample. Extract explicitly stated
customer issues/requests, products, attempted actions, and outcomes with
original-turn evidence. These are human role-play conversations with fictional
scenarios, not production support tickets. The
[ABCD input-preparation slice](abcd-support-sample.md) provides a bounded local
importer and an independently authored format fixture. The support profile
now runs through the shared core with scripted fixture responses; real support
extraction and evaluation remain G1 work. Hidden scenario facts and task labels
must not become source evidence or automatic extraction gold.

The downstream demonstration will use deterministic filtering and aggregation
across documents, with traceability from each result to its approved records
and original evidence. Producing syntactically valid JSON alone is not a
sufficient demonstration of usefulness.

Before transplanting the implementation into this repository, confirm with
maintainers:

- The standalone template's name and contribution scope.
- Its distinction from the planned Enterprise Knowledge Agent template.
- Whether the proposed hosted workflow and protocol choices fit the repository.
- The expected deployment, documentation, and validation surfaces.

Do not add an unnecessary autonomous agent merely to make the workflow look
more agentic.

## 2. Existing baseline and principal gaps

DataFlowMVP provides a useful starting point rather than a finished template.
Its existing implementation includes a Foundry-hosted deterministic workflow,
Blob-backed checkpoints, explicit recovery, document chunking, structured
extraction, source-reference validation, and a local Streamlit review workflow.

The main gaps to address are:

| Gap | Required change |
| --- | --- |
| Domain coupling | Separate company, year, taxonomy, document parsing, and model assumptions from reusable execution logic. |
| Disconnected interaction | Connect the browser workbench to cloud execution and durable review state. |
| Missing configuration lifecycle | Add schema generation/editing, sample feedback, version comparison, and explicit configuration changes. |
| Limited quality evidence | Introduce explicit labeled evaluation datasets, matching rules, and visible error analysis. |
| Incomplete adoption path | Provide reproducible provisioning, sample initialization, operating guidance, and cleanup without relying on a developer's existing environment. |

Increasing the number of financial-report runs or completing the previous
three-year research product is not the first priority for this contribution.
Only necessary implementation components and distributable samples should be
carried forward; development migration bundles and environment records should
not be copied into the template.

## 3. First-release user journey

The browser workbench will support the following sequence:

1. Upload or select a supported document.
2. Describe the information to extract.
3. Generate a proposed schema or define/edit it manually.
4. Run extraction on selected samples.
5. Inspect extracted records alongside their source evidence.
6. Provide feedback and inspect proposed configuration changes.
7. Confirm a new configuration version.
8. Import a labeled dataset, run evaluation, and inspect failures.
9. Review improvement suggestions and explicitly rerun evaluation.
10. Freeze a configuration version and process a document batch.
11. Approve, correct, exclude, or add missing records.
12. Query and export approved results, with evidence and coverage information.

Configuration improvement and business-record review are separate workflows.
Changing an extractor must not silently rewrite old results or prior human
review decisions.

## 4. Agreed first-release boundaries

### Documents and reusable configuration

- Support SEC HTML and UTF-8 plain text through explicit input adapters.
- Import bounded ABCD-format JSON/gzip subsets as dialogue source blocks for the
  second domain; preserve speakers, original turn positions and dataset splits.
  This does not expand the first release into arbitrary JSON ingestion.
- Normalize inputs into document blocks with stable document identifiers,
  block identifiers, and source locations.
- Preserve accessible source snapshots for evidence inspection and recovery.
- Make supported input assumptions and limits explicit. Do not imply that
  one SEC sample proves support for every filing layout.
- Exclude arbitrary URL fetching, automatic ingestion connectors, PDF,
  DOCX, images, and OCR from the first release.

Each extraction uses one bounded, flat business-record schema. Supported field
types include text, numbers, booleans, enums, and nullable fields, with explicit
formats for dates. A document may produce zero or more records.

The framework owns fixed provenance, configuration-version, execution, and
review metadata. Business fields, descriptions, and extraction rules are
configurable. Unsupported schema constructs must fail explicitly rather than
being silently simplified.

Arbitrary nested schemas, multi-table relationships, and unconstrained schema
adaptation are outside the first release.

### Schema generation, feedback, and versions

The model may propose:

- A schema draft from a natural-language extraction goal.
- Changes to field descriptions or extraction rules based on selected samples.
- Improvements associated with diagnosed evaluation failures.

The operator must see and confirm proposed changes before they become a new
configuration version. Trial runs and evaluations are explicit actions.

Keep prior configurations, executions, and review decisions available.
Comparing or restoring a configuration must not overwrite historical records.
The first release will not perform unbounded background tuning or automatically
replace the active configuration after feedback.

Model deployment settings should be configurable, but compatibility claims
must be limited to configurations actually verified for the template.

### Records, evidence, and aggregation

The core output is a source-document record, not an automatically resolved
cross-document entity or event.

- Prevent duplicate writes when the same operation is repeated.
- Use explicit identifiers and deterministic rules for cross-document grouping.
- For example, count customers using a supplied customer identifier and a
  defined blocker category, rather than asking the model to infer identity.
- Without reliable event identifiers, report mentions or records rather than
  claiming to count unique real-world events.
- Do not perform automatic semantic entity resolution or event merging.

Source-location validation is necessary but does not prove that a claim is
semantically supported by the cited text. Candidate records must remain
distinguishable from human-approved records.

Default queries and aggregations must use approved records only. Candidate
previews and exports must be explicitly labeled. Show processing coverage and
review coverage; a zero-candidate document is not automatically a reviewed
document with no relevant facts.

The minimum review workflow includes approval, correction, exclusion, and
addition of missed records. Review state must be durable.

### Evaluation and quality reporting

Support import of explicitly labeled evaluation data and include small labeled
datasets for both reference domains. Each input is associated with expected
record JSON and the applicable schema version. Validate imported data against
the supported contract.

Define record matching and field comparison rules before scoring:

- Include missing records in the evaluation rather than scoring only matched
  records.
- Report the relevant record/document and field-level outcomes and failures.
- State sample sizes, denominators, and unsupported comparisons.
- Handle free-text fields without an established automatic comparison rule
  separately; do not present unverified model self-scores as accuracy.

Keep development/diagnostic samples separate from held-out reporting samples.
Do not feed the held-out reporting set into the configuration improvement
process and then report the resulting score as independent evidence.

Business review approval does not automatically create complete ground truth.
Converting reviewed records into evaluation data requires an explicit decision
about completeness and intended use.

The first contribution proves the workflow and reuse. It will publish measured
quality and limitations without a numeric precision, recall, or time-savings
release threshold. Structural checks, evidence-location checks, visible
failures, and the approved-record query boundary remain mandatory.

A dedicated annotation platform, calibrated field confidence, and claims of
production-grade extraction accuracy are outside the first release.

## 5. Architecture and deployment direction

### Browser workbench

Extend the existing Streamlit implementation rather than introducing a separate
frontend stack in the first release.

Keep extraction, configuration, evaluation, execution, and review logic outside
page code so the UI can be replaced later. Prefer clear forms, JSON editing,
tables, and readable differences over pixel-level reproduction of the
reference product.

Host the workbench in Azure with Entra sign-in and access restricted to a
designated operator. Server-side access to Foundry and Blob uses managed
identity and appropriate RBAC.

Foundry Playground is an optional testing entry point, not the primary
workbench or a critical-path dependency. A Responses adapter should only be
added if a concrete use case requires it.

### Deterministic cloud execution

Retain a deterministic Foundry-hosted workflow and chunk/attempt-level
checkpoints, with source-block coverage recorded inside each committed chunk.
A single start action should trigger bounded backend progression rather than
requiring the user to issue a command for every block.

Pause when an error occurs or a configured processing limit is reached.
Resume must be explicit and operate from durable state.

The existing implementation can resume committed, handled failures, but an
unknown interruption may leave an unresolved execution claim. Such a job must
remain visibly blocked pending reconciliation; do not promise automatic
recovery or exactly-once model inference.

Do not depend on a conversational model to repeatedly invoke tools until a
batch finishes. Do not assume that a single HTTP request can process an entire
long document. Select and verify the execution mechanism during the
feasibility stage.

Run identifiers and durable backend state, not browser state, Streamlit
reruns, or conversation history, are the source of truth. Repeated requests
must not duplicate writes or blindly repeat completed inference.

### Infrastructure

The first deployment path is Bicep plus Azure Developer CLI (`azd`).
It will provision the required Foundry project/model resources, Blob storage,
and web hosting, including workbench authentication and access configuration.

The target is a freshly provisioned, single-operator developer reference
environment. Authenticated public endpoints are acceptable; anonymous data
access is not.

Select the specific Azure web hosting service and confirm the hosted workflow's
deployment mechanism through a minimal feasibility exercise. Do not assume
every required protocol or deployment setting is already expressible through
the existing azd examples.

Document prerequisites, permissions, configuration, sample setup, costs,
operating limits, validation, and cleanup. Day-to-day use should not require a
local CLI; this does not imply command-free infrastructure provisioning.

Private networking, APIM, multi-user collaboration, multi-tenancy, a second IaC
implementation, and production SLA claims are not first-release commitments.

## 6. Delivery gates

There is no fixed delivery deadline. Progress is gated by observable outcomes,
not a calendar promise. A failed gate should lead to a visible design or scope
adjustment, not a hidden workaround.

### G0: Confirm contribution fit and cloud feasibility

Work:

- Confirm the revised standalone workbench/workflow scope with maintainers.
- Exercise a minimal hosted Streamlit-to-Foundry path with authenticated access.
- Verify bounded backend progression, durable status, and explicit recovery.
- Check refresh and repeated-request behavior on a small existing workflow.

Exit criteria:

- The intended contribution direction is understood and acceptable to pursue.
- A small browser-driven task completes with durable, inspectable state.
- Failures can be surfaced and resumed without duplicate processing.
- No dependency on a full UI rewrite or Playground protocol adaptation is
  introduced merely to complete this feasibility check.

### G1: Establish the reusable core and demonstrate two domains

Work:

- Define normalized document, bounded schema, evidence, configuration-version,
  execution, and review contracts. Frozen schema/profile and field-evidence
  contracts are implemented; general input planning and review remain open.
- Move financial-report-specific assumptions into adapters and sample profiles.
  New configured financial and support jobs use one output validator; a
  separate compatibility adapter retains the already-frozen G0 wire format.
- Implement the SEC HTML and plain-text paths.
- Introduce the ABCD customer-support profile and a small, versioned local
  development/held-out subset. The offline importer, support profile and
  shared fixture execution are available; real provider validation, human
  extraction gold, and approved support queries remain to be implemented.
  Review dataset redistribution
  before bundling upstream dialogue text.

Exit criteria:

- After freezing the core, the second domain can be added through the supported
  adapter/configuration/sample-query surfaces.
- Adding domain-specific branches to the extraction engine means this gate
  has not passed.
- Both domains preserve evidence, run identity, and explicit error states.

### G2: Build interactive configuration and sample improvement

Work:

- Extend Streamlit with schema generation and manual editing.
- Add sample execution and evidence inspection.
- Add feedback-driven proposals, visible differences, version confirmation,
  comparison, and restoration.

Exit criteria:

- An operator completes a goal-to-schema-to-sample-to-revision journey.
- Configuration changes are explicit and versioned.
- Previous executions and review results remain unchanged.

### G3: Demonstrate evaluation through batch application

Work:

- Import labeled examples and present meaningful document/field comparisons.
- Show failed cases and associate improvement proposals with diagnostic data.
- Keep independent reporting data out of the improvement loop.
- Run a batch against a fixed configuration version.
- Connect candidate preview, record review, coverage, approved-record queries,
  and exports.

Exit criteria:

- Both reference domains complete the end-to-end workbench journey.
- Evaluation rules and limitations are visible and reproducible.
- Unsupported claims are not promoted merely because JSON and citations pass
  structural checks.
- Default downstream results come only from approved records and trace back
  to their sources.
- Repeated requests, interruption, and recovery preserve state and completed
  work.

### G4: Package an independently adoptable contribution

Work:

- Complete Bicep/azd provisioning, identity setup, and sample initialization.
- Include cloud workbench hosting and designated-operator access.
- Provide operating, cost, limitation, validation, and cleanup guidance.
- Curate only the necessary source, samples, and documentation for the target
  repository.

Exit criteria:

- A clean environment can deploy and complete both sample journeys.
- The template does not rely on a developer's private environment state,
  migration bundles, credentials, or undistributable data.
- Required resources and cleanup behavior are explicit.
- Maintainer scope expectations have been addressed before preparing the
  upstream pull request.

## 7. Post-first-release roadmap

Evaluate these capabilities after the bounded first contribution:

- Additional file types, PDF/image processing, OCR, and ingestion adapters.
- Scheduled and incremental processing.
- Richer external APIs and integrations.
- Budget-bounded automatic search across candidate configurations.
- Validated field confidence and explicitly measured precision/cost modes.

Each capability needs its own acceptance criteria and cost/operational
assessment. None should be represented as already implemented or as providing
quality parity with the reference product.

The contribution's value is an independently deployable Foundry reference for
the document-structuring lifecycle, not a claim to reproduce the full
Databricks platform.
