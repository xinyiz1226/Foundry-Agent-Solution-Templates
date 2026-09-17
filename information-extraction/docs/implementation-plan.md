# CU + Fabric: data preparation and analysis accelerator

**Replanned September 17, 2026. Planning only; integration is not implemented.**
This is the active delivery plan. It replaces the architecture and delivery
order in the [September 14-16 plan](implementation-plan-20260916.md), without
erasing its implementation evidence or silently marking its G0-G4 gates done.
The [CU adoption criteria](content-understanding-plan.md) remain applicable.

## 1. Outcome and scope

Build an enterprise-oriented reference solution for **data scientists** who
need to turn unstructured material into quality-assessed, traceable datasets
and use them in analysis. CU + Fabric is the intended foundation, subject to
capability, quality and tenant feasibility checks. The repository is a
distribution channel, not a reason to require a hosted or autonomous agent.

The target journey is:

```text
Select source material and extraction profile
  -> inspect samples and confirm a version
  -> evaluate against human-confirmed expected answers
  -> run bounded batch/incremental extraction with CU
  -> validate, review and publish a versioned Lakehouse dataset
  -> analyze the structured tables using SQL/notebooks
  -> trace an unexpected result to records and original evidence
  -> correct data or revise configuration explicitly, re-evaluate, republish
```

This follows the user journey of
[Agent Bricks Information Extraction](https://learn.microsoft.com/en-us/azure/databricks/agents/agent-bricks/info-extraction),
not its implementation. No Databricks, Unity Catalog, Lakeflow or Genie Code
dependency is introduced. Fabric is an explicit platform dependency, not an
optional export destination in the new direction.

**Recommended first deliverable:** a reproducible dataset release, quality
report and executable analysis notebook/SQL example. A suggested lead example
is support-conversation issue/outcome analysis, with financial HTML/text as a
second-domain reuse check. The user has selected both domains but has **not**
confirmed which should lead or whether a dashboard/report should be the primary
deliverable. Confirm that at R0; do not silently turn the suggestion into scope.

Inputs remain financial HTML/UTF-8 text and bounded ABCD conversations.
PDF, images, OCR, audio/video, arbitrary connectors, automatic entity resolution,
cross-tenant SaaS and autonomous business-system actions remain out of scope.
Fabric folder/pipeline ingestion does not authorize arbitrary URL fetching.

## 2. Reuse before building

Begin with the
[CU + Fabric sample](https://github.com/Azure-Samples/azure-ai-content-understanding-with-fabric)
and
[Content Processing Solution Accelerator](https://github.com/microsoft/content-processing-solution-accelerator).
Pin the revisions and map actual runnable functionality before selecting code
to reuse. See the [source-backed feasibility findings](cu-fabric-research.md).

The pinned Fabric sample uses an older preview API, key/SAS configuration and
overwriting result paths; its copy step depends on notebook completion rather
than success. Reuse requires adapting those semantics, not simply importing
the archive and claiming the enterprise integration is finished.

| Source | Intended reuse | Boundary to verify |
| --- | --- | --- |
| CU + Fabric sample | Notebook/pipeline connection and result ingestion starting point | Files landing in a Lakehouse are not yet typed, validated, versioned analytical tables. Sample authentication is not automatically the target enterprise identity design. |
| Content Processing accelerator | Proven application/deployment patterns, CU processing, operational components and structured-output consumption examples | Do not deploy its entire UI, queue, Cosmos DB and compute stack unless this workload needs them. Avoid duplicating Fabric orchestration or state without a documented reason. |
| Existing POC | Source/profile identity, original-evidence rules, conservative retry semantics, fixtures and validation tests | Port behavior/tests where useful. SQLite, Blob ledger, Streamlit and native resilient tasks are not required target architecture. |
| CU/Fabric native experiences | Analyzer authoring, data processing and consumption where they satisfy the journey | Add minimal missing interfaces; do not recreate Studio or build a parallel data platform. |

Do not claim missing features across the ecosystem merely because a sample
does not demonstrate them. A reuse decision must explain what is reused,
adapted, omitted and newly built, including licenses and attribution.

## 3. What stops, what survives

**Pause new standalone-workbench features**, its configurable cloud rollout,
new provider-neutral abstraction work, and old hosted-agent acceptance probes
that are unrelated to the selected Fabric path. Do not spend time polishing
the local UI to imitate Agent Bricks.

Preserve existing code, frozen plans, attempts, evidence, authorization receipts
and historical documentation. Keep Responses as a bounded comparison baseline.
Do not migrate or delete old state, redeploy the old cloud application, stop
existing processes, or remove Azure resources as a side effect of replanning.
Any eventual decommissioning needs a separate retained-data and cleanup decision.

Previously observed results remain limited: the local real-model pilot used
owned synthetic inputs, produced two financial records and one support record,
all Pending. No CU/Fabric integration, real-corpus benchmark, business approval
workflow or enterprise readiness has been demonstrated.

## 4. Target data and execution contracts

Use logical raw, candidate and published layers; exact tables, schema names and
physical placement are R1 design outputs rather than an invented committed API.

| Layer | Required content and behavior |
| --- | --- |
| Original sources | Stable source identity/hash, licensed source snapshot or controlled reference, source version, selected section/turns and parser version. Restrict access and define retention; immutable history does not imply indefinite retention. |
| Configurations and runs | Frozen business schema, analyzer definition/API/model binding, input selection, run identity, authorization and remote operation identity; visible completed, failed, pending and ambiguous outcomes. |
| CU artifacts and candidates | Retained result/derived Markdown, fields, raw confidence where available, original-source mapping, validation diagnostics and coverage. CU confidence is not accuracy or approval. |
| Review and release | Explicit decisions/corrections, actor and time, immutable links to prior versions, included source/run/configuration identities and publication policy. Business approval is separate from gold annotation. |
| Published dataset | Typed Lakehouse tables, an identified release, source/evidence associations, quality/processing/review coverage and consumer-facing queries that select only approved records. |

The current approved-only consumer boundary remains. Do not substitute automatic
schema checks or a confidence threshold for approval without an explicit policy
change. Zero records, missing results and reviewed no-record documents must be
distinguished; do not make a failed or unreviewed input disappear from coverage.

Original text/HTML/ABCD evidence is a hard gate. CU Markdown spans are derived
coordinates, not original-source positions. For ABCD, exclude scenario, action,
task labels and delexed material before analysis and preserve original speakers
and turn indices. Record counts describe conversations/mentions, not unique
real-world customers without explicit identity data.

Incremental ingestion must distinguish unchanged input from new source or
configuration versions. Replaying a completed operation must not duplicate the
published records or blindly resubmit CU. Persist known CU operation IDs and
resume by polling; ambiguous submission remains visible and requires
reconciliation or explicit authorization. One analysis is not necessarily one
underlying model call.

A release must not become visible half-published across related tables. Select
and test a release manifest/consumer-selection mechanism; do not assume generic
cross-table transactions or exactly-once inference. Define retention of released
data and artifacts so a named release remains reproducible for its promised
retention period. Corrections and schema changes create explicit new versions.

## 5. Delivery sequence and measurable gates

R0-R5 replace the old workbench delivery sequence. They are outcomes, not calendar
promises. No phase is currently complete; this update only establishes the plan.

### R0 - Confirm adoption path and access

Confirm lead scenario, consumer deliverable, expected users, volume/cadence,
data classification and a representative enterprise access/network boundary.
Verify Fabric tenant/capacity/workspace availability, administrator dependencies,
CU region/model quota, identities and approximate costs through authorized checks.
An Azure subscription alone is not evidence of Fabric access.

Pin both official reuse candidates, identify the smallest usable deployment,
and document reuse/adapt/build decisions. Evaluate native Fabric execution first;
select additional compute or the old hosted runtime only for a demonstrated gap.

**Exit:** one agreed scenario-to-output journey, supported resource/identity
matrix, selected runtime/state ownership, cost assumptions and exact deployment
scope ready for approval. If access is unavailable, document the blocker rather
than provision a substitute platform or represent local mocks as Fabric success.

### R1 - Prove one CU-to-table path and original evidence

Adapt the smallest official sample path. Run one bounded case through CU,
persist its operation/result, map original evidence and materialize candidate
Lakehouse tables. Query via a verified Fabric notebook/SQL surface; merely
copying JSON to Files does not pass. Initially keep the output unpublished.

Use a supported table writer, such as Spark; the Lakehouse SQL analytics endpoint
does not write underlying table data. Verify the unattended CU identity path
for the selected execution mode rather than copying the sample's key/SAS setup
or assuming workspace identity is available to arbitrary notebook code.

**Exit:** data and original-source mapping are inspectable; reopen/poll/replay
does not repeat completed paid work or duplicate candidate rows. Errors and
unknown outcomes remain explicit. This proves integration only, not extraction
quality, production scale, or a default switch.

### R2 - Pass the two-domain quality gate

Freeze approximately ten real-source cases, about five per domain, with
human-confirmed gold and comparison rules. Keep the existing
[CU comparison gates](content-understanding-plan.md#4-independent-comparison-before-integration):
original evidence, required/null/zero/multiple-record behavior, semantic
counterexamples and no record/field regression per domain versus Responses.
Use equal visible source content, assess HTML parsing separately and count
failures/missing records in denominators.

**Exit:** a reproducible report with per-domain field/record/evidence results,
sample sizes, latency and known/unknown cost. Any tuning makes those cases
development data; use fresh cases for independent revalidation. Failures or
inconclusive outcomes block default adoption, not merely trigger UI work.
The ten cases do not establish general accuracy or enterprise scale.

### R3 - Publish and demonstrate the analytical feedback loop

Implement minimal explicit approval/correction/exclusion/missed-record handling,
coverage and versioned publication. Provide a reusable SQL/notebook analysis
over released tables. Use a second profile to show configuration-based reuse
without domain branches in the execution engine.

In the suggested support example, inspect products/issues with explicitly
unresolved or pending outcomes and reported attempted actions. Keep unknown
outcomes separate; do not infer causal treatment effectiveness from dialogue
sequences. ABCD is role-play data, not proof of real business impact.

**Exit:** select a release, run the analysis, drill to source evidence, record
a correction or configuration proposal, re-evaluate as applicable and publish
a new release without changing the old one. A dashboard is optional unless
selected at R0; Power BI is not silently added as a licensing requirement.

### R4 - Make incremental operation and enterprise controls verifiable

Automate bounded new/changed-input processing and operational status. Demonstrate
unchanged-input replay, schema-version change, partial batch failure, restart,
quota/rate limiting, ambiguous submission and failed publication. Test at a
representative, explicitly agreed workload beyond the ten quality cases.

Validate least-privilege separation of operators/reviewers/consumers, raw versus
published data access, noninteractive identity, secret handling, audit and
retention, monitoring, cost controls and the selected network boundary. A view
filter alone is not an authorization boundary if consumers can read raw tables.
Verify actual identity support on every hop rather than assuming workspace
identity or service principal works everywhere.

**Exit:** documented positive/negative access checks, recovery evidence,
measured throughput/cost, alerts and owner/runbook; private access where required
by the agreed enterprise profile is tested, not deferred behind an
"enterprise-ready" label. No universal compliance, exactly-once billing or SLA
claim follows from using managed services.

### R5 - Package an independently adoptable accelerator

Package repeatable Azure provisioning and Fabric item deployment/import,
configuration, sample initialization, permissions, expected outputs and runbooks.
Document any tenant-admin or manual steps explicitly. Keep portable artifacts
free of private workspace IDs, credentials and restricted corpus files.

**Exit:** a second operator follows the guide in a clean isolated target, runs
both sample profiles and the chosen analysis, verifies release provenance and
access/recovery boundaries, and understands estimated cost and targeted cleanup.
Resolve upstream contribution/maintenance ownership before filing a PR. Reuse
may justify contributing to an existing accelerator rather than a new template.

## 6. Priority and parallel work

| Priority | Work | Dependency |
| --- | --- | --- |
| First | R0 access/reuse/design decision; source selection and human-gold preparation | User confirmation and platform prerequisites |
| Then | R1 thin vertical integration | R0; separate resource and paid-run approval |
| Adoption decision | R2 quality comparison | R1 plus confirmed gold |
| Usable product | R3 released tables and analytical feedback loop | R2 |
| Enterprise acceptance | R4 operational/security verification | Controls designed from R0; complete against the R3 path |
| Distribution | R5 clean-target adoption | R3/R4 acceptance evidence |

Source licensing, gold preparation, deployment documentation and identity/network
design can proceed in parallel once scope is agreed. A new UI, generic connector
framework, multiple orchestration engines, and broad file-format support are
not critical-path work.

Schema generation and feedback proposals should reuse supported CU experiences
first. Build an extra interface only where it blocks this journey. Full visual
parity with Agent Bricks and automated tuning remain later work.

## 7. Cost and authorization

Budget Fabric capacity/active duration, OneLake storage, CU parsing and
contextualization, connected model usage, and any selected Azure compute/storage/
network/monitoring. Power BI consumption licensing depends on the chosen route.
Verify existing capacity and trial eligibility; do not assume either is available
or that pausing capacity eliminates storage or every other charge.

The previous synthetic DeepSeek cost is not a CU + Fabric project estimate.
R0 must produce both a bounded experiment estimate and a monthly scenario with
SKU, region, active hours, volume and retention assumptions. Minimize engineering
delay rather than minor resource cost, while preserving explicit approval,
identity and historical-state boundaries.

This request authorizes **replanning and documentation only**. It does not
authorize cloning/deploying the entire accelerator, acquiring Fabric capacity,
changing the tenant, making paid calls, migrating old data or deleting resources.
The earlier unconfirmed accelerator-deployment request is not an approved
resource plan for this new direction.
