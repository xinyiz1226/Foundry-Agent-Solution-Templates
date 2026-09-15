# Empty web-host infrastructure

## Scope and approval

[`infra/web-host.bicep`](../infra/web-host.bicep) prepares only a dedicated
Linux Basic B1 App Service Plan and an empty Web App in an existing resource
group. It is not the authenticated cloud workbench or a full azd deployment.

The operator separately approved those two resources in the existing Foundry
project's resource group and region, with the disclosed retained-plan cost.
That approval does not cover a different region/SKU, quota/support requests,
directory applications, managed identities, role assignments, application
code deployment, endpoint enablement, or model calls.

The template creates four ARM records: the plan, the site, and the site's
FTP/SCM basic-publishing-credential policies. The latter are site security
configuration, not additional hosting plans or identity resources.

| Setting | Template value |
| --- | --- |
| Plan | Linux, Basic B1, one instance |
| Runtime configuration | `PYTHON|3.13` |
| Public network access | Disabled |
| HTTPS / minimum TLS | HTTPS-only; site and SCM minimum TLS 1.2 |
| FTP | Disabled |
| FTP / SCM basic publishing credentials | Both disabled |
| Always On | False |
| App code, app settings with credentials, identity, Entra/RBAC grants | Not deployed |

The app may enter its platform default running state during resource
creation. Its public network access is already disabled in the template;
the separate verified stop step below leaves the owned app stopped.
Neither a stopped app nor a blocked public endpoint removes the retained
plan's charges.

## Current outcome: created in West US 2

The creation/readback below records the original empty-host slice.
Subsequent [separately approved identity configuration](web-identity-configuration.md)
added login settings and a narrowly scoped managed identity. The app still
has no deployed workbench code and remains stopped/public-access-disabled.

On September 15, 2026, the operator approved changing only the new web
resources' region to **West US 2**, keeping the existing Foundry resource
group and the previously approved B1 scope. The existing Foundry project
and storage were not moved.

The template from `66db832` passed provider-level what-if in the new region:
four creations for the plan, site and two publishing-policy children;
nine existing resources were ignored, with no modification/deletion.
One incremental deployment then succeeded. Its operations recorded the
four expected creations and a read of the new site.

After verifying the new site's ownership tag, the owned site was stopped.
Readback established:

| Check | Observed value |
| --- | --- |
| Plan | West US 2, Linux (`reserved=true`), Basic B1, capacity 1 |
| Plan readiness | `Ready`, provisioning `Succeeded` |
| Site | West US 2, bound to the owned plan, `Stopped` |
| Public network / HTTPS | `Disabled` / HTTPS-only |
| Runtime / startup | `PYTHON|3.13` / empty startup command |
| TLS | Site and SCM minimum 1.2 |
| FTP / Always On | Disabled / false |
| Basic publishing credentials | Both FTP and SCM `allow=false` |
| Configured site identity | None |
| Public HTTPS request | HTTP 403 while stopped and public access disabled |

The HTTP 403 does not establish Entra authentication or distinguish the
individual effects of stop and network restriction. No application code,
managed identity, directory registration or role grant was deployed, and
no Foundry agent was enabled or model invoked.

**The retained B1 plan now incurs hosting charges even with the site
stopped.** The observed public West US 2 Linux B1 retail rate was USD 0.017
per hour, approximately USD 12.41 at 730 hours, excluding other services,
network, taxes and subscription-specific pricing. This is not a hard cap
or a measured invoice.

Environment-specific names, resource IDs, parameters and detailed
verification remain in private session artifacts. This completes only
the empty-host resource slice, not a deployed workbench or G0.

## Earlier East US attempt: September 15, 2026

The Bicep template compiled successfully with CLI 0.47.16. Proposed plan/site
names were absent in the intended resource group, and the site name was
globally available. **Azure provider validation and provider-level what-if
both failed before any deployment-create request was submitted:**

```text
SubscriptionIsOverQuotaForSku
Current Limit (B1 VMs): 0
Current Usage: 0
Required for this deployment: 1
Minimum requested new limit: 1
```

This occurred for the requested East US deployment. A subsequent scoped
resource inventory returned no resource at either proposed name. **No plan
or Web App was created, so this attempt did not allocate a new billable
hosting plan.** No quota request, role change, application upload, agent
enablement or real model call was performed.

Runtime/region catalog support in the
[earlier preflight](workbench-hosting-preflight.md) did not establish
subscription quota. The operator subsequently chose the successful West US 2
alternative above; no East US quota request was submitted. The quota
guidance below remains applicable if East US is required in a future,
separately approved deployment.

## Resolve the quota gate

The error is from `Microsoft.Web/serverfarms`; do not confuse its B1 workers
with a `Microsoft.Compute` VM-family vCPU quota.

An authorized subscription operator can open the
[Azure portal](https://portal.azure.com), use the global **?** help entry or
**Support + Troubleshooting**, describe the App Service quota failure, and
follow the flow to **Create a support request**. Specify the correct
subscription, App Service/Linux B1, East US, current limit/usage zero, and
requested worker limit at least one. Service-specific form fields can vary;
do not select an unrelated Compute family merely because it appears in the
generic Quotas examples.

Microsoft documents quota adjustments as subscription-management support,
separate from paid technical support, and describes the required
subscription-level roles in its
[support-request guide](https://learn.microsoft.com/en-us/azure/azure-portal/supportability/how-to-create-azure-support-request).
The [quota guide](https://learn.microsoft.com/en-us/azure/quotas/quickstart-increase-quota-portal)
also distinguishes adjustable quotas from those requiring a support request.
Eligibility and approval time are not established by this deployment.

Do not submit a support request or raise quota automatically under the
resource-creation approval. After approval, rerun provider validation and
what-if before creating anything. Keep contact details, ticket identifiers,
environment values and raw tracking IDs outside the public repository.

## Reproduce the controlled deployment

Use explicitly approved names, subscription, tenant, existing resource
group and location. Confirm the resource group against the Foundry project
resource ID rather than creating another group. Never overwrite an
unrelated existing app or plan.

From the repository root, with Azure CLI/Bicep available:

```powershell
$subscriptionId = '<approved-subscription-id>'
$resourceGroup = '<existing-foundry-resource-group>'
$location = '<approved-region>'
$planName = '<new-dedicated-plan-name>'
$webAppName = '<new-globally-unique-web-app-name>'
$ownershipLabel = '<non-secret-unique-approval-label>'
$deploymentName = '<owned-deployment-name>'

az account show --subscription $subscriptionId `
    --query '{subscription:id,tenant:tenantId}' --output json
if ($LASTEXITCODE -ne 0) { throw 'Unable to verify the selected Azure account.' }

az resource list --subscription $subscriptionId --resource-group $resourceGroup `
    --query "[?name=='$planName' || name=='$webAppName'].{name:name,id:id,tags:tags}" `
    --output json
if ($LASTEXITCODE -ne 0) { throw 'Unable to check existing resource ownership.' }
```

Inspect the result and check the Web App's global name availability. For an
initial creation, stop if either name is already owned by another deployment.
On recovery after a partial deployment, first inspect deployment operations
and each existing resource's ownership tag; an ARM deployment is not an
all-or-nothing transaction.

```powershell
$parameters = @(
    "planName=$planName"
    "webAppName=$webAppName"
    "location=$location"
    "ownershipLabel=$ownershipLabel"
)

az deployment group validate --subscription $subscriptionId `
    --resource-group $resourceGroup --mode Incremental `
    --template-file .\information-extraction\infra\web-host.bicep `
    --parameters $parameters
if ($LASTEXITCODE -ne 0) { throw 'Provider validation failed; do not create.' }

az deployment group what-if --subscription $subscriptionId `
    --resource-group $resourceGroup --mode Incremental `
    --template-file .\information-extraction\infra\web-host.bicep `
    --parameters $parameters
if ($LASTEXITCODE -ne 0) { throw 'Deployment preview failed; do not create.' }
```

Review the exact preview: only the approved plan, site and two policy
children may be created. No unrelated resource modification/deletion,
role assignment, identity or application deployment is in scope.

```powershell
az deployment group create --name $deploymentName `
    --subscription $subscriptionId --resource-group $resourceGroup `
    --mode Incremental `
    --template-file .\information-extraction\infra\web-host.bicep `
    --parameters $parameters
if ($LASTEXITCODE -ne 0) { throw 'Inspect partial deployment state before retrying.' }

$actualOwner = az webapp show --subscription $subscriptionId `
    --resource-group $resourceGroup --name $webAppName `
    --query tags.ownership --output tsv
if ($LASTEXITCODE -ne 0 -or $actualOwner -ne $ownershipLabel) {
    throw 'Web App ownership mismatch; do not operate on it.'
}

az webapp stop --subscription $subscriptionId `
    --resource-group $resourceGroup --name $webAppName
if ($LASTEXITCODE -ne 0) { throw 'Owned Web App stop was not confirmed.' }
```

Then read back plan SKU/capacity/Linux status, site plan binding, `Stopped`
state, disabled public access, HTTPS/TLS/runtime settings, both basic
publishing policies, ownership tags, and absence of a configured identity.
Provider success alone is not the complete required final state. An empty,
stopped app is not a successful Streamlit deployment or authorization test.

Retain only the resources approved for retention. Deleting the dedicated
plan later requires an explicit cleanup decision; never delete the shared
resource group, existing Foundry project or storage to clean up this slice.
