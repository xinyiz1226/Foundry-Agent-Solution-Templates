# G0 storage deployment

## Scope

[`infra/storage.bicep`](../infra/storage.bicep) provisions a dedicated storage
slice for G0 validation. It does not deploy the full workbench, a hosted
workflow, a model, or an azd environment. The complete Bicep/azd deployment
path remains part of the implementation plan.

The template targets an existing resource group and creates:

- One StorageV2 account using Standard_LRS and the Hot access tier.
- The default Blob service, with seven-day blob and container soft deletion.
- One private container.
- A Storage Blob Data Contributor assignment for one operator, scoped to that
  container rather than the account, resource group, or subscription.

HTTPS and TLS 1.2 are required. Anonymous Blob access and Shared Key
authorization are disabled. OAuth authentication is the default; public
network connectivity remains enabled and still requires authorization.
Encryption uses Microsoft-managed keys.

This is not private networking, customer-managed encryption, WORM storage,
backup/DR, or a production certification. The adapter's create-only protocol
does not prevent an independently authorized administrator from modifying
resources or data.

## Prerequisites and ownership

Use an explicitly approved subscription, existing resource group, location,
new globally unique account name, and operator identity. The deploying
identity needs permission to deploy resources and assign the container's
data role. Storage Blob Data Contributor alone does not grant infrastructure
deployment or role-assignment permissions.

The operator object ID must belong to the **target tenant**. A user's home
tenant object ID and guest object ID in the subscription's tenant may differ.
Confirm the selected subscription before looking up the operator; a wrong
object ID can leave storage created but the role assignment failed.

Resource names and parameters for a particular environment belong in an
untracked local/private location. Never commit account keys, access tokens,
SAS URLs, or existing environment state.

## Validate and provision

The following PowerShell commands are operator actions, not automatic setup.
Replace every placeholder and review costs and scope first. Run from the
repository root with Azure CLI and Bicep available:

```powershell
$subscriptionId = '<approved-subscription-id>'
$tenantId = '<subscription-tenant-id>'
$resourceGroup = '<existing-resource-group>'
$accountName = '<new-globally-unique-account-name>'
$location = '<approved-region>'
$containerName = 'information-extraction'

az login --tenant $tenantId
az account set --subscription $subscriptionId
az account show --query '{subscription:id,tenant:tenantId}' --output json

$operatorId = az ad signed-in-user show --query id --output tsv
if ($LASTEXITCODE -ne 0) { throw 'Unable to resolve the target-tenant operator.' }

az storage account check-name --name $accountName --output json
az bicep version
```

Do not proceed if the selected tenant/subscription is wrong or the account
name is already taken. Install Bicep with `az bicep install` if the version
check reports that it is missing.

Preview the resources in incremental mode. Existing unrelated resources in
the group must not be modified or removed:

```powershell
$parameters = @(
    "storageAccountName=$accountName"
    "location=$location"
    "containerName=$containerName"
    "operatorPrincipalId=$operatorId"
)

az deployment group validate `
    --subscription $subscriptionId --resource-group $resourceGroup `
    --template-file .\information-extraction\infra\storage.bicep `
    --parameters $parameters
if ($LASTEXITCODE -ne 0) { throw 'Storage deployment validation failed.' }

az deployment group what-if `
    --subscription $subscriptionId --resource-group $resourceGroup `
    --mode Incremental `
    --template-file .\information-extraction\infra\storage.bicep `
    --parameters $parameters
if ($LASTEXITCODE -ne 0) { throw 'Storage deployment preview failed.' }
```

After reviewing and authorizing the preview, create the resources:

```powershell
az deployment group create `
    --name information-extraction-storage-g0 `
    --subscription $subscriptionId --resource-group $resourceGroup `
    --mode Incremental `
    --template-file .\information-extraction\infra\storage.bicep `
    --parameters $parameters
if ($LASTEXITCODE -ne 0) { throw 'Inspect deployment operations before retrying.' }
```

An ARM deployment is not an all-or-nothing transaction across resources. If a
role assignment fails, inspect the resources already created and correct the
principal or permission issue. Do not enable keys or anonymous access to
work around a failure. With the same parameters, incremental redeployment
can finish the intended resources; it is not a cleanup operation.

## Verify the result

```powershell
az storage account show `
    --subscription $subscriptionId --resource-group $resourceGroup `
    --name $accountName `
    --query '{state:provisioningState,sku:sku.name,https:enableHttpsTrafficOnly,tls:minimumTlsVersion,anonymous:allowBlobPublicAccess,sharedKey:allowSharedKeyAccess,publicNetwork:publicNetworkAccess}' `
    --output json

az storage container show `
    --account-name $accountName --name $containerName `
    --auth-mode login `
    --query '{name:name,publicAccess:properties.publicAccess}' `
    --output json
```

Require successful provisioning, Standard_LRS, HTTPS enabled, TLS1_2,
`allowBlobPublicAccess=false`, and `allowSharedKeyAccess=false`. The container
must have no anonymous access level. Verify the role assignment is scoped to
the intended container and tenant-local operator.

Role changes can take time to propagate. A denied data request is a visible
failure; retry only after inspecting role scope/identity and allowing bounded
propagation time. Never fall back to an account key. An unauthenticated
container request must fail with an authentication/public-access denial,
not succeed or merely fail because of a network error.

These checks establish infrastructure settings and access, not application
checkpoint correctness or Foundry-hosted recovery.

## Cost, retention, and cleanup

Storage capacity, transactions, retained soft-deleted data, and possible
transfer costs are billable. G0 samples are small, but no zero-cost guarantee
is made. This deployment does not introduce a recurring compute job.

Keep the account only while needed and track its ownership. A validation
prefix can be retained as explicit evidence, but must not be mistaken for
production data or a scheduled job. Soft deletion is a limited recovery
feature and is not a backup plan.

**Never delete a shared resource group to clean up this template.** After
separate authorization, remove only template-owned data/resources. Deleting
the dedicated account removes its data and child container; do not rely on
blob soft deletion to recover an account deletion.

For an explicitly authorized account cleanup:

```powershell
az storage account show `
    --subscription $subscriptionId --resource-group $resourceGroup `
    --name $accountName --query '{id:id,tags:tags}' --output json

# Review the exact account and its ownership before confirming deletion.
az storage account delete `
    --subscription $subscriptionId --resource-group $resourceGroup `
    --name $accountName
```

Verify the account and its scoped role assignment no longer exist and that
unrelated group resources remain intact. No account cleanup is implied by a
successful deployment or smoke command.

## Observed infrastructure validation

On September 14, 2026, the storage slice compiled with Bicep 0.47.16, passed
ARM validation, and was deployed incrementally to an operator-approved
existing resource group. What-if showed only new storage resources and the
new container-scoped role assignment; unrelated resources were ignored.

The first role assignment used an object ID from the wrong tenant and failed
with `PrincipalNotFound`; storage itself had already been created. Selecting
the intended subscription and using its tenant-local operator object ID
allowed incremental deployment to complete. No access control was weakened.

Management reads confirmed the stated storage settings. Entra-authenticated
container inspection succeeded. An unauthenticated data-plane request using
Storage API version `2023-11-03` returned HTTP 401 with
`NoAuthenticationInformation`.

The dedicated account is intentionally retained for subsequent G0 work;
cleanup has not been exercised. Environment-specific identifiers and
parameters are not included here.

The subsequent [application storage smoke](blob-store.md#observed-live-storage-evidence)
also succeeded against this container: fresh processes restored committed
progress, explicitly resumed a controlled failure, and replayed historical
requests without new model work. That probe used a synthetic model and Entra
CLI user identity, not Foundry hosting or a managed identity. Its small
synthetic ledger prefix is intentionally retained with the account.
