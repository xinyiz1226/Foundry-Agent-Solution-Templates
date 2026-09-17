# CU + Fabric accelerator: bounded research

**Checked September 17, 2026.** Public first-party source inspection only. No
tenant access, deployment, installation, paid analysis or runtime changes.
These findings inform the [active delivery plan](implementation-plan.md);
they are not evidence of an operational or enterprise-ready deployment.
The subsequent [R0 assessment](r0-resource-feasibility.md) records authorized
live resource/metadata checks, resolution of the Fabric tenant-context mismatch,
the remaining cross-tenant identity/placement decision, selected API/result
contracts and bounded capacity-cost scenarios. The unverified-environment
statements below describe this earlier public-source inspection, not a lack of
subsequent checks.

## Pinned reuse candidates

Both upstream HEADs matched the previously inspected revisions at this check:

| Candidate | Revision | Reuse boundary |
| --- | --- | --- |
| [CU with Fabric](https://github.com/Azure-Samples/azure-ai-content-understanding-with-fabric/tree/effa2c1109fa207183158d7a462a89d815168e07) | `effa2c1109fa207183158d7a462a89d815168e07` | Notebook/pipeline ingestion starting point, not a finished analytical dataset or enterprise identity design. |
| [Content Processing Solution Accelerator](https://github.com/microsoft/content-processing-solution-accelerator/tree/9a3f15e4b1403c0851507a9009bc1d39141c4eab) | `9a3f15e4b1403c0851507a9009bc1d39141c4eab` | Processing, application and infrastructure patterns to reuse selectively, not an automatic requirement to deploy the full stack. |

### Official Fabric sample: adapt rather than deploy unchanged

The [README](https://github.com/Azure-Samples/azure-ai-content-understanding-with-fabric/blob/effa2c1109fa207183158d7a462a89d815168e07/README.md)
and [notebook](https://github.com/Azure-Samples/azure-ai-content-understanding-with-fabric/blob/effa2c1109fa207183158d7a462a89d815168e07/Field%20Extraction%20Template%20Notebook.ipynb)
show Blob input -> CU -> Blob JSON -> Lakehouse Files. SQL/Power BI are suggested
subsequent uses, not shipped analytical tables or applications.

The notebook uses a CU key, Blob SAS, API `2024-12-01-preview`, generated analyzer
UUIDs and overwrites named result blobs. The
[pipeline archive](https://github.com/Azure-Samples/azure-ai-content-understanding-with-fabric/blob/effa2c1109fa207183158d7a462a89d815168e07/Pipeline%20Template.zip)
contains a binary Copy sink with `rootFolder: Files`; its notebook dependency is
`Completed`, not `Succeeded`, and activity retries are zero.

**Implication:** retain the useful flow, but explicitly adapt API compatibility,
analyzer versioning, credentials, immutable artifacts, checkpointing and success/
publication conditions. Do not copy stale or partial outputs merely because
the notebook ended. A wholesale import is not the R1 completion criterion.

### Existing accelerator: useful components, different assumptions

Its [extract handler](https://github.com/microsoft/content-processing-solution-accelerator/blob/9a3f15e4b1403c0851507a9009bc1d39141c4eab/src/ContentProcessor/src/libs/pipeline/handlers/extract_handler.py#L51-L65)
uses CU `prebuilt-layout`; the [mapping stage](https://github.com/microsoft/content-processing-solution-accelerator/blob/9a3f15e4b1403c0851507a9009bc1d39141c4eab/src/ContentProcessor/src/libs/pipeline/handlers/map_handler.py#L66-L73)
uses schema-driven GPT output. It has [step/dead-letter queue primitives](https://github.com/microsoft/content-processing-solution-accelerator/blob/9a3f15e4b1403c0851507a9009bc1d39141c4eab/src/ContentProcessor/src/libs/pipeline/pipeline_queue_helper.py#L20-L36),
[result editing](https://github.com/microsoft/content-processing-solution-accelerator/blob/9a3f15e4b1403c0851507a9009bc1d39141c4eab/src/ContentProcessorWeb/src/Components/JSONEditor/JSONEditor.tsx#L100-L122),
and a [claim analysis journey](https://github.com/microsoft/content-processing-solution-accelerator/blob/9a3f15e4b1403c0851507a9009bc1d39141c4eab/docs/ClaimProcessWorkflow.md).
Its [Bicep](https://github.com/microsoft/content-processing-solution-accelerator/blob/9a3f15e4b1403c0851507a9009bc1d39141c4eab/infra/main.bicep#L174-L178)
conditionally provisions private networking.

These are reuse candidates, not proof of exact HTML/dialogue provenance,
immutable releases, human-gold regression gates or Fabric-wide network support.
Adapt digital input handling instead of expanding scope to match PDF/vision
assumptions. Do not duplicate queues, stores or applications without a need.

## Fabric prerequisites and data surfaces

An Azure subscription alone does not establish Fabric readiness. Verify tenant
enablement, capacity-backed workspace, user licensing, permissions and capacity
ownership. PPU alone does not provide Fabric capacity; Power BI authoring/viewing
requirements depend on the selected license/capacity and sharing route.
Sources: [licenses](https://learn.microsoft.com/en-us/fabric/enterprise/licenses),
[workspace roles](https://learn.microsoft.com/en-us/fabric/fundamentals/roles-workspaces).

Trial availability and its feature limits must be checked, not assumed.
The current [trial documentation](https://learn.microsoft.com/en-us/fabric/fundamentals/fabric-trial)
describes a 60-day trial with capacity configurations and restrictions; trial
eligibility is not established for this user.

A JSON file in Lakehouse Files is not automatically a SQL-queryable managed
Delta table. The [Lakehouse SQL analytics endpoint](https://learn.microsoft.com/en-us/fabric/data-engineering/lakehouse-sql-analytics-endpoint)
is a read-only T-SQL surface over underlying Delta data, not an INSERT/UPDATE/
DELETE writer. Use Spark or another verified supported writer. Tables that
reference `/files` are not exposed through that endpoint; use supported managed
tables or Tables shortcuts. SQL security alone does not govern other access
paths such as Spark.

The [medallion pattern](https://learn.microsoft.com/en-us/fabric/onelake/onelake-medallion-lakehouse-architecture)
provides useful raw/cleaned/curated organization. It does not establish
cross-table atomic publication, immediate consumer freshness, immutable
experiment history or exactly-once CU invocation.

## Identity and private connectivity are path-specific

[CU supports Entra authentication and private endpoints](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/concepts/secure-communications).
The accelerator's [CU client](https://github.com/microsoft/content-processing-solution-accelerator/blob/9a3f15e4b1403c0851507a9009bc1d39141c4eab/src/ContentProcessor/src/libs/azure_helper/content_understanding.py#L20-L56)
defaults to GA `2025-11-01` and uses the Cognitive Services token scope; its
[credential helper](https://github.com/microsoft/content-processing-solution-accelerator/blob/9a3f15e4b1403c0851507a9009bc1d39141c4eab/src/ContentProcessor/src/libs/utils/azure_credential_utils.py#L77-L99)
selects managed identity in detected Azure environments.

[Fabric workspace identity](https://learn.microsoft.com/en-us/fabric/data-factory/workspace-identity)
is a managed service principal with operation-specific support and permissions.
Workspace Admin is required to create it; My Workspace is not supported.
Connector support does not prove arbitrary notebook code can acquire a CU
token as that identity. Scheduled execution identity, token audience, CU/model
RBAC and the exact notebook/pipeline route remain unverified.

[Managed private endpoints](https://learn.microsoft.com/en-us/fabric/security/security-managed-private-endpoints-overview)
support listed Data Engineering workloads; [creation guidance](https://learn.microsoft.com/en-us/fabric/security/security-managed-private-endpoints-create)
lists Cognitive Services as a target. This is a candidate CU path, not a tested
deployment. OneLake shortcuts do not use those endpoints for Blob/ADLS access.
[Web activity](https://learn.microsoft.com/en-us/fabric/data-factory/web-activity)
has a separate gateway/configuration path. Outbound managed private endpoints,
Fabric Private Link and trusted workspace access are distinct features with
different trial/support limits; verify each required route, DNS and approval.

## Incremental processing, evidence and release boundaries

The [incremental-copy tutorial](https://learn.microsoft.com/en-us/fabric/data-factory/tutorial-incremental-copy-data-warehouse-lakehouse)
demonstrates watermark-based copy, not a ready-made CU submission/recovery
contract. Stable source/version/configuration identities, remote operation
tracking, deduplication and checkpoint advancement after durable success remain
explicit integration work.

[Fabric lineage](https://learn.microsoft.com/en-us/fabric/governance/lineage)
shows item relationships, not automatically exact field-to-original-source
evidence, human approval, gold labels or an immutable release. Keep original
sources, CU-derived artifacts, corrected records and published release identity
distinct. Test partial-write/replay boundaries instead of inferring guarantees.

## Cost and unresolved environment checks

Budget Fabric capacity and active time, OneLake storage/retention, CU parsing/
contextualization, selected model tokens, and any additional Azure compute,
storage, gateway/network and monitoring. Do not reuse the tiny synthetic
DeepSeek bill as a project estimate.

[Capacity pause/resume](https://learn.microsoft.com/en-us/fabric/enterprise/pause-resume)
can affect availability and bills accumulated overages/smoothed operations at
pause. [OneLake storage](https://learn.microsoft.com/en-us/fabric/onelake/onelake-consumption)
is billed separately from capacity; pausing is not deletion or a zero-total-cost
guarantee. [CU pricing](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/pricing-explainer)
separates service work from connected model usage and distinguishes API modes.

Current tenant access, capacity/SKU, regions, model quota, exact identity/network
support, contract prices and measured workload cost are **unverified**. The small
two-domain quality set cannot replace security, scale, recovery or clean-target
deployment acceptance.
