# R0: resource availability and functional feasibility

**Updated September 17, 2026, 06:24 UTC. Fabric access and a same-tenant Azure
subscription path are confirmed through metadata; R0 has not passed.**
The [confirmed journey](agent-user-journey.md) remains the target. This assessment
separates live metadata access from documented capabilities and work that still
requires configuration, implementation or a separately authorized paid test.
Initial resource checks ran at 02:45-02:49 UTC; the user-supplied Fabric target
was checked at 05:59-06:00 UTC. The user subsequently selected same-tenant
investigation and a corporate test subscription, checked at 06:19-06:24 UTC.
The earlier failed tenant context is retained below as historical evidence,
not the current target's status.

## 1. Decision

The legacy POC has a usable comparison baseline: an existing East US Foundry
account/project, GPT-5-mini and an embedding deployment, working Entra-authenticated
CU metadata APIs, and a working Foundry agent-list API. Model capacity alone
does not justify a larger deployment. Resource reuse now also depends on the
tenant-placement decision described below.

**The Fabric metadata-access blocker is resolved for the supplied target.**
Using the existing operator's corporate-tenant authentication, the selected
workspace and Lakehouse GETs both returned HTTP 200. The workspace's capacity
matched an **Active F4 in West Central US**. No new capacity or trial is needed
merely to establish the presence of a usable Fabric starting point.

The earlier **HTTP 401 `UserNotLicensed`** occurred in the separate Azure
test-subscription tenant. It was reconfirmed at 05:37 UTC; no license was added
or changed to obtain the later corporate-tenant success.

**The user selected a same-tenant direction for further assessment.** Fabric
and the legacy POC's CU/Foundry resources remain physically in different tenants;
no migration has occurred. A user-selected corporate test subscription is
Enabled, exposes Foundry resources and has candidate model quota. Prefer a
dedicated POC resource group/account/project there, subject to an approved
resource, identity, network and cost plan, rather than borrowing another
team member's test resources without confirmed ownership/use authorization.
The user has not authorized creating that proposed deployment.

Corporate Fabric access does not authorize exporting corporate data to the
legacy test tenant. Do not silently adopt cross-tenant execution or assume one
workspace/managed identity can access both sides. No source contents were read
or transferred during these checks.

CU extraction on that legacy account is not configured or proven. Default model bindings are
empty, the account managed identity has no matching assignments in the
account-scope/inherited role-assignment result, and no new analyzer has been
created or called. Existing deployment availability and analyzer compatibility
metadata are promising, not a successful CU-to-model authorization test.

Recommend **Fabric Notebook UI + a durable worker + a Foundry prompt agent**
for the first integration. The worker owns grants, dispatch, checkpoints and
remote-operation reconciliation independently of the Notebook kernel. This is
a conditional recommendation, not an approved hosting deployment or a
disconnect/recovery proof.

## 2. Authorized scope and evidence handling

The user authorized resource/access checks and functional feasibility assessment.
Only existing operator authentication, management-plane inventory, quotas,
permissions, data-plane metadata GETs, public documentation and retail prices
were inspected. The Resource Graph POST was a read-only query.

No resources, analyzers, agents, workspaces, capacities or role assignments were
created or changed. No model inference, CU analysis, Notebook/Pipeline execution,
trial activation or source-data ingestion occurred. No application keys,
connection secrets, business document contents or raw tokens were requested or
published. Existing workbench processes and retained state were not changed.

Detailed timestamped JSON receipts remain in the private session artifacts.
This portable report intentionally omits tenant/subscription/principal/workspace
IDs, resource names, internal endpoints and other users' resource inventory.
It records observed properties, not a claim about resources outside the selected
subscription or the caller's visibility.

## 3. Live availability checks

### Latest: same-tenant Azure path, 06:19-06:24 UTC

After the user selected same-tenant investigation, ARM listed 158 subscriptions
visible to the operator in the corporate tenant. The user then chose one
corporate Foundry-agent test subscription. Resource inventory was restricted
to that subscription; visibility of the others was not treated as authorization
to inspect their resources or use their budgets.

| Surface | Observed result | Boundary |
| --- | --- | --- |
| Selected subscription | Enabled, in the same tenant as the supplied Fabric Lakehouse. | Tenant alignment is possible without moving Fabric. No resource deployment was approved. |
| Resource inventory | HTTP 200, 92 matching resources, not truncated: 47 Cognitive Services accounts, 42 account projects, three Machine Learning workspaces. | Existing resources are candidates, not approved shared dependencies. Some account provisioning states are Failed; the count is not a count of working deployments. |
| Name-based discovery | No matching account/project/resource-group names for the operator's identifier. | A naming heuristic is not ownership evidence or proof that no usable resource exists. No existing account was selected for reuse. |
| Provider | `Microsoft.CognitiveServices` is Registered. | No registration change is needed on the observed state. |
| Operator permissions | Subscription-level effective permissions include management `actions: ["*"]`; returned `dataActions` are empty. | Broad management permission is not a Foundry data-plane grant, corporate approval, or a deployment guarantee against Azure Policy/deny assignments. Resource-specific rights remain unverified. |
| Model catalog | East US 2 lists GPT-4.1-mini `2025-04-14` with Standard/GlobalStandard, GPT-5-mini `2025-08-07` with GlobalStandard, and text-embedding-3-small `1` with Standard/GlobalStandard. | Catalog/SKU presence plus quota is not successful deployment or CU analysis. |

**Region recommendation:** East US 2 is a documented CU region. The current
[CU region list](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/language-region-support)
does not include West Central US (the existing Fabric capacity's region) or
West US 2 (an additional quota-only probe). Do not choose a CU region solely
because Foundry accounts or model quota exist there. The proposed same-tenant
path remains cross-region and needs appropriate data-location/network review;
it is not a same-region deployment.

East US 2 quota values, interpreted using the API's explicit thousands-of-TPM
meter descriptions:

| Model / deployment type | Allocated | Limit | Arithmetic headroom |
| --- | --- | --- | --- |
| GPT-4.1-mini Standard | 0 | 5,000K TPM | 5,000K TPM |
| GPT-4.1-mini GlobalStandard | 2,510K TPM | 15,000K TPM | 12,490K TPM |
| GPT-4.1 GlobalStandard | 1,000K TPM | 3,000K TPM | 2,000K TPM |
| GPT-5-mini GlobalStandard | 500K TPM | 1,000K TPM | 500K TPM |
| text-embedding-3-small Standard | 120K TPM | 350K TPM | 230K TPM |
| text-embedding-3-large Standard | 240K TPM | 350K TPM | 110K TPM |

Use the catalog's exact `usageName` for quota lookup: GPT-4.1-mini uses
`OpenAI.Standard.gpt4.1-mini` / `OpenAI.GlobalStandard.gpt4.1-mini`, not a
hyphenated `gpt-4.1-mini` suffix. The initial discovery filter missed these
meters; the table above uses the corrected catalog-matched query. Do not infer
zero quota from a mismatched string filter or add repeated regional readings.

For a later approved small pilot, **GPT-4.1-mini `2025-04-14` is the preferred
first validation candidate**, with text-embedding-3-small where the analyzer
requires it. Its version agrees between the live catalog and
[CU's supported-model table](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/service-limits#supported-generative-models).
Standard is a candidate deployment type, not a tested throughput or
data-residency guarantee for the entire solution. GPT-5-mini remains an
alternative: its live catalog version is `2025-08-07`, while the current CU
table lists `2025-12-11`. That discrepancy requires validation, not a fabricated
version selection or an automatic incompatibility claim.

No corporate Foundry data-plane reads, model calls, analyzer configuration,
resource creation or RBAC mutations were performed. Management-plane discovery
of a team resource does not authorize its invocation.

### Supplied Fabric target, 05:59-06:00 UTC

| Surface | Observed result | Boundary |
| --- | --- | --- |
| Authentication | A Fabric token was acquired for the corporate tenant from existing operator authentication. | No interactive login or default Azure subscription change was needed. |
| Selected workspace | GET returned HTTP 200 and a capacity association. | The user-supplied target is readable; write/execute permissions were not tested. |
| Selected Lakehouse | GET returned HTTP 200, type Lakehouse, with Files/Tables paths and default schema `dbo`. | Paths are metadata, not evidence of readable source files, populated tables or write access. |
| SQL analytics endpoint | Reported provisioning status `Success`. | No SQL connection or query was executed. |
| Associated capacity | The visible-capacity list contained the workspace's matching capacity: F4, Active, West Central US. | No purchase is implied. Workload headroom, performance, reservation/contract price and authorization to use shared capacity remain unverified. |
| Tenant placement | Fabric target and existing CU/Foundry have different tenant contexts. | Agree on supported identities and permitted data movement, or approved same-tenant resource placement, before implementation. |

The supplied workspace/Lakehouse names, IDs and capacity details are retained
privately rather than embedded in the portable template.

### Initial: Azure test-subscription context, 02:45-02:49 UTC

| Surface | Observed result | What it establishes / does not establish |
| --- | --- | --- |
| Azure operator | Subscription is Enabled; account and signed-in-user metadata are readable. | Azure access works in the selected tenant. This does not establish Fabric licensing or an unattended worker identity. |
| Resource inventory | Resource Graph returned HTTP 200 with no truncation for the relevant resource-type query. No `Microsoft.Fabric/capacities` resources appeared in this subscription. | No ARM Fabric capacity was observed here. Capacities elsewhere, trial capacities and tenant-wide availability are not ruled out. |
| Fabric provider | `Microsoft.Fabric` is Registered. | Provider registration is not a capacity, user license, workspace assignment or permission to run workloads. |
| Fabric token | An access token for the Fabric audience was acquired without interactive login. | Authentication/token acquisition alone is insufficient. |
| Fabric APIs | Both `GET /v1/workspaces` and `GET /v1/capacities` returned HTTP 401 `UserNotLicensed`. | No successful workspace/capacity/item enumeration; no Lakehouse or Notebook target can yet be verified. |
| Primary Foundry resource | Existing East US `AIServices` S0 account and project are provisioned; project management is enabled. | Reuse candidate for Agent/CU. Existing resources must not be overwritten. |
| Secondary owned Foundry resource | Existing Japan East account/project has no model deployments. | No reason to switch from the populated East US account on present evidence. |
| Foundry agent API | SDK-supported `GET .../agents?limit=10&api-version=v1` returned HTTP 200, four existing agents, no further page. | Operator can read the catalog. No new agent, function dispatch or autonomous execution was tested. |
| CU GA API | GET defaults and three prebuilt analyzer definitions returned HTTP 200 using Entra authentication and API `2025-11-01`. | Endpoint/network/operator read authorization work. No extraction or accuracy evidence. |
| Network | Primary account has public access enabled, default network action Allow, no listed private endpoint connections. | Reachable development configuration, not private-enterprise networking acceptance. |
| Operator permissions | Effective permissions include Cognitive Services data actions, with exclusions including agent user-identity impersonation. | Do not infer that the operator's rights transfer to CU, a worker or Fabric workspace identity. |
| Account managed identity | System-assigned identity exists; no matching role assignments were returned by the account-scope/inherited assignment query. | CU-to-model authorization still needs review and a narrowly approved configuration/test; group/alternative credential routes were not investigated. |
| Existing POC storage/compute | Existing storage accounts and a Linux B1 App Service plan remain; the old web app is Stopped with public ingress Disabled. | Preserve them. Stopping the app does not remove the dedicated plan's compute charge. Their suitability for new durable execution is untested. |

The separate Content Processing accelerator session was checked through its
latest local handoff. It remains at model/quota recommendation and asks for
configuration/cost/deployment approval before creation. That is not evidence
of an already deployed accelerator to reuse; do not duplicate that initiative.

Fabric list endpoints are visibility-scoped, not tenant inventory:
[workspaces](https://learn.microsoft.com/en-us/rest/api/fabric/core/workspaces/list-workspaces)
and [capacities](https://learn.microsoft.com/en-us/rest/api/fabric/core/capacities/list-capacities).
[Fabric licensing](https://learn.microsoft.com/en-us/fabric/enterprise/licenses)
and [workspace roles](https://learn.microsoft.com/en-us/fabric/fundamentals/roles-workspaces)
are context-specific. The supplied target's later successful reads supersede
the initial assumption that Fabric target discovery is still blocked.

## 4. Legacy test-tenant models, CU compatibility and quota

### Deployments already available in the primary account

| Deployment/model | Version | SKU / allocated capacity | Reported rate limits |
| --- | --- | --- | --- |
| GPT-5-mini | `2025-08-07` | GlobalStandard / 50 | 50 requests/minute; 50,000 tokens/minute |
| text-embedding-3-small | `1` | Standard / 120 | 120 requests/10 seconds; 120,000 tokens/minute |
| DeepSeek-V4-Pro | `2026-04-23` | GlobalStandard / 20 | 20 requests/minute; 20,000 tokens/minute |
| DeepSeek-V4-Flash-0731 | `2026-07-31` | GlobalStandard / 20 | 20 requests/minute; 20,000 tokens/minute |

All four deployments reported Succeeded. These are service-reported limits,
not measured throughput or capacity reserved for this accelerator. Historical
DeepSeek pilot success does not establish CU compatibility.

### Read-only CU findings

`GET /contentunderstanding/defaults` returned `modelDeployments: {}`.
Do not silently change shared account defaults during setup; first choose and
review the narrowest supported analyzer/model-binding scope. CU documents
request-level `modelDeployments` overrides, so empty defaults do **not** require
a resource-wide change. Prefer explicit mappings for the bounded trial if the
selected analyzer/request contract supports the intended configuration.
Sources: [GET defaults](https://learn.microsoft.com/en-us/rest/api/contentunderstanding/content-analyzers/get-defaults?view=rest-contentunderstanding-2025-11-01)
and [model deployment mappings](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/concepts/models-deployments).

The live prebuilt definitions reported:

| Analyzer | Relevant compatibility metadata | Consequence |
| --- | --- | --- |
| `prebuilt-document` | Supported completion models include GPT-5-mini; supported embedding models include text-embedding-3-small. | The existing pair is a candidate for custom document extraction. A custom schema/model binding and real call remain untested. |
| `prebuilt-documentFieldSchema` | Supported completion list excludes GPT-5-mini; embedding list contains only text-embedding-3-large. | Do not assume the existing mini/small pair can run CU's schema-generation prebuilt. |
| `prebuilt-digitalParse` | `models: {}`; OCR/layout disabled in the returned configuration. | Useful no-language-model parsing candidate for digital inputs, not proof of schema extraction or a free analysis service. |

The product requirement is **Agent-generated schema**, not mandatory use of
`prebuilt-documentFieldSchema`. Prefer testing the existing GPT-5-mini through
the Foundry Agent for proposal generation, then passing the human-confirmed
schema to a compatible CU custom analyzer. This avoids making the more
restrictive CU schema-generation prebuilt a new deployment prerequisite.
Tool/structured-output behavior must still be proven.

### Quota snapshot

The East US usage endpoint reported the following selected real-time meters:

| Meter | Allocated | Limit | Arithmetic headroom |
| --- | --- | --- | --- |
| GPT-5-mini GlobalStandard | 275K TPM | 500K TPM | 225K TPM |
| GPT-5.4-mini DataZoneStandard | 0 | 200K TPM | 200K TPM |
| text-embedding-3-small Standard | 120K TPM | 350K TPM | 230K TPM |
| text-embedding-3-large Standard | 0 | 350K TPM | 350K TPM |

The API's generic `unit` is `Count`; its localized meter descriptions explicitly
identify thousands of tokens per minute. West US 2 returned the same GPT-5-mini
GlobalStandard allocation. Do not add regional readings as independent pools.
Quota headroom is not actual model/region deployability, a quota grant for this
project, or a reason to expand the existing pilot deployment.

The earlier test-tenant probe's GPT-4.1 filter used display-model hyphenation
rather than the exact quota `usageName`. Its missing real-time results do not
establish absent/zero GPT-4.1 quota; that tenant was not re-probed after selection
of the corporate path. It reported zero limit for selected non-mini GPT-5.4
real-time meters. Batch enqueued-token quota cannot substitute for synchronous
Agent/CU quota. No quota increase or deployment was attempted.

## 5. Functional feasibility and remaining proofs

| Requirement | Assessment | Required evidence before claiming success |
| --- | --- | --- |
| Goal -> inspected samples -> proposed schema | Documented Agent/function-calling capability; existing model is a candidate. | Real agent response and allowlisted bounded sampling; human schema confirmation; denial of unauthorized data/tools. |
| HTML/TXT Files and stable-ID/text Table inputs | CU digital input support is documented; the selected Lakehouse exposes Files/Tables paths in metadata. | Authorized bounded source reads, preservation of source/version/turn identity, successful CU calls and table writes. |
| Description-only autonomous iteration | Application-enforced control logic is implementable, not a native CU safety guarantee. | Frozen schema/scoring, grant limits/expiry, best comparable draft, visible stops and independent held-out isolation. |
| Continue after Notebook disconnect | Notebook-only function dispatch is insufficient. | Durable execution owner; disconnect/reopen and worker restart tests; same run identity and safe remote-operation recovery. |
| Notebook/Pipeline jobs | Documented workload APIs exist; selected workspace metadata is accessible. | Exact item/job type, parameters, execution permissions, noninteractive identity, submission/status/result path and connection support. |
| Candidate Delta Tables and SQL analysis | Use Spark or another supported writer; Lakehouse SQL analytics is read-only over table data. | Actual managed-table creation/query and input/output reconciliation. JSON copied into Files is insufficient. |
| Human approval and reproducible release | Requires explicit application policy, manifest and consumer-selection behavior. | Scope-bound approval, coverage, evidence gates, partial-write/replay tests and stable release references. |
| Scheduled candidate production | Feasible design, not verified execution. | Schedule authorization, frozen configuration, unattended identity, incremental/retry behavior; no automatic publication. |
| Enterprise identity/private access | Operator public-endpoint reads only. | Least privilege on every hop; chosen network profile, DNS/endpoints and negative-access tests. |

Keep the [pinned reuse/adaptation map](cu-fabric-research.md): adapt the official
Fabric sample's old API/key/SAS/overwriting/completion dependency behavior; reuse
the Content Processing accelerator selectively rather than deploying its whole
UI/queue/Cosmos DB stack by default.

The recommended worker owns control state, not a second copy of Fabric's
analytical data platform. Fabric owns Lakehouse datasets and bounded data jobs.
The Agent selects allowed development actions; the worker validates every
argument and grant and records results. Independent acceptance and publication
remain outside its authority.

Use fixed, versioned Notebook code and allowlisted parameters, not Agent-generated
Python/Spark/SQL. Persist result manifests/artifact references instead of relying
on a browser connection or assuming a generic job-status response contains
Notebook output. Choosing the exact worker host, durable store and unattended
identity is still an R0 decision requiring target-environment evidence.

### Verified API contracts, not executed jobs

The following routes use `https://api.fabric.microsoft.com/v1`. Listing them
does not authorize submission. User, service-principal and managed-identity
support in the REST contracts remains subject to tenant settings, item
permissions and workload/connection restrictions.

| Purpose | Documented route / result |
| --- | --- |
| Selected item metadata | `GET /workspaces/{workspaceId}/items/{itemId}`; optional `?include=DefaultIdentity`. |
| Notebook submission | Release route: `POST /workspaces/{workspaceId}/notebooks/{notebookId}/jobs/execute/instances?beta=false`. Returns 202, Location and Retry-After; parameter/compute configuration is documented. |
| Pipeline submission | `POST /workspaces/{workspaceId}/items/{itemId}/jobs/Pipeline/instances`. The older `jobs/instances?jobType=Pipeline` route remains documented. Parameter support is workload/job-specific. |
| Job lifecycle | `GET /workspaces/{workspaceId}/items/{itemId}/jobs/instances/{jobInstanceId}`. Provides status/failure metadata, not a documented Notebook exit value. |
| Notebook richer result | `GET /workspaces/{workspaceId}/notebooks/{notebookId}/jobs/execute/instances/{jobInstanceId}?beta=true`. Beta; the value is `properties.exitValue`, not a top-level field. No release equivalent was verified. |

References: [item metadata](https://learn.microsoft.com/en-us/rest/api/fabric/core/items/get-item),
[Notebook submission](https://learn.microsoft.com/en-us/rest/api/fabric/notebook/background-jobs/run-on-demand-notebook),
[core submission](https://learn.microsoft.com/en-us/rest/api/fabric/core/job-scheduler/run-on-demand-item-job),
[job status](https://learn.microsoft.com/en-us/rest/api/fabric/core/job-scheduler/get-item-job-instance),
[beta Notebook result](https://learn.microsoft.com/en-us/rest/api/fabric/notebook/background-jobs/get-notebook-job-instance%28beta%29)
and [identity support](https://learn.microsoft.com/en-us/rest/api/fabric/articles/identity-support).

Use release submission plus lifecycle polling and a bounded, operation-ID-keyed
result manifest instead of making beta exit-value retrieval mandatory.
The older Pipeline guide's statement that an actual run never succeeds remains
an unresolved documentation inconsistency: the current REST contract and a
[first-party service-principal sample](https://github.com/microsoft/fabric-user-data-functions-samples/blob/main/PYTHON/fabric-rest-apis/fabric-restapi-functions.py#L14-L54)
document Pipeline submission. The sample checks acceptance, not successful
completion. Neither universal failure nor working end-to-end execution should
be inferred without the selected tenant's live proof.

For the hosted alternative,
[long-running resilience](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/long-running-agent-resilience)
is preview. Outliving a request connection is distinct from crash recovery;
recovery requires stored background responses and explicit resilient-execution
opt-in, re-enters the handler, and still requires checkpoints and duplicate
side-effect prevention. Foreground requests are not recovered. The recommended
durable worker avoids making that preview a prerequisite; it still needs its
own proven persistence/recovery implementation.

## 6. Cost and approval boundary

No new billable inference or compute jobs were started by this assessment.
This is not a claim of zero existing Azure charges.

The existing West US 2 **Linux B1** retail meter returned **USD 0.017/hour**
(`Azure App Service Basic Plan - Linux`, B1, Consumption, checked September 17).
At 730 hours/month, one retained instance is approximately **USD 12.41/month**
before storage, network, monitoring, taxes or negotiated pricing. Do not confuse
the Windows B1 meter with Linux. A stopped web app does not stop plan-level
dedicated compute billing.
Sources: [App Service billing model](https://learn.microsoft.com/en-us/azure/app-service/overview-hosting-plans#cost-of-app-service-plans)
and [Azure Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices).

### Fabric capacity-only scenarios

The public Retail Prices API returned **USD 0.18 per Fabric capacity-unit hour**
for the Consumption meter `Compute Pool Capacity Usage CU` in East US and
West US 2. Meter IDs are `2e1c6864-e833-5731-8dd6-220bc17b5566` and
`0f8accf9-0d34-5e06-9dca-b08cef8a3add`, respectively.
The [Fabric pricing page](https://azure.microsoft.com/en-us/pricing/details/microsoft-fabric/)
defines F2 as two capacity units and F4 as four. The following are arithmetic
equivalents from that meter, **not independently returned SKU quotes, measured
workload costs or proof that either SKU is sufficient/available for this tenant**:

| Scenario | F2 equivalent at USD 0.36/hour | F4 equivalent at USD 0.72/hour |
| --- | --- | --- |
| Bounded experiment, 10 active hours | USD 3.60 | USD 7.20 |
| Development month, 160 active hours | USD 57.60 | USD 115.20 |
| Continuously active month, 730 hours | USD 262.80 | USD 525.60 |

These are capacity-only sizing scenarios, not a purchase recommendation.
Existing shared capacity may avoid a new purchase but still consumes capacity;
trial eligibility and private-network feature suitability have not been checked.
[OneLake storage](https://learn.microsoft.com/en-us/fabric/onelake/onelake-consumption)
is separate. [Pausing capacity](https://learn.microsoft.com/en-us/fabric/enterprise/pause-resume)
settles remaining smoothed consumption/overages and does not eliminate storage
or unrelated Azure costs.

The [CU pricing explainer](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/pricing-explainer)
uses an illustrative USD 1/million standard contextualization tokens, separate
from extraction and connected-model charges. This is not a verified regional
quote. Current regional extraction and GPT-5-mini token prices were not verified
in this follow-up; do not substitute the older DeepSeek pilot bill or remembered
model prices.

A complete CU/Fabric pilot and monthly estimate is **not yet a deployment quote**:
an existing Active F4 in West Central US is now identified, but its contract/
allocation cost, workload headroom, active hours, worker host, source billing
units and model-token workload have not been validated. The earlier East US/
West US 2 scenarios are not a regional quote for this capacity. Price capacity plus OneLake,
CU service processing plus connected model tokens, Agent reasoning, worker/state,
and any network/monitoring components separately. Retained POC costs are a
baseline, not new integration usage.

No spending limit or configuration change is authorized by this report.
Before any paid proof, propose a bounded source set, total CU submissions,
Agent-response/workload limits, expiration, approved mutations and cost envelope.
CU analysis may invoke multiple underlying model calls; an application
submission count is not an exact monetary cap or exactly-once billing guarantee.

## 7. Unblock R0, then authorize R1

1. **Completed for metadata:** the supplied Fabric workspace/Lakehouse is
   readable in the corporate tenant and attached to an Active F4 capacity.
   Do not acquire another capacity to resolve the unrelated test-tenant error.
2. **Same-tenant direction selected; discovery completed:** the user-selected
   corporate test subscription has Foundry resources and candidate model quota.
   Agree on a dedicated resource plan or explicitly authorized existing account,
   preserving the legacy test-tenant POC. Do not deploy or borrow team resources
   merely because they are visible.
3. Verify Notebook/Pipeline, OneLake, CU-to-model and worker rights for the chosen
   unattended identity, plus same-tenant/cross-region network and data boundaries.
   Start the model-validation plan with the catalog-matched GPT-4.1-mini candidate;
   preserve alternatives if real CU/Agent behavior fails. Do not change shared
   model defaults without approval. Metadata reads are not write/execute proof.
4. Agree on durable worker/state ownership and the concrete resource/cost plan,
   reusing existing resources only where isolation and ownership permit.
5. Obtain separate approval for configuration/resource changes and bounded paid
   proofs: goal-to-schema, both input shapes to unpublished Tables, original
   evidence, deny tests, disconnect/reopen and ambiguous-submission recovery.

**Fabric discovery/read access and same-tenant subscription/model-quota discovery
are complete. R0 still needs a selected account/resource plan, unattended
identity/network design, execution architecture and cost approval. R1-R5 have
not started.** Documented feasibility and HTTP 200 metadata reads are not
end-to-end functional acceptance.
