# Native data preparation: is another POC justified?

**Checked September 17, 2026. Public-source research, not an executed benchmark.**
This extends the [accelerator comparison](unified-data-foundation-comparison.md).
The [confirmed journey](agent-user-journey.md) and implementation plan are not
changed by this recommendation. No resources, model calls or jobs were started.

## Decision

**Do not start another general extraction accelerator yet.** Compare native
Fabric preparation and native CU authoring/improvement before implementing the
proposed preparation module. The earlier distinction between an accelerator's
querying Agent and a preparation Agent remains valid for that inspected
repository, but it understates what the wider Fabric/CU products already offer.

Fabric documents goal-guided schema inference, business-field extraction,
Notebook-assisted preparation and evaluation/refinement examples. CU Studio
documents schema suggestions, human corrections and labeled improvement.
These substantially overlap with the proposed goal-to-schema-to-iteration
experience. Original evidence, independent acceptance and controlled publication
may still matter, but their importance does not establish demand for a new
platform rather than a small recipe or extension.

No conclusion here relies on inaccessible internal material or an internal
product roadmap. Workplace-document retrieval was not completed.

## 1. Fabric already prepares unstructured data

| Proposed capability | Verified native alternative | Important qualification |
| --- | --- | --- |
| Business-field extraction from text rows | `ai.extract` supports described fields, schema-driven types, arrays/objects, required fields, enums and nullability. [F1] | This is not merely CSV type inference. Output/cardinality must be explicitly normalized and checked. |
| Goal-guided schema proposal | `ai.infer_schema` takes a guiding prompt and selected file paths, samples inputs and returns editable labels usable by extraction. `aifunc.load` can return extracted data and a reusable schema. [F2] | Sampling must be explicitly bounded; proposal is not automatic business approval. |
| Existing Lakehouse inputs | Text-column extraction and file paths, including attached Lakehouse Files and ABFS, are documented. [F1][F2] | TXT is supported; original-HTML fidelity and exact dialogue-turn alignment remain untested. File-mode limit is 50 MB. |
| Notebook authoring and error diagnosis | Copilot generates/refactors code across cells, profiles tables and diagnoses Spark errors; the walkthrough runs generated cells after approval. [F3] | Not read-only, and not equivalent to the proposed fixed preparation-tool allowlist. |
| Visual transformation review | Data Wrangler previews transformations and exports pandas/PySpark code; AI enrichment has preview/apply interactions. [F4] | Transformation review is not independent extraction acceptance. |
| Evaluation/refinement | An official extraction evaluation notebook scores consistency/coverage with an LLM judge and compares richer-label refinements. [F5] | Judge scores are proxies, not human gold. Refinement can change fields/types/cardinality; it does not enforce the proposed frozen-structure contract. |
| Errors, explanation and usage | `error_col`, optional raw output and `ai.stats` expose row errors, model output and usage. [F1][F6] | Model explanations or extraction text are not guaranteed original-source coordinates. |
| Browser-independent work | Fabric Notebook jobs and Pipeline Notebook activity provide existing execution foundations. [F7] | Not proof of exactly-once paid inference, durable local cache or valid unattended AI-endpoint authentication. |

The AI Functions configuration documentation describes a Fabric-hosted default
model and configurable compatible model endpoints. **These functions are LLM
calls, not documented CU analyzer calls. CU is not a mandatory dependency for
the first native text-extraction baseline.** Custom models need compatible
structured responses; file processing has additional Responses API requirements.
[F8]

Native classification and summarization can also cover several support-dialogue
outputs. Explicitly select the intended text column rather than implicitly
sending unrelated columns. [F9]

### Availability and integration limits

The central release-state table lists **AI Functions and Notebook Copilot as
Preview**; Data Factory Copilot query/pipeline generation and troubleshooting
are listed GA. Do not infer release status from a missing banner on an individual
page. [F10]

AI Functions prerequisites include a paid F2+ or P capacity, tenant enablement
and a supported runtime (Runtime 1.3+ in the inspected guidance). Regional/
cross-geo settings also matter. The previously observed F4 is only a capacity
prerequisite, not evidence that these features are enabled or usable by the
selected operator/job identity. [F6][F11]

Notebook job service-principal support does not automatically establish support
for every built-in AI endpoint under that identity. The selected unattended
route, actual HTML handling and recomputation/billing behavior remain untested.
Do not rely on cache as a persistent no-resubmission contract.

## 2. CU already authors and improves extractors

| Proposed capability | Verified native alternative | Important qualification |
| --- | --- | --- |
| Sample-driven schema suggestion | CU Studio classifies samples, recommends templates and can suggest a full schema for human review/editing. [C1] | A second schema-proposal UI is not new extraction capability. |
| Human trials and correction | Author fields, analyze additional samples, inspect results, correct auto-label predictions and rebuild. [C1][C2] | Auto-label predictions are not independently confirmed gold. |
| Automatic improvement | GA and preview support labeled-document training. Preview distills relevant patterns/domain context into the built analyzer. [C2] | A description-only optimizer must compete with this, not only with an untuned zero-shot analyzer. |
| Confidence and grounding | Native document fields have confidence and source grounding. [C2] | Confidence is not observed accuracy; derived spans do not establish original HTML offsets or ABCD turn IDs. |
| Analyzer lifecycle | Analyzer copying supports backup and iteration versions; preview exposes versioned workflow families. [C3][C4] | Do not claim CU has no versioning. This does not by itself make experiment records or published datasets immutable. |
| Quantitative gold evaluation | Guidance calls for evaluation before/after training. [C2] | Native Studio metric dashboards, split management and independently protected held-out acceptance were not verified; do not declare them absent. |

**Production-oriented baseline:** evaluate GA `2025-11-01`. Consider
`2026-06-01-preview` separately if preview use is acceptable. CU Studio, not
only the new Foundry playground, is the relevant native authoring/labeling
baseline. [C5]

Labeled training is documented for **document analyzers only** and currently
excludes **`generate` fields**. Training also does not repair OCR errors.
HTML/TXT appear in supported document/text inputs, but exact Studio upload and
labeled-training parity for each representation were not demonstrated. [C2][C6]

Preview labeled improvement reduces dependence on runtime training documents
and may reduce tokens, but resolves to an advanced contextualization workflow.
**Fewer tokens do not establish lower total cost or higher accuracy.**
Native preview `workflow: "agentic"` is document reasoning, not proof of
external preparation-grant or publication governance. [C2][C4]

## 3. Revised build/reuse assessment

| Earlier proposed work | Revised recommendation |
| --- | --- |
| New goal-to-schema implementation | First test native `ai.infer_schema` and CU Studio suggestions. Build only missing interaction/validation justified by users. |
| New general text-extraction adapter stack | First test native `ai.extract`; compare CU for tasks requiring its extraction/grounding/improvement behavior. |
| Description-only autonomous tuning | Do not make this the centerpiece before comparison with native labeled CU improvement and Fabric refinement examples. |
| Notebook authoring/debugging assistant | Reuse Notebook Copilot where permitted; document any fixed-tool requirements it does not meet. |
| New execution engine | Reuse managed execution foundations. Add only domain-specific grants, persisted operation reconciliation and state if the chosen workflow needs them. |
| New chat/search/ontology experience | Reuse existing accelerators/native tools; exclude from this POC. |
| Human-gold/original-evidence acceptance and release traceability | Potential thin companion, but first establish repeated user friction that ordinary Notebook code cannot adequately solve. |

The platform's preview status may influence adoption. It is not, by itself,
evidence that a custom wrapper is production-ready or cheaper to maintain.
Likewise, a Foundry Agent requirement chosen to fit a repository is not user
value; the Agent should remain only if it improves the measured task.

## 4. A smaller decision experiment

**Recommendation only; not executed or newly authorized.** Before building a
module, use the existing scenario definitions and a bounded subset to compare
native workflows. Retain both financial and ABCD cases before any broader
adoption conclusion; a first financial smoke does not replace the two-domain gate.

| Candidate | What it tests |
| --- | --- |
| Fabric-native Notebook | Guided schema inference, human schema confirmation, `ai.extract`, row errors and materialized candidate output. |
| CU Studio / GA | Native schema suggestions, human editing and labeled improvement where the field methods are trainable. |
| CU preview, optional | Whether native distilled improvement adds useful quality/effort benefits at its actual total cost and accepted preview risk. |
| Custom Agent, conditional | Only after a baseline exposes a specific unresolved task; give it the same development information and comparable workload limits. |

Freeze business fields, record cardinality, null rules and scoring before
comparison. Separate development and human-confirmed acceptance material
before tuning. Native schema proposals/refinements that alter structure must
be reviewed and aligned before scoring; do not compare different objectives.
For `generate` fields excluded from native training, label the comparison
accordingly rather than pretending all candidates have identical capabilities.

Measure active human preparation/review time, held-out field/record/evidence
correctness, omissions/failures, latency and known/unknown total usage cost.
Retain the original source and materialized results; repeated lazy evaluations
or model-backed displays must not be mistaken for free reads.

First try a small persisted review table and source-evidence checks around
native output, not a complete approval/release platform. The acceptance-data
path must stay outside tuning access. Include ambiguous repeated passages,
unsupported values and missing facts; keep quality/evidence failures visible.

**Stop:** native workflows meet agreed quality and users report no material
preparation/review problem. Deliver a recipe or upstream improvement.
**Continue narrowly:** repeated evidence shows a specific unmet task, and a
small companion measurably improves it without worse quality or unacceptable
cost/operational complexity. Agree thresholds and representative users before
claiming success; this research does not invent an improvement percentage.

## Sources and evidence limits

Public first-party documentation and samples only, accessed September 17, 2026.
Fabric sample implementation is pinned to `618b765245eee371003d0aa011a3d921f45b6d24`.
No live functional, quality, cost, permission or scalability validation occurred.
Absence/uncertainty statements are limited to inspected sources.

[F1]: https://learn.microsoft.com/en-us/fabric/data-science/ai-functions/pyspark/extract
[F2]: https://learn.microsoft.com/en-us/fabric/data-science/ai-functions/multimodal-overview#aiinfer_schema-infer-schema-from-files
[F3]: https://learn.microsoft.com/en-us/fabric/data-engineering/copilot-notebooks-chat-pane
[F4]: https://learn.microsoft.com/en-us/fabric/data-science/data-wrangler-ai
[F5]: https://github.com/microsoft/fabric-samples/blob/618b765245eee371003d0aa011a3d921f45b6d24/docs-samples/data-science/ai-functions/eval-notebooks/AIFunctions-PySpark-eval-extract.ipynb#L384-L435
[F6]: https://learn.microsoft.com/en-us/fabric/data-science/ai-functions/overview
[F7]: https://learn.microsoft.com/en-us/fabric/data-factory/notebook-activity
[F8]: https://learn.microsoft.com/en-us/fabric/data-science/ai-functions/pyspark/configuration
[F9]: https://learn.microsoft.com/en-us/fabric/data-science/ai-functions/pyspark/summarize
[F10]: https://learn.microsoft.com/en-us/fabric/fundamentals/copilot-ai-feature-state
[F11]: https://learn.microsoft.com/en-us/fabric/fundamentals/copilot-fabric-overview#available-regions
[C1]: https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/how-to/customize-analyzer-content-understanding-studio
[C2]: https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/document/analyzer-improvement
[C3]: https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/how-to/copy-analyzers
[C4]: https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/concepts/analyzer-reference
[C5]: https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/foundry-vs-content-understanding-studio
[C6]: https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/service-limits
