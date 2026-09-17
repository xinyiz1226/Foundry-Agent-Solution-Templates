# R0: resource availability and functional feasibility

**Checked September 17, 2026, 02:45-02:49 UTC. R0 is blocked, not passed.**
The [confirmed journey](agent-user-journey.md) remains the target. This assessment
separates live metadata access from documented capabilities and work that still
requires configuration, implementation or a separately authorized paid test.
The focused public-source API and pricing follow-up was completed the same day.

## 1. Decision

The Foundry/CU side has a usable starting point: an existing East US Foundry
account/project, GPT-5-mini and an embedding deployment, working Entra-authenticated
CU metadata APIs, and a working Foundry agent-list API. A new Foundry account or
larger model deployment is **not justified by the current evidence**.

The immediate blocker is Fabric. Token acquisition succeeded, but both Fabric
workspace and capacity enumeration returned **HTTP 401 `UserNotLicensed`** in
the selected Azure subscription's tenant/operator context. This does not prove
the user lacks a license in every tenant, or that no organization-wide capacity
exists. Do not buy a capacity merely to work around an unidentified user/tenant
licensing problem.

CU extraction is not configured or proven. Account default model bindings are
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
Resolve [Fabric licensing](https://learn.microsoft.com/en-us/fabric/enterprise/licenses)
and [workspace roles](https://learn.microsoft.com/en-us/fabric/fundamentals/roles-workspaces)
in the intended Fabric tenant before repeating these reads.

## 4. Existing models, CU compatibility and quota

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

The response contained GPT-4.1 batch meters but no selected real-time GPT-4.1
meters. It reported zero limit for selected non-mini GPT-5.4 real-time meters.
Batch enqueued-token quota cannot substitute for synchronous Agent/CU quota.
No quota increase or deployment was attempted.

## 5. Functional feasibility and remaining proofs

| Requirement | Assessment | Required evidence before claiming success |
| --- | --- | --- |
| Goal -> inspected samples -> proposed schema | Documented Agent/function-calling capability; existing model is a candidate. | Real agent response and allowlisted bounded sampling; human schema confirmation; denial of unauthorized data/tools. |
| HTML/TXT Files and stable-ID/text Table inputs | CU digital input support and Fabric data surfaces are documented. | Selected licensed Fabric workspace; bounded source reads, preservation of source/version/turn identity, successful CU calls. |
| Description-only autonomous iteration | Application-enforced control logic is implementable, not a native CU safety guarantee. | Frozen schema/scoring, grant limits/expiry, best comparable draft, visible stops and independent held-out isolation. |
| Continue after Notebook disconnect | Notebook-only function dispatch is insufficient. | Durable execution owner; disconnect/reopen and worker restart tests; same run identity and safe remote-operation recovery. |
| Notebook/Pipeline jobs | Documented workload APIs exist; target tenant remains blocked. | Exact item/job type, parameters, noninteractive identity, submission/status/result path and connection support. |
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
the Fabric tenant/capacity, active hours, worker host, source billing units and
model-token workload have not been validated. Price capacity plus OneLake,
CU service processing plus connected model tokens, Agent reasoning, worker/state,
and any network/monitoring components separately. Retained POC costs are a
baseline, not new integration usage.

No spending limit or configuration change is authorized by this report.
Before any paid proof, propose a bounded source set, total CU submissions,
Agent-response/workload limits, expiration, approved mutations and cost envelope.
CU analysis may invoke multiple underlying model calls; an application
submission count is not an exact monetary cap or exactly-once billing guarantee.

## 7. Unblock R0, then authorize R1

1. Confirm the intended Fabric identity/tenant and an existing capacity-backed
   workspace/Lakehouse. Resolve the observed licensing error through the
   appropriate administrator or user licensing path; do not activate a trial or
   buy capacity without a separate decision.
2. Repeat read-only workspace/capacity/item checks in that authorized context.
   Verify Notebook/Pipeline and OneLake permissions for the selected unattended
   identity and identify any administrator/network dependencies.
3. Review CU model binding and account/worker identity rights. Prefer the
   existing GPT-5-mini and embedding deployment if their actual custom-analyzer
   behavior satisfies both domains. Do not alter shared defaults without approval.
4. Agree on durable worker/state ownership and the concrete resource/cost plan,
   reusing existing resources only where isolation and ownership permit.
5. Obtain separate approval for configuration/resource changes and bounded paid
   proofs: goal-to-schema, both input shapes to unpublished Tables, original
   evidence, deny tests, disconnect/reopen and ambiguous-submission recovery.

**R0 remains blocked by Fabric access and unverified execution/identity choices.
R1-R5 have not started.** Documented feasibility and HTTP 200 metadata reads are
not end-to-end functional acceptance.
