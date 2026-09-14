# Information Extraction Solution Template: Implementation Plan

## Status and purpose

This plan records the scope agreed on September 14, 2026. It is a planning
artifact, not a claim that all capabilities described below already exist.
A preliminary [offline execution core](../README.md) is now implemented;
the cloud workflow, workbench, and complete G0 gate remain outstanding.

Execution planning is detailed in the [minimal migration inventory](migration-inventory.md)
and [G0 technical validation plan](g0-validation-plan.md). These documents
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
A small synthetic customer-meeting-note sample will demonstrate reuse by
extracting evidence-supported adoption blockers.

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
  execution, and review contracts.
- Move financial-report-specific assumptions into adapters and sample profiles.
- Implement the SEC HTML and plain-text paths.
- Introduce the synthetic customer-meeting-note sample.

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
