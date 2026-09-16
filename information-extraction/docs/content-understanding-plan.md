# Content Understanding: agreed direction and validation gate

**Agreed September 16, 2026. Status: planning only.** The user approved recording
this plan, not implementation, deployment, or a paid experiment. No CU analyzer,
model deployment, analysis result, or quality measurement is claimed here.
The [configured workbench](configured-workbench.md) still uses its existing
Responses implementation. Its [synthetic pilot](configured-workbench-pilot.md)
is historical integration evidence, not evidence for adopting CU.

## 1. Product decisions

| Decision | Agreed answer |
| --- | --- |
| Contribution's primary value | A configurable, cross-domain workflow: configuration, execution, original evidence, human review and approved export. A proprietary extraction engine or provider neutrality is not the goal. |
| CU's intended role | Preferred parsing/extraction foundation if it passes the validation gate, not merely an OCR utility. Keep the existing Responses path as a comparison baseline; do not delete it or switch defaults now. |
| Initial inputs | Financial HTML/text and ABCD support conversations. Do not add PDF, images, OCR, audio or video in this increment. |
| Evidence | Trace accepted fields to original material. CU Markdown is a separately retained derived representation, not the evidence endpoint. Confidence does not establish correctness or approval. |
| Adoption evidence | Approximately ten real-source cases, about five per domain, with human-confirmed expected records and evidence. A successful synthetic demonstration is insufficient. |
| Default-switch gate | Correct original evidence and existing missing-value/cardinality constraints are mandatory; record and field performance must not be worse than the baseline, assessed separately by domain. Record latency/cost, but modest cost differences are not an adoption blocker. |
| Immediate action | Record the English plan only. A subsequent execution request must precede code changes, provisioning or paid analysis. |

The resulting decision tree is:

```text
Service-first, cross-domain workflow
  -> CU capability fit
     -> Original evidence can be verified
        -> Financial HTML/text + ABCD comparison
           -> Hard gates and baseline comparison pass
              -> Propose controlled integration and a default switch
           -> Fail or inconclusive
              -> Keep current default; preserve diagnostics and identify gaps
     -> Original evidence cannot be verified
        -> Do not relax provenance requirements to force adoption
```

## 2. What CU can supply

The following are documented capabilities, not observations against the user's
Azure resource. The baseline is GA API **2025-11-01**; do not require preview
agentic reasoning, synchronous APIs, or labeled training for this increment.
Current preview behavior is not assumed to apply to GA. [1]

| Capability | Relevance and qualification |
| --- | --- |
| TXT, HTML and JSON inputs | Useful for both selected domains. JSON-file support is not an ABCD conversation interface or a guarantee of turn-aware citations. HTML support is not SEC retrieval, Inline XBRL interpretation or hidden-node filtering. [2] |
| Custom analyzer fields | Scalar types, enum, object/array fields and descriptions can express the business profiles. CU is not arbitrary JSON Schema; missing-value serialization and zero/multiple-record behavior must be tested, not assumed equivalent. [3] |
| Field grounding/confidence | Current documentation covers document extract, generate and classify methods. Availability for the chosen text input/analyzer combination needs verification; confidence is a signal, not a correctness certificate. [2][4] |
| Schema proposals and examples | Potential later help for profile creation/improvement. The application still owns confirmation, freezing, comparisons and human approval. Do not add training or feed evaluation answers into this first experiment. [5] |
| Python and Entra integration | Official Python SDK and managed-identity/RBAC support exist. Resource region, permissions and model availability must be checked before use. A CU Reader role can analyze; its name does not imply non-billable access. [6][7] |

Generative CU requires supported connected Foundry models. DeepSeek was not in
the reviewed supported list, so reuse of the current deployment is **unverified**.
Parsing-only `prebuilt-read`, `prebuilt-layout` and `prebuilt-digitalParse` need
no language/embedding model; requirements for a generative analyzer and optional
sample features are different. Resolve actual model requirements rather than
provisioning unnecessary deployments. [5][8]

## 3. Preserve the useful application responsibilities

Retain profile editing, immutable sources/configurations, historical jobs,
explicit authorization, durable execution and Pending results. Human review,
corrections and approved-only export remain application work; CU does not
complete those product gaps.

The existing `ModelProvider`/`Model.complete` seam is not evidence of a drop-in
integration. `configured_inputs.prepare_plan` currently constructs frozen
text/dialogue blocks locally without a paid call. The generic output validator
resolves field references against those blocks. CU instead analyzes content
asynchronously and produces its own representation.

An eventual integration must distinguish:

- Original source and selected visible content, frozen before paid work.
- CU analyzer definition, API version, schema, explicit model bindings and
  analysis options, retained rather than inferred from mutable defaults.
- Submission intent, operation identity and authorization accounting.
- Persisted CU result/Markdown and a versioned mapping to original sources.
- Validated candidate records, separate diagnostics and later human decisions.

Do not hide a billed CU parsing request inside **Create job (no model call)**.
A changed provider/schema/mapping must not rewrite historical plans, receipts
or evidence. Do not redesign the workbench before the independent validation
establishes a useful fit.

### Evidence is the critical compatibility test

CU `ContentSpan` offsets index **CU-produced Markdown**, not original bytes,
HTML nodes or ABCD turns. Choosing UTF-8 span indexing does not change that
provenance distinction. [9]

For financial HTML, retain the original fragment/file and a reproducible mapping
from the selected visible content to the source. Do not present transformed
Markdown as verbatim original HTML. For text, preserve original text/line
locations. For ABCD, keep the current customer/agent-only importer, original
turn indices and speakers; never submit hidden scenarios, action events, task
labels or delexed content merely because JSON input is supported.

Mapping must account for repeated quotations, normalization and speaker context.
Do not select the first matching substring and call it verified provenance.
Unmappable output may be retained as a diagnostic artifact but cannot count as
a valid original-evidence candidate or a passing result. All published candidates
remain Pending; neither a source span nor confidence can automatically approve
them.

### Remote operations and cost admission

GA analysis returns 202 and `Operation-Location`, followed by result polling.
Persist that identity and poll the known operation instead of resubmitting.
CU results are retained for up to 24 hours, so retain completed results in
application storage. [10][11]

The reviewed contract does not establish a billable-execution idempotency key,
recovery solely by client request ID, or guaranteed cancellation of running
analysis. A timeout, client cancellation or result deletion must not be treated
as proof that server work or billing stopped. An ambiguous submission requires
reconciliation or explicit authorization, not a blind POST retry. [10]

One CU analysis may cause multiple underlying model calls. Count analysis
submissions, retries, reported pages/contextualization and reported model usage
separately. Existing model-call slots cannot be advertised as an equivalent
limit on underlying CU model calls or a hard monetary cap. Missing usage remains
unknown, not zero. Known-operation polling is not a new analysis authorization.

## 4. Independent comparison before integration

This is a small engineering adoption check, not a statistically representative
accuracy benchmark or proof of production readiness.

1. **Prepare and freeze the cases.** Select approximately five financial
   HTML/text fragments and five real ABCD conversations. Keep hashes, source
   identifiers, selected sections/turns, split and transformation versions.
   Follow existing licensing/provenance guidance; do not bundle upstream
   dialogue text by default. Keep local corpus artifacts outside source control.
2. **Confirm the expected answers before execution.** Record gold record counts,
   field values/nulls and original evidence. Agent-proposed labels require human
   confirmation; do not silently describe them as adjudicated human gold.
3. **Cover failure-prone behavior.** Include missing facts, no-record and
   multiple-record cases, suggestions versus attempted actions, and recorded
   requests versus completed resolutions. Preserve the existing schema rules:
   required values cannot be invented, nullable unknowns remain null with no
   evidence, and unsupported fields/cardinality do not pass by coercion.
4. **Make the comparison fair.** Freeze both configurations. Use identical
   selected visible content and business schemas. Derive the baseline's text
   from original material, not CU output. Assess HTML parsing/source mapping
   separately and record representation differences; do not conflate improved
   parsing with an isolated model-quality claim.
5. **Authorize a bounded run separately.** First verify the chosen resource,
   supported model/deployment, permissions and prices. Specify maximum new
   analysis submissions, baseline requests and input size/page bounds.
   Additional parsing probes or retries must be visible in the allowance.
   This document does not grant those calls.
6. **Persist and compare all outcomes.** Include rejected, failed and unmappable
   cases in the report rather than reporting only successes. Report record
   precision/recall, field correctness, evidence correctness, null/cardinality
   failures and their counts/denominators separately by domain, alongside
   latency and known/unknown cost components.

**The switch is blocked** if any accepted field has incorrect original-source
grounding, the schema/critical semantic cases fail, or CU performs worse on the
agreed record/field measures in either domain. Do not average away one domain's
regression. Unmappable/dropped output cannot disappear from recall/error
accounting to manufacture a pass. Inconclusive results do not authorize a switch.

Do not send gold answers as examples or training data. If prompts are adjusted
using these results, use fresh cases for independent revalidation and disclose
the earlier set's development role. Keep the Responses baseline available until
the gate passes and a subsequent integration/default change is authorized.

## 5. Approximate cost, not an experiment authorization

Official pricing-page HTML checked on September 16 exposed these East US 2 USD
estimates. Actual subscription pricing, selected processing path and connected
model usage may differ. [12][13]

| CU meter | Listed estimate |
| --- | --- |
| Asynchronous Document Minimal | $0.01 per 1,000 pages |
| Asynchronous Document Basic | $1 per 1,000 pages |
| Asynchronous Document Standard | $5 per 1,000 pages |
| Standard contextualization | $1 per million contextualization tokens |

The pricing explanation assigns 1,000 contextualization tokens per document
page. For **100 billable page-equivalents**, Minimal extraction plus standard
contextualization would be approximately **$0.101**; the Standard extraction
path plus standard contextualization would be approximately **$0.60**.
Both exclude connected completion/embedding model charges, storage and other
infrastructure. These examples are not a quote for the ten-case experiment.

TXT/HTML use documented character-based page equivalents (3,000 characters,
rounded up); JSON metering should be confirmed for the selected representation
rather than assumed identical. No recurring CU free allowance was verified.
Failed analysis can still involve billed successful underlying model calls.
Do not compare these service meters directly with the previous $0.00104
successful DeepSeek synthetic usage as if workloads and capabilities matched.

## Sources

[1]: https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/whats-new
[2]: https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/service-limits
[3]: https://learn.microsoft.com/en-us/rest/api/contentunderstanding/content-analyzers/create-or-replace?view=rest-contentunderstanding-2025-11-01#contentfielddefinition
[4]: https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/document/analyzer-improvement
[5]: https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/concepts/prebuilt-analyzers
[6]: https://learn.microsoft.com/en-us/python/api/overview/azure/ai-contentunderstanding-readme?view=azure-python
[7]: https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/concepts/secure-communications
[8]: https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/concepts/models-deployments
[9]: https://learn.microsoft.com/en-us/rest/api/contentunderstanding/content-analyzers/analyze?view=rest-contentunderstanding-2025-11-01#contentspan
[10]: https://learn.microsoft.com/en-us/rest/api/contentunderstanding/content-analyzers/analyze?view=rest-contentunderstanding-2025-11-01
[11]: https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/content-understanding/data-privacy#data-retention
[12]: https://azure.microsoft.com/en-us/pricing/details/content-understanding/
[13]: https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/pricing-explainer
