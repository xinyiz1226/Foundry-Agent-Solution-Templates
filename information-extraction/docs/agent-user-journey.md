# Foundry Agent + CU + Fabric: user journey and example packs

**Confirmed September 17, 2026. Design only.** This is the agreed user journey,
not a guide to features already implemented. No sample corpus, new profile,
Notebook, agent, Pipeline or Lakehouse table was created by this decision.
The [delivery plan](implementation-plan.md) defines implementation gates;
the [CU adoption plan](content-understanding-plan.md) defines the quality gate.

## 1. Product and platform roles

The user is a data scientist preparing reusable structured datasets from
existing Lakehouse material. General data preparation is the main scenario;
financial and support examples demonstrate different inputs and field types,
not two separate industry applications. Notebook/SQL analysis is sufficient;
a dashboard, upload UI and standalone chat workbench are not required.

| Component | Responsibility |
| --- | --- |
| Fabric Notebook | User entry: select data, state a goal, inspect proposals/results, grant bounded work, select a configuration and approve publication. |
| Foundry Agent Service | Inspect authorized samples through tools, propose a schema, interpret development failures, decide which permitted draft changes and trials to attempt, and explain its recommendation. |
| Content Understanding | Parse and extract using the selected analyzer/schema/model configuration. |
| Durable execution and tool layer | Enforce authority outside the model; persist run/grant/draft/tool/remote-operation state; dispatch allowlisted routines, enforce limits, stop and recover. Hosting is not yet selected. |
| Fabric Lakehouse | Original-source associations, retained artifacts, candidate records, evaluation data, approvals and versioned published tables, subject to validated access controls. |
| Fabric Pipeline | Run explicitly enabled repeated/scheduled processing with a frozen configuration; produce candidates, not autonomous publications. |

The Agent has a real decision-making role, not merely a fixed CU call wrapped
in a hosted endpoint. It cannot generate and execute arbitrary Python, Spark
or SQL, change security controls, or approve its own output.

Lakehouse storage is not a claim that data never leaves Fabric. Authorized
sample content is processed by Foundry/CU. Validate disclosure, identity,
region/network paths, telemetry and retention for each service.

## 2. End-to-end journey

### A. Select existing data and describe the goal

An operator separately initializes the example packs and required environment.
During normal use, the user selects:

- **Files:** an authorized Lakehouse directory/file selection containing bounded
  HTML/TXT documents.
- **Tables:** an authorized table, stable source ID and text column, with bounded
  row selection. Preserve the selected content version and any original turn
  mapping; require valid IDs rather than silently using row order.

The initial request defines the allowed sample scope and bounded inspection/
schema-generation work. Goal submission does not authorize extraction across
the entire dataset. Dataset text is untrusted content, not tool instructions.

Example goals:

> Prepare comparable annual revenue and operating-income records from these
> two reports. Extract each report's current fiscal year, not prior-year columns.

> Turn these support conversations into records of the request, named product,
> actions actually attempted and explicitly stated outcome. Leave unstated facts
> unknown and retain the original supporting turns.

### B. Generate, inspect and confirm the schema

Natural-language schema generation is a **first-release requirement**, not a
later enhancement. Reuse suitable CU/model capabilities behind controlled
tools; do not require users to hand-author JSON before experiencing the flow.

The Agent inspects bounded samples and proposes fields, types, definitions,
missing-value rules and extraction instructions. The user can edit and must
confirm the structure. Unsupported constructs fail visibly. Save a configuration
version; a proposed schema is not automatically a production analyzer.

### C. Explore without pretending to have evaluated quality

Users may run small exploratory trials without gold answers. Display candidates
against original evidence, omissions and errors, but do not claim measured
accuracy or allow formal publication through this path.

Machine-proposed labels are drafts. Systematic scored iteration needs
human-confirmed development labels and fixed comparison rules. Independent
acceptance additionally needs separate human-confirmed cases. Reviewed business
records are not automatically complete gold.

### D. Authorize bounded autonomous development iteration

After structure confirmation, the user grants a specific development experiment.
The persisted grant identifies allowed source/sample versions, draft lineage,
tool/routine scope, modifiable descriptions/instructions, comparison rules,
iteration/call/workload limits and expiry. Set actual values before execution;
the discussion's three-round example is not a fixed product default.

The Agent can choose the next permitted action: inspect a development error,
clarify a field description, run a bounded trial, compare versions, or stop.
Each modification creates a draft; keep inputs and scoring rules comparable.

| Agent may do within the grant | Requires a separate human decision |
| --- | --- |
| Read selected development samples and diagnostics | Broaden the source scope or access a different dataset |
| Revise field descriptions and extraction instructions | Add/delete fields or change types, enum values, nullability, business objectives or scoring |
| Invoke fixed extraction, status, validation and development-evaluation routines | Execute generated code, provision resources or change access controls |
| Compare drafts and recommend a candidate | Select a release configuration, trigger unapproved bulk/history processing, enable a schedule or publish |

The tool layer validates every call, not just the first instruction. Fixed
readers validate workspace/item/path/table/column selectors and input sizes;
evaluation routines enforce their configured comparison logic. Tool access must
not expose arbitrary queries or a generic code-execution escape hatch.

### E. Continue independently of the Notebook, then stop visibly

Closing/disconnecting the Notebook does not end already authorized work. A
separate durable execution owner continues only within the saved grant. Reopening
discovers the same run, drafts and results rather than starting another iteration.

Stop initiating work when the configured goal/stop condition is met, no
improvement is found under the configured policy, limits/expiry are reached,
authorization fails, a tool fails, or submission status is ambiguous. Report the
best comparable draft and remaining failures; show field-level tradeoffs instead
of hiding them behind a single aggregate score. If no successful comparison
exists, report that instead of manufacturing a recommendation.

Persist known CU/Fabric operation IDs and poll them. An uncertain submission
is not permission to retry blindly. Stopping local dispatch or reaching expiry
does not guarantee cancellation of accepted remote work or its charges.
One CU analysis may involve several underlying model calls.

### F. Select a candidate and independently validate it

The user chooses a draft. Run independent acceptance through a separate access
path: the tuning Agent/tools cannot read held-out inputs, labels, per-case
failures or diagnostic feedback, or adjust the acceptance rules. Acceptance
results go to the human-controlled review path, not another autonomous tuning
iteration.

Require explicit quality evaluation before formal publication. Retain the
agreed two-domain CU adoption checks, including correct original evidence and
no record/field regression versus a comparable Responses baseline. Confidence,
valid JSON or a completed operation are not substitutes.

If acceptance fails, keep the failure visible. If a human uses those failures
to improve configuration, move those cases into development and obtain fresh
independent acceptance cases. A low score does not authorize lowering a gate.

### G. Process new data and explicitly publish

Once a configuration is accepted, the user authorizes the batch/schedule,
input selection, workload limits and cadence. Pipeline may then produce
candidates from new/changed input using that frozen configuration. It does not
silently adopt a draft, reprocess all history or publish results.

In the Notebook, show errors, processing/review coverage and sample inspection.
Support record corrections, exclusions and additions of missed records with
valid evidence. Permit an explicit **scope-bound batch approval**, recording
actor, time, input/configuration/candidate versions, exclusions and inspection
basis. Batch approval is not a claim that every record was manually inspected.
It cannot bypass invalid structure or missing/incorrect original-source mapping.

Published records remain approved-only. Failed, unreviewed, excluded and
reviewed-no-record inputs remain visible in coverage. Candidate access and
consumer access must be enforced beyond a convenient query filter.

### H. Analyze and return problems to their source

Publish a versioned dataset, quality/coverage report and runnable Notebook/SQL
examples. The user selects a release, analyzes it, and drills from aggregates to
records and original evidence. Distinguish a record correction from an extractor
change and from a change in analytical interpretation.

Corrections or confirmed new configurations create new versions. Re-evaluation
and republication are explicit; historical releases remain reproducible for
their documented retention period. Adding an industry dashboard is not required
to demonstrate this loop.

## 3. Example packs

### Financial: two source files, four target records

Use bounded income-statement HTML excerpts from the issuer's
[FY2024 annual report](https://www.microsoft.com/investor/reports/ar24/) and
[FY2025 annual report](https://www.microsoft.com/investor/reports/ar25/).
Retain company identification, statement title, fiscal-period headers, units,
row labels and the mapping back to the original source. These are issuer-hosted
financial reports, not proof of comprehensive SEC HTML parsing.

| Report's current fiscal year | Period end | Revenue | Operating income | Unit |
| --- | --- | --- | --- | --- |
| 2024 | 2024-06-30 | 245122 | 109433 | USD_millions |
| 2025 | 2025-06-30 | 281724 | 128528 | USD_millions |

These are source-verified demonstration expectations, not observed CU output.
Each report contributes only its current-year revenue and operating income:
four business records in total. Prior-year comparative columns are not
additional observations. A TXT rendering is the same evidence, not an
independent evaluation case.

The agreed new financial schema is `company` (text), `fiscal_year` (integer),
`period_end` (date, YYYY-MM-DD), `metric` (revenue/operating_income), `value`
(number), and `unit` (USD_millions), all supported by source evidence.
Implement it as a new profile/version; preserve the old three-field profile
and its runs. A comparison baseline must use the same new business schema,
not score CU's extra fields against the older incompatible profile.

The example analysis compares the two fiscal years by metric. Compute changes
in Notebook/SQL after extraction; do not ask CU to invent calculated facts,
sum repeated comparative observations or label fiscal years as calendar years.

### Support: twenty dialogue rows

Select twenty distinct conversations from the official ABCD **train** split.
Use [ASAPP Research ABCD](https://github.com/asappresearch/abcd/tree/6b8700ce67c6b37b062dd7a60abc76d7ef832a97),
release `abcd_v1.1.json`, distributed as JSON/gzip. Pin actual source hashes and
selected `convo_id` values after inspection; IDs have not yet been selected.
The upstream three-conversation sample is train-only and insufficient for
this pack plus independent acceptance.

Initialize a Lakehouse table with one selected conversation per row, a stable
ID and visible text, retaining original turn/speaker mappings separately.
Only original customer/agent turns enter the model input. Exclude scenario,
action, delexed content and hidden task labels. One input row can yield zero
or multiple distinct concern records, not necessarily one output row.

Keep the existing five-field support schema:
`customer_issue_or_request`, `product_or_service`, `attempted_action`,
`stated_outcome`, `outcome_status` (resolved/unresolved/pending or null).
Unstated outcomes stay null; suggestions are not completed attempts.
Automatic issue taxonomy, sentiment and customer/entity resolution are not
first-release requirements.

Demonstrate coverage, missing fields and explicitly stated outcome counts with
clear denominators and source drilldown. ABCD contains role-play scenarios:
do not claim real customer trends, unique-customer counts, causal effects of
troubleshooting actions or measured production business value.

### Independent cases and initialization

Prepare approximately five additional financial cases and five ABCD **test**
conversations with human-confirmed expected records and evidence. Preserve
development/acceptance separation and actual case provenance. The two annual
statements do not by themselves provide five independent financial cases.
Select genuine missing-fact, zero/multiple-record and semantic-counterexample
coverage; do not invent case IDs or pretend this coverage has been collected.

Use an operator-authorized initialization procedure, not a new upload UI.
Review report excerpt rights and ABCD distribution/notices before bundling;
ABCD's MIT repository license does not remove attribution requirements.
Keep runtime datasets, credentials and tenant-specific artifacts outside
source control. No corpus was downloaded or initialized by this design task.

## 4. Architecture validation before implementation

Current [Foundry function-calling documentation](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/function-calling)
describes application execution of agent-selected functions. The
[Python Projects SDK](https://learn.microsoft.com/en-us/python/api/overview/azure/ai-projects-readme)
documents agent versions and Responses/Conversations. A persistent conversation
does not execute application functions after the dispatcher stops.

Evaluate Notebook UI + durable worker + prompt agent against Notebook UI +
hosted agent execution. Choose the smallest supported path that meets disconnect,
authorization and recovery requirements. Do not assume hosted execution alone
provides crash recovery; [long-running resilience](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/long-running-agent-resilience)
has its own requirements and preview boundary.

Fabric documents [Notebook APIs](https://learn.microsoft.com/en-us/fabric/data-engineering/notebook-public-api),
[Pipeline APIs](https://learn.microsoft.com/en-us/fabric/data-factory/pipeline-rest-api-capabilities),
and [job submission](https://learn.microsoft.com/en-us/rest/api/fabric/core/job-scheduler/run-on-demand-item-job)
with [job-state retrieval](https://learn.microsoft.com/en-us/rest/api/fabric/core/job-scheduler/get-item-job-instance).
Verify the selected item/job type, parameters, result retrieval, unattended
identity and connection support in the actual target. API documentation contains
workload/version-specific limitations; do not promise a working route solely
from a generic scheduler contract.

[Identity support](https://learn.microsoft.com/en-us/rest/api/fabric/articles/identity-support)
is workload-specific. [OneLake access](https://learn.microsoft.com/en-us/fabric/onelake/onelake-access-api)
uses a different token audience from CU. A Fabric workspace identity is not
interchangeable with an Azure managed identity. Resolve token/resource RBAC,
private networking and retention before granting tools access.

A [Fabric data agent](https://learn.microsoft.com/en-us/fabric/data-science/concept-data-agent)
provides data-query capabilities; it is not by itself evidence of this iteration,
job-control or publication workflow. Do not assume adding that connector
implements the required tools.

Required proofs include both input shapes, actual schema proposals and
agent-selected revisions, denied out-of-scope tools/data/structure changes,
held-out isolation, no blind duplicate submission, Notebook disconnect/reopen,
expired grants and human-only promotion/publication. Current POC smoke results
do not establish any of these new integrated capabilities.
