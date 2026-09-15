# Minimal experiment: deployment approval

Status: **second approved experiment passed real model/private-SQL and controlled same-session resume validation; temporary model access revoked and active resource group deleted; soft-deleted accounts retained, actual cost unknown**.

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

The operator approved the USD 10 spending-response threshold, maximum 24-hour
experiment, immediate cleanup, and new-agent shared-model access on 2026-09-15.
The threshold is not a hard billing cap. Subscription/tenant and operator
IDs were verified and retained only in ignored local preflight artifacts.
The operator subsequently authorized reuse of an existing DeepSeek Flash model
and the next step, SQL provider registration. `Microsoft.Sql` is now registered.
The subsequent approved resource deployment and its blockers are recorded below.
At that first preparation checkpoint, no shared-resource role assignment or
inference call had been performed. The second experiment below supersedes
the earlier runtime-validation status.

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

### Pre-deployment read-only findings, 2026-09-15

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

**Gates at that checkpoint:** select the validated isolated azd profile and review the
retained soft-deleted account/name and next experiment scope before another
deployment. Actual runtime identity and shared-model access were unverified.
Read-only availability and quota checks do not reserve capacity or prove the
runtime works.

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
performed at that checkpoint; real Flash tool-call compatibility and
authorization subsequently passed in the second experiment.

The local evidence and configuration are under `.artifacts/preflight/`.
The chat approval is recorded separately in `experiment-approval.json`;
deployment ownership state is under `.artifacts/<environment>/state.json`.
No model inference or shared-model permissions changes were run.

### First approved cloud attempt, 2026-09-15

Central US infrastructure provisioning succeeded. Agent deployment initially
failed because Azure CLI returned output names such as
`azurE_AI_PROJECT_ENDPOINT`, while the JSON-backed lookup was case-sensitive.
The lookup now accepts one case-insensitive match and rejects ambiguous keys;
the original persisted deployment state passes the corrected lookup.

The subsequent `azd deploy` failed with `AADSTS530036`: the refresh token was
rejected by Conditional Access authentication-flow checks. Tenant-explicit
ARM and Foundry token acquisition succeeds, but default-context ARM token
acquisition fails with the same error. Setting `AZURE_TENANT_ID` in the azd
environment did not prevent the deployment failure. The effective deployment
login context was unresolved at that checkpoint; do not describe this as all
tenant-scoped authentication failing or circumvent the tenant's policy.

Preflight now checks actual azd token acquisition for ARM and Foundry in both
the configured-tenant and default contexts, not just cached login status.
Tokens are discarded, not printed or saved. Native command errors preserve
safe `AADSTS` codes without copying arbitrary token-bearing output.

Immediate cleanup was attempted, but bulk resource-group deletion raced
Foundry service cleanup. SQL, private endpoints/DNS, initializer storage and
identity were removed. After verifying ownership and the exact initializer
subnet association, its NAT was detached and the NAT/public IP were deleted.
The account and account-level Capability Host subsequently completed deletion,
and Azure released `legionservicelink`. After the new guards passed, deletion
of the entire active experiment resource group was confirmed at
**2026-09-15 07:45:14 UTC**. The 24-hour fallback automation was then cleared.
The exact new Foundry account remains soft-deleted; permanent purge was not
approved or performed. No shared model resource or external role was changed.
The post-experiment Cost Management query returned HTTP 429, so final billed
cost is unknown, not zero.
That first attempt produced no successful hosted-agent invocation, SQL
initialization, runtime identity validation, or idle/resume result.

### Authentication-context resolution

The exact installed azd 1.34.0 implementation explains the failure path:
[token tenant selection](https://github.com/Azure/azure-dev/blob/127491451b9940e3ca7e5faf03f107b4f9442eac/cli/azd/cmd/auth_token.go)
resolves the subscription before selecting its user-access tenant.
[Subscription lookup](https://github.com/Azure/azure-dev/blob/127491451b9940e3ca7e5faf03f107b4f9442eac/cli/azd/pkg/account/subscriptions_manager.go)
first calls `ClaimsForCurrentUser(ctx, nil)`, which requires the default
credential. Explicit `--tenant-id` avoids that lookup. Setting
`AZURE_TENANT_ID` and `AZURE_SUBSCRIPTION_ID` alone still reproduced the failure.

The explicit resolution uses the
[supported `auth.useAzCliAuth` mode](https://github.com/Azure/azure-dev/blob/127491451b9940e3ca7e5faf03f107b4f9442eac/cli/azd/pkg/auth/manager.go)
in a new project-isolated `AZD_CONFIG_DIR`. The Azure CLI user object,
subscription and tenant were verified against the approved operator before
selecting the profile. No identities, global azd configuration, Conditional
Access policy or shared-model permissions were changed.

Both configured-tenant and default ARM/Foundry token acquisition now pass in
that explicit profile, and the complete existing read-only preflight passed.
The global/native azd context was not repaired or silently replaced.
Use [the opt-in helper](../README.md#optional-isolated-azure-cli-authentication)
in every new shell to select the validated profile. No resources were
redeployed or models invoked to validate this authentication resolution.

### Second approved experiment

The operator explicitly authorized continuation on 2026-09-15 at 08:18:30 UTC.
A separate, unused environment/resource group was selected, with the same
USD 10 stop-response threshold, maximum 24-hour duration, immediate cleanup
and exact new-agent inference-role scope. Existing model settings were not
changed. Neither the old nor new Foundry account was approved for purge.

Infrastructure and hosted-agent deployment succeeded after exporting the
extension's canonical `FOUNDRY_PROJECT_ENDPOINT`. Actual agent metadata and
directory `ServiceIdentity` object/application IDs were verified before
granting one tracked Cognitive Services OpenAI User assignment.

Private Deployment Scripts rejected the storage firewall configuration before
SQL execution. Its [documented private setup](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/deployment-script-vnet-private-endpoint)
requires an `AzureServices` bypass. The approved no-bypass policy was preserved:
the bootstrap instead used direct private ACI in the same approved initializer
subnet, UAMI and NAT footprint, with a digest-pinned Microsoft PowerShell image.
No public SQL access, trusted-services bypass or inbound public endpoint was
enabled. Container termination, exit code and exact SQL completion evidence
were verified. Legacy storage/file endpoint/DNS and the failed deployment
script remain owned resources for cleanup, not dependencies of direct ACI.

Both the first hosted invocation and a controlled stop/idle/resume of the exact
same session passed actual DeepSeek inference, private SQL, TLS, agent SID,
fixture and checked least-privilege assertions. Natural automatic idle timeout
was not tested. See [runtime evidence](validation.md#second-approved-cloud-experiment-2026-09-15).
The session was stopped again. The one newly created shared-model role was
revoked and its absence verified; no pre-existing assignment was removed.

Active resource-group absence was independently verified at **10:25 UTC**,
along with absence of the exact temporary model assignment. The 24-hour
fallback was cleared only after those checks. No purge has been performed
and final billing is unknown.
The project and active account have been confirmed absent. The 30-minute
network wait subsequently timed out; inspection found no Foundry SAL, only
the initializer's explicitly deletable ACI `acisal`. The corrected cleanup
guard distinguishes this exact residual from blocking links. A guarded retry
completed normal owned-resource deletion without modifying the SAL directly.
No direct SAL mutation or account purge is authorized.
The final local poll encountered an empty-inventory error after resources
were removed. An independent `az group exists` returned `false`, and a fresh
read-only cleanup preview confirmed group absence and retained soft deletion.
The older lifecycle state is preserved rather than rewritten to hide the
polling failure; separate completion evidence records verified cloud absence.
The empty-array polling error is now fixed with entrypoint regression
coverage; no resource recreation or additional cloud deletion was needed.
An unexpected capability-host 404 envelope was corroborated by a successful
empty parent list before resuming. Cleanup now handles that precise case
without interpreting arbitrary `UserError` responses as absence.

## Approval record

| Decision | Required value |
|---|---|
| Approver and approval date | Operator approval in chat, 2026-09-15; local approval record retained |
| Subscription, tenant, and operator principal | Verified for read-only checks; actual IDs remain in ignored local artifacts |
| New resource group and environment | Dedicated experiment group was created with ownership tags and an inventory; no pre-existing group was adopted |
| Region | Central US explicitly selected for new resources; existing shared model remains in East US |
| Model, version, deployment SKU/capacity | Existing DeepSeek Flash selected; no new model deployment or capacity change |
| Shared-model runtime access | Actual new agent identity verified; one approved temporary inference assignment created, used and revoked; absence verified |
| Experiment duration and cleanup owner | Current session executes and verifies immediate cleanup; maximum 24 hours from approval, deadline in ignored record |
| Spending limit and response to threshold | USD 10 stop-response threshold approved; billing delays mean this is not a hard cap |
| Required directory/resource permissions | Broad management access and basic directory lookup observed; no automatic tenant consent or provider registration |
| Required package/image egress | Reviewed initializer/source-build egress only; private SQL is not zero-internet execution |

## Ordered teardown required

Do not begin another teardown with bulk group deletion. `cleanup.ps1` now
automates the guarded order using this probe's recorded resource IDs. Use the
[repository's Foundry cleanup sequence](../../private-network-hosted-agent/docs/cleanup.md#supported-manual-order)
as a troubleshooting reference, with **this probe's** IDs and ownership checks.
Do not run that other template's script or adopt its environment.

Delete and verify absence of project Capability Hosts before account
Capability Hosts, then projects and the account. If a resource is already
`Deleting`, observe its progress rather than repeatedly issuing deletion.
Account deletion and subnet-link release are separate asynchronous operations.
Never directly delete or patch a service association link.

This package does not implicitly purge soft-deleted Foundry accounts or
delete directory objects. Permanent purge requires separate
`-ApproveFoundryPurge` authorization and matching recorded account-incarnation
evidence. Do not fabricate missing metadata to permit purge.
Purge also requires matching soft-account ownership tags and creation time,
plus verified active-account absence. The already-absent-group path is always
read-only, even when purge approval is supplied; it reports rather than
removes retained soft-deleted resources.
Do not claim complete teardown while residual Foundry resources or links
remain; retain the evidence and escalate stalled platform cleanup.

Only after active Foundry accounts and blocking subnet service associations are absent
can `cleanup.ps1` delete the remaining owned group. It checks each stage,
observes already-`Deleting` resources, and bounds waits with visible progress.
The timeout is per wait operation, not an overall experiment deadline;
operators must still enforce their approved duration and spending response.
The initializer NAT association is removed only after verifying its exact
owned subnet/NAT IDs and that no initializer work remains.
For direct ACI, cleanup verifies the recorded/planned ID, ownership, identity,
subnet, image, private topology and terminal state before requesting deletion.
It confirms both container absence and safe subnet teardown before detaching NAT;
active, unknown or mismatched execution is not treated as safe to remove.
The sole allowed residual is the exact owned initializer ACI `acisal` with
Boolean `allowDelete: true`, matching linked service and successful state,
expected delegation, and no containers, active work, network profiles, IP
configurations or other initializer associations. Checks repeat immediately
before mutations. This permits an ordinary platform-enforced deletion attempt,
not direct SAL/delegation editing or a claim that deletion must succeed.

`-WhatIf` is read-only for Azure and local ownership state. The absent-group
path reports residual soft-deleted accounts explicitly. No shared-model
resource, external role assignment, or directory identity is part of teardown.
The implementation passed offline lifecycle regressions, and a real
`-WhatIf` against the already-deleted experiment reported the retained account
without requesting purge or changing state. The second experiment now
requires the full guarded teardown, including its completed direct ACI and
failed legacy deployment-script resource.

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
| Private initialization storage/file endpoint/DNS | Legacy resources still provisioned by the core template; unused by direct ACI, owned and charged until cleanup |
| Direct private ACI | Temporary SQL bootstrap with digest-pinned image and pinned module; completion evidence required |
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
These resources were explicitly approved and deployed for the bounded
experiments; future deployments still require separate approval.

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
This authentication path passed the second live probe. Reject a missing or
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
The bounded experiments have an approved USD 10 stop-response threshold, not
a hard cap. Final billed cost remains unknown: the second experiment's scoped
Cost Management query also returned HTTP 429. Its group-only query would not
include inference charged to the shared model account. Future deployments
require their own scope and spending approval.

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
