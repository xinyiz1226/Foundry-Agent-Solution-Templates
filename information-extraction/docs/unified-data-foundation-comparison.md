# Unified Data Foundation accelerator comparison

**Checked September 17, 2026.** Public `main` of
`microsoft/agentic-applications-for-unified-data-foundation-solution-accelerator`
was inspected at commit **`995d3007baae798e2a60f94e4dd8502b5b82dfa6`**
(September 16, 2026, 09:49:13 UTC).

This is an advisory comparison with our
[confirmed preparation journey](agent-user-journey.md), not approval to deploy
either solution or a change to the [active plan](implementation-plan.md).
Our Agent/CU/Fabric integration remains planned, not implemented.

## Verdict

**Substantial infrastructure overlap, but a different primary workflow.**
The accelerator implements data loading, Fabric Notebook execution, Delta
tables, ontology construction, Foundry agents and document retrieval. It is
more than an architecture diagram. Its principal agent experience is answering
questions over loaded structured data and indexed documents. [1][2][3][4]

Our proposed experience is developing an extractor and producing a
quality-assessed, explicitly approved, traceable dataset. CU extraction,
goal-driven extraction-schema proposals, constrained development tuning,
isolated acceptance and governed dataset releases were **not found in the
inspected remote preparation path**. This is a bounded finding, not a claim
that the platform cannot support them.

Merely combining Foundry, Fabric, unstructured data and a configurable schema
would not sufficiently differentiate another standalone accelerator.

## Comparison

| Area | Inspected implementation | Our confirmed plan / implication |
| --- | --- | --- |
| Starting data | Local CSV tables and PDF references; reuse or create a Lakehouse. [2][5] | Existing Lakehouse HTML/TXT Files or stable-ID/text Table rows. Different scope, not technical novelty by itself. |
| Structured preparation | Upload CSVs, generate/run Spark Notebook, infer schema and overwrite Delta tables. [2] | Genuine overlap in materialization; reuse suitable patterns rather than rebuilding connectivity. |
| Unstructured preparation | Extract PDF text with `pypdf`, create page chunks, embed and index in AI Search. [5] | Retrieval preparation, not CU business-field extraction into candidate Tables. |
| Schema/semantics | CSV type/key/relationship heuristics and ontology properties/relationships. [3][6] | Not the same as proposing an extraction schema from a goal and unstructured samples, then freezing structure/scoring. |
| Agent responsibilities | Real Foundry prompt agents with Fabric and Search/KB tools answer questions. [4][7] | Our Agent chooses bounded preparation actions and description-only development revisions. |
| User entry and repetition | Chat application and provisioning/build scripts, including Notebook execution. [2][8] | Notebook-first review/authoring and explicitly scheduled Fabric candidate processing were not found in inspected scope. |
| Quality | Interactive test chat and representative response-format checks. [9][10] | Not extraction gold, development-failure optimization or held-out acceptance isolation. |
| Evidence | PDF filename/page/chunk metadata and retrieval citations. [5] | Useful provenance, but not original HTML/text/ABCD-turn coordinates for each extracted field. |
| Durability | Job polling/retries, saved Fabric IDs and conversation history. [11][12] | Not proof of durable grant-bounded iteration, safe ambiguous submissions or replay without repeated paid work. |
| Publication | Delta overwrite and Data Agent draft/published definitions. [2][13] | Publishing agent configuration is not approving/versioning analytical datasets with correction and coverage records. |
| Identity/deployment | Managed identity/OBO patterns and substantial application infrastructure. [14][15] | Reusable examples, not automatic permission or compatibility for our target workloads. |

## What the code establishes

### Data preparation is real, but mostly installation-time loading

`01_create_fabric_items.py` reuses a matching Lakehouse or creates one,
uploads local CSVs to Files, generates a Notebook, and writes inferred Spark
dataframes as Delta tables with overwrite semantics. Ontology code then maps
existing columns into entity properties and relationships. [2][3]

The BYOD helper reads the first 100 CSV rows, infers types, selects keys using
naming heuristics and matches foreign keys by column names. That routine does
not establish key uniqueness or referential integrity. It is schema inference
over already tabular input, not a goal-to-extraction-schema workflow. [6]

AI-assisted sample-question generation and prompts that describe existing
tables are distinct from designing an extractor from unstructured material. [16]
Bronze/silver/gold transformation stages and a user-operated preparation
optimization loop were not found in the inspected build path.

### The Foundry agents primarily consume data

The setup creates `PromptAgentDefinition` instances. Structured questions use
`MicrosoftFabricPreviewTool`; document access uses Search or KB retrieval.
The KB MCP path allowlists `knowledge_base_retrieve` with approval set to
`never`. These are real tool integrations, not evidence of externally enforced
preparation data/config/tool/call/workload/expiry grants. [4][7]

The PDF route uses `pypdf`, embeddings and search indexing. CU analyzer
creation/invocation was not found in that path. Do not equate document RAG
with extraction of typed business records and original-field evidence. [5]

### Existing persistence/publication is not our proposed release contract

Remote Notebook submission and polling are implemented, but the inspected
error/timeout path can submit another run. A path without a Location header
sleeps and reports completion. These semantics should not be copied as proof
of safe operation reconciliation or exactly-once paid work. [11]

Persisting Fabric item IDs or conversation history does not by itself preserve
source/config hashes, candidate evidence, grants, corrections, coverage or
ambiguous extraction outcomes. Data Agent publication copies definition parts;
it is not acceptance and publication of a reviewed dataset release. [12][13]

## What remains worth building

**Already covered elsewhere:** Fabric/Foundry connectivity, Delta loading,
schema metadata, editable configuration, retrieval citations and chat analysis.
Those are reuse opportunities, not persuasive standalone differentiation.

**Mostly product scope and interaction choices:** Notebook-first entry,
existing-Lakehouse-only input, text-only first release and general rather than
industry-led positioning. They may improve usability but do not independently
justify a new execution platform.

**Potential substantive contribution:** externally enforced development grants,
durable bounded preparation, independent acceptance isolation, exact original
evidence, explicit ambiguous outcomes, and correction-aware versioned releases.
These are still unverified planned value, not advantages already delivered.
The small financial/ABCD acceptance sets can illustrate these controls, not
establish general accuracy or enterprise readiness.

## Recommendation

1. **Prefer a small preparation companion before a standalone full stack.**
   Produce reviewed Delta releases that this or other analytical applications
   can consume. Keep independently usable Notebook authoring and reuse existing
   extraction/evidence invariants where they fit. Avoid another generic chat,
   RAG, ontology or dashboard implementation.
2. **Reuse selected code patterns, not the whole deployment by default.**
   Evaluate the Fabric Notebook/Delta and Foundry identity/client wiring.
   Adapt overwrite/retry semantics to the release/reconciliation contracts.
   Do not inherit CSV/PDF staging, automatic Lakehouse creation or the
   application/search stack unless the selected consumer needs them.
3. **Prove the missing workflow before deciding distribution.**
   Demonstrate bounded tuning, held-out isolation, disconnect recovery,
   original evidence and human-controlled releases. If the actual need instead
   becomes Q&A over prepared enterprise data, extend this accelerator rather
   than build a competing template.

Maintainer alignment and whether this should be an upstream extension,
an optional companion or a separate template remain open decisions.
No existing plan, resource or running application was changed by this comparison.

## Evidence scope and uncertainty

Read-only first-party GitHub investigation covered README/architecture docs,
build steps 00-06, schema utilities, ontology/data-agent creation, Python/.NET
execution, credentials/history, infrastructure and representative tests.
No clone, cloud/resource operations or remote tests were performed.
Authenticated GitHub reads encountered SAML enforcement; public reads succeeded.

Architecture documentation emphasizes Fabric SQL Database, while the inspected
current ingestion code materializes Lakehouse Delta tables. Prefer the pinned
implementation when describing what ships. [1][2]
Absence statements mean **not found in inspected scope**, not universal absence
or platform impossibility. Earlier CU/Fabric and Content Processing repositories
were not broadly re-investigated for this comparison.

## Primary sources

[1]: https://github.com/microsoft/agentic-applications-for-unified-data-foundation-solution-accelerator/blob/995d3007baae798e2a60f94e4dd8502b5b82dfa6/documents/TechnicalArchitecture.md#L25-L48
[2]: https://github.com/microsoft/agentic-applications-for-unified-data-foundation-solution-accelerator/blob/995d3007baae798e2a60f94e4dd8502b5b82dfa6/infra/scripts/post-provision/01_create_fabric_items.py#L461-L563
[3]: https://github.com/microsoft/agentic-applications-for-unified-data-foundation-solution-accelerator/blob/995d3007baae798e2a60f94e4dd8502b5b82dfa6/infra/scripts/post-provision/01_create_fabric_items.py#L750-L809
[4]: https://github.com/microsoft/agentic-applications-for-unified-data-foundation-solution-accelerator/blob/995d3007baae798e2a60f94e4dd8502b5b82dfa6/infra/scripts/post-provision/04_create_agent.py#L493-L570
[5]: https://github.com/microsoft/agentic-applications-for-unified-data-foundation-solution-accelerator/blob/995d3007baae798e2a60f94e4dd8502b5b82dfa6/infra/scripts/post-provision/03_upload_to_search.py#L464-L523
[6]: https://github.com/microsoft/agentic-applications-for-unified-data-foundation-solution-accelerator/blob/995d3007baae798e2a60f94e4dd8502b5b82dfa6/infra/scripts/post-provision/data_config_utils.py#L83-L158
[7]: https://github.com/microsoft/agentic-applications-for-unified-data-foundation-solution-accelerator/blob/995d3007baae798e2a60f94e4dd8502b5b82dfa6/infra/scripts/post-provision/04_create_agent.py#L754-L787
[8]: https://github.com/microsoft/agentic-applications-for-unified-data-foundation-solution-accelerator/blob/995d3007baae798e2a60f94e4dd8502b5b82dfa6/infra/scripts/post-provision/00_build_solution.py#L458-L529
[9]: https://github.com/microsoft/agentic-applications-for-unified-data-foundation-solution-accelerator/blob/995d3007baae798e2a60f94e4dd8502b5b82dfa6/infra/scripts/post-provision/06_test_agent.py#L305-L359
[10]: https://github.com/microsoft/agentic-applications-for-unified-data-foundation-solution-accelerator/blob/995d3007baae798e2a60f94e4dd8502b5b82dfa6/tests/e2e-test/pages/HomePage.py#L118-L160
[11]: https://github.com/microsoft/agentic-applications-for-unified-data-foundation-solution-accelerator/blob/995d3007baae798e2a60f94e4dd8502b5b82dfa6/infra/scripts/post-provision/01_create_fabric_items.py#L655-L693
[12]: https://github.com/microsoft/agentic-applications-for-unified-data-foundation-solution-accelerator/blob/995d3007baae798e2a60f94e4dd8502b5b82dfa6/infra/scripts/post-provision/01_create_fabric_items.py#L1400-L1417
[13]: https://github.com/microsoft/agentic-applications-for-unified-data-foundation-solution-accelerator/blob/995d3007baae798e2a60f94e4dd8502b5b82dfa6/infra/scripts/post-provision/01_create_fabric_items.py#L1345-L1385
[14]: https://github.com/microsoft/agentic-applications-for-unified-data-foundation-solution-accelerator/blob/995d3007baae798e2a60f94e4dd8502b5b82dfa6/src/api/python/auth/azure_credential_utils.py#L13-L48
[15]: https://github.com/microsoft/agentic-applications-for-unified-data-foundation-solution-accelerator/blob/995d3007baae798e2a60f94e4dd8502b5b82dfa6/infra/bicep/main.bicep#L419-L469
[16]: https://github.com/microsoft/agentic-applications-for-unified-data-foundation-solution-accelerator/blob/995d3007baae798e2a60f94e4dd8502b5b82dfa6/infra/scripts/post-provision/data_config_utils.py#L232-L251
