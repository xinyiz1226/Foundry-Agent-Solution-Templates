# Minimal experiment: deployment approval

Status: **preflight and authorized SQL provider registration completed; resource provisioning not approved or run**.

Local build/test evidence must be reviewed separately from the Azure checks.
Passing tests does not certify SDK/runtime compatibility or private SQL access.
All entries below must be settled before running approval-gated scripts.

## Current preparation checkpoint

The package has been committed and pushed. Local Azure CLI 2.90.0 and azd
1.34.0 are available with the required Foundry agent/project extensions.
The operator completed tenant-scoped sign-in. A live ARM subscription read
passed, and tenant-scoped azd status returned `success`. An unscoped azd
status check returned `unauthenticated` for the same local installation;
always check the tenant used for sign-in before asking the user to sign in again.

The proposed USD 10 spending-response threshold, maximum 24-hour experiment,
and immediate cleanup still require approval. Subscription/tenant and operator
IDs were verified and retained only in ignored local preflight artifacts.
The operator subsequently authorized reuse of an existing DeepSeek Flash model
and the next step, SQL provider registration. `Microsoft.Sql` is now registered.
No SQL database, Foundry resource, or shared-resource role assignment was created.
General resource provisioning and inference spending remain separate approvals.

On the deployment workstation, first make `az` and `azd` available on the
current shell's PATH and complete interactive sign-in with the intended tenant:

```powershell
az login --tenant '<approved-tenant-id>' --use-device-code
azd auth login --tenant-id '<approved-tenant-id>' --use-device-code
azd auth login --tenant-id '<approved-tenant-id>' --check-status --output json
```

Sign-in does not approve deployment. Complete the record below, use the actual
operator identity in an ignored `config.local.json`, and run read-only
`scripts\preflight.ps1 -ConfigPath .\config.local.json -CheckAzure`.
Keep credentials and local configuration out of Git. Region/model/quota,
permissions and spending approval remain separate gates.

### Read-only findings, 2026-09-15

| Check | Observed result |
|---|---|
| Subscription and caller | Enabled subscription; management permission includes `*` with no exclusions on that grant |
| Policy/deny checks | No assignments returned by the subscription/inherited policy query or at-scope deny query; not a guarantee that future deployment cannot be denied |
| Directory lookup | Current user object ID and an existing service principal's object/application IDs were readable; actual agent identity is not yet created |
| Required providers | All checked providers are now registered, including `Microsoft.Sql` after explicit authorization |
| Proposed new resource group | `rg-bpi-probe` does not exist; ownership guards must recheck immediately before creation |
| Hosted agents/private networking | Central US selected by the operator and listed as supported; actual session capacity and routing remain unverified |
| Selected model | Existing `DeepSeek-V4-Flash-0731`, version `2026-07-31`, Succeeded, GlobalStandard capacity 20, East US; Chat Completions is advertised |
| Model ownership | The existing model replaces the prior GPT deployment proposal. Do not create, resize, delete, or claim ownership of the shared account/model |
| Initializer quota | Central US: 0/100 container groups and 0/10 Standard cores |
| Network quota | Central US: 0/1000 VNets, 0/20 Standard IPv4 public IPs, 0/100 NAT gateways, 0/65536 private endpoints |
| SQL regional capabilities | Central US is `Available`: SQL 12.0, Basic 5 DTU, 2 GB and LRS backup are supported. East US and East US 2 remain restricted |
| Selected-region preflight | The existing script passed account, providers, shared-model metadata and SQL availability checks using the Central US candidate configuration |

**Region decision completed:** the operator selected Central US after a
read-only survey found SQL Basic available there, in West US 3, Canada Central,
Japan East, Australia East and West Europe. The local candidate now places
the new Foundry account/project, VNet and SQL in Central US. The existing
DeepSeek model stays in East US; it is not migrated or recreated.

**Remaining gates:** approve the complete resource/egress inventory, spending
response, maximum duration and cleanup responsibility, plus inference access
for the actual agent identity on the shared account. Read-only availability
and quota checks do not reserve capacity or prove the runtime works.

The selected local configuration now uses `modelMode: existing` and
`modelApi: chat_completions`, with the verified shared account's OpenAI v1
endpoint. Its model version, SKU and capacity are not template parameters
in this mode. The prior new-GPT quota/capacity proposal is superseded.
The existing deployment is GlobalStandard pay-as-you-go; reuse does not make
inference free or reserve any extra capacity for this probe.

The actual deployed agent identity must be separately authorized for inference
on the shared account. The scripts do not grant or revoke that role, retrieve
keys, alter shared networking, or fall back to the operator/project identity.
See [existing-model setup](../README.md#reuse-an-existing-model) for the
documented role and cleanup responsibilities. No model invocation has been
performed; real Flash tool-call compatibility and authorization remain live gates.

The local evidence and candidate configuration are under `.artifacts/preflight/`.
They are not ownership state or a deployment approval. The only cloud write
performed was the explicitly authorized SQL provider registration. No model
inference or automatic permissions changes were run.

## Approval record

| Decision | Required value |
|---|---|
| Approver and approval date | Not yet supplied |
| Subscription, tenant, and operator principal | Verified for read-only checks; actual IDs remain in ignored local artifacts |
| New resource group and environment | Choose a dedicated `rg-bpi-*` group; no reuse |
| Region | Central US explicitly selected for new resources; existing shared model remains in East US |
| Model, version, deployment SKU/capacity | Existing DeepSeek Flash selected; no new model deployment or capacity change |
| Shared-model runtime access | The model owner must approve the actual agent's inference role; no shared-role changes performed |
| Experiment duration and cleanup owner | Not yet supplied |
| Spending limit and response to threshold | Not yet supplied; budgets are alerts, not hard caps |
| Required directory/resource permissions | Broad management access and basic directory lookup observed; no automatic tenant consent or provider registration |
| Required package/image egress | Explicitly review; private SQL is not zero-internet execution |

## Resources to review

The Bicep files are the authoritative proposed inventory. Before execution,
compile and inspect them and perform an approved Azure what-if/preflight.

| Component | Purpose / cost consideration |
|---|---|
| Dedicated resource group | Ownership boundary; refuse pre-existing groups |
| New Foundry account and project | Source hosted-agent execution; the selected existing-model mode skips model deployment |
| Existing shared model | Externally owned, no deployment or resize; inference is still billed and requires approved runtime access |
| Foundry hosted agent | CPU/memory consumption and session idle time |
| VNet and separate delegated subnets | Foundry runtime, private endpoints, temporary initializer |
| Azure SQL logical server and Basic probe DB | Tiny fixture only; Basic is not a performance choice for the full DW |
| SQL private endpoint and private DNS | SQL public access disabled; endpoint charged while retained |
| Initializer user-assigned identity | Privileged only for this new experiment; never runtime identity |
| Private initialization storage/file endpoint/DNS | Private deployment-script support; persists beyond container lifetime |
| Deployment-script execution container | Temporary SQL bootstrap; required image/module downloads |
| Initializer-only Standard NAT gateway and static public IP | Explicit outbound path for private ACI image/module/identity access; hourly charges persist until cleanup |
| Scoped Azure role assignments | Model invocation, operator access, initializer storage and resource permissions |

No App Service, APIM, Search, VPN, private Foundry ingress endpoint, or agent
image registry is required for the minimum probe. If source-driver validation
fails, a container/registry fallback needs a new review, not an automatic switch.

The initializer downloads the pinned `SqlServer` PowerShell module from
PowerShell Gallery. The platform also needs Microsoft container images and
identity endpoints. Source builds need package access. No template rule should
open the SQL public endpoint to solve these dependencies.

**Architecture addition requiring review:** compiled Bicep includes a NAT
gateway and public IP attached only to the initializer subnet. These make
initializer egress explicit instead of relying on an unspecified default
outbound route. They do not create inbound access to SQL or attach a NAT to the
Foundry delegated subnet. See [ACI virtual-network requirements](https://learn.microsoft.com/en-us/azure/container-instances/container-instances-vnet).
They are proposed resources, not resources already deployed or approved.

## Authentication and permission review

The template uses separate principals:

1. **Operator:** provisions resources and role assignments, deploys/invokes the
   agent, and reads the deployed service principal's object and application IDs.
2. **Initializer:** new probe SQL server's Entra administrator and a scoped
   storage-file principal, used only in the private initialization job.
3. **Agent:** actual deployed runtime identity, granted only CONNECT and SELECT
   on `reporting.v_pilot_probe`, plus VIEW DEFINITION on the synthetic base table
   solely to make permission checks inspectable (not to read its rows).

The scripts use explicit external-user SID/type creation after verifying the
agent object/application IDs. They do not grant Directory Readers or execute
`CREATE USER ... FROM EXTERNAL PROVIDER` directory-name lookup as a fallback.
This authentication path still requires live validation. Reject a missing or
ambiguous agent identity rather than using the project identity.

The initializer identity is deliberately powerful for the disposable probe.
Do not carry this administrator design into the later customer-owned database
path. Removing or rotating that identity changes database administration and
must be coordinated rather than done implicitly.

## Cost estimate boundaries

Illustrative September 15, 2026 USD public retail prices. SQL Basic and the
Standard IPv4 static public IP were rechecked for the selected Central US
region; global Standard NAT and Private DNS rates were also rechecked.
This is not the subscription's negotiated bill or a complete deployment quote.

| Meter | Reference rate |
|---|---|
| SQL Basic | $0.161/day |
| Private endpoint | $0.01/hour per endpoint, plus processed data |
| Private DNS | $0.50/zone-month, plus queries |
| Standard NAT gateway | $0.045/hour, plus $0.045/GB processed |
| Standard static IPv4, Central US | $0.005/hour |
| Hosted-agent CPU | $0.0994/vCPU-hour |
| Hosted-agent memory | $0.0118/GiB-hour |

Source: [Azure Retail Prices API](https://prices.azure.com/api/retail/prices),
[Foundry pricing](https://azure.microsoft.com/en-us/pricing/details/foundry-agent-service/),
[Private Link pricing](https://azure.microsoft.com/en-us/pricing/details/private-link/).

These rates are examples, not a complete quote. Reprice the selected region
and all resources. In particular, the earlier $0.42/day
SQL-network subtotal covered **one** endpoint and **one** DNS zone. This
package also needs private initializer support, so that number is not its
infrastructure total.

For the proposed SQL Basic, **two** private endpoints (SQL/file), **two** DNS
zones, one NAT gateway, and one static IPv4, the selected-component subtotal
is approximately **$1.87/day, $3.75/two days, or $57.00/730 hours**. This excludes
initializer storage/transactions, ACI execution, hosted-agent compute, model
tokens, traffic, build charges if any, and platform-managed networking.
Do not present it as the total bill or a guaranteed experiment cap.

Reproducible retail queries:

- [Central US SQL Basic](https://prices.azure.com/api/retail/prices?$filter=armRegionName%20eq%20%27centralus%27%20and%20productName%20eq%20%27SQL%20Database%20Single%20Basic%27%20and%20skuName%20eq%20%27B%27)
- [Standard NAT gateway](https://prices.azure.com/api/retail/prices?$filter=productName%20eq%20%27NAT%20Gateway%27%20and%20skuName%20eq%20%27Standard%27%20and%20armRegionName%20eq%20%27Global%27)
- [Central US static IP](https://prices.azure.com/api/retail/prices?$filter=armRegionName%20eq%20%27centralus%27%20and%20productName%20eq%20%27IP%20Addresses%27%20and%20skuName%20eq%20%27Standard%27)

Account for supporting storage, every private endpoint/zone, initializer
compute and egress, any NAT/public-IP charges, source-build charges if
applicable, platform-managed network resources, model tokens, and diagnostics.
Do not claim that network injection or source builds are free without evidence.
The final total and acceptable budget are still open deployment-approval items.

## Go / no-go

Proceed only when:

- Local checks pass and actual runtime/dependency versions are recorded.
- Region/model/quota and required resource providers are confirmed.
- Required permissions and egress are approved.
- The exact Bicep resource inventory and updated cost estimate are accepted.
- An experiment duration, teardown owner, and spend response are recorded.
- The cloud operator understands that a local pass is not a cloud pass.

Stop on identity ambiguity, public SQL resolution, TLS failure, unexpected
permissions, unsupported runtime packages, unapproved resources, or uncertain
resource ownership. Do not repair these by weakening network or TLS controls.
