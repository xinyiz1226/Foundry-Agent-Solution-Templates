# Business Performance Investigator

**Current deliverable: a minimal private-SQL validation package, not the full
analyst application. No cloud deployment has been verified.**

The planned solution investigates business metric changes without requiring
Fabric or Databricks. This first milestone checks a smaller prerequisite:

```text
Authenticated operator -> public Foundry agent endpoint
                                  |
                       hosted Python SQL probe
                       (actual agent identity)
                                  |
                         delegated VNet subnet
                                  |
                       Azure SQL private endpoint
                                  |
                       reporting.v_pilot_probe

Temporary private initializer -> same SQL endpoint
(separate privileged identity)
```

The probe returns deterministic evidence from one approved view. It does not
accept arbitrary SQL, perform sales analysis, or provide a Web UI.
See [PLAN.md](PLAN.md) for the confirmed full-template scope and later milestones.

The proposed initializer uses an explicit NAT gateway and static public IP for
outbound downloads. These add persistent costs until cleanup; they do not open
SQL publicly. Review this addition and the revised cost subtotal before approval.

## Contents

| Path | Purpose |
|---|---|
| `agent/` | Source-deployed hosted agent, fixed SQL probe, pinned dependencies |
| `infra-bicep/` | Core private-SQL resources and separate initialization deployment |
| `scripts/` | Local validation, preflight, approval-gated lifecycle, cloud evidence validation |
| `tests/` | Local runtime and lifecycle contracts; no live database required |
| `config.example.json` | Non-deployable placeholders; copy and review before use |
| `config.existing-model.example.json` | Reuse an externally managed Azure model deployment without creating or resizing it |
| `docs/deployment-approval.md` | Resources, permissions, cost assumptions, and approval checklist |
| `docs/validation.md` | Local versus cloud checks and failure investigation |

## Prerequisites

For local verification:

- Python 3.13 and a dedicated virtual environment.
- PowerShell 7.2 or newer.
- Standalone [Bicep CLI](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/install).
- Package-download access for the pinned Python dependencies.

Only for a separately approved cloud experiment:

- Azure CLI and Azure Developer CLI, authenticated to the approved tenant.
- `azure.ai.agents` and `azure.ai.projects` azd extensions:
  `azd extension install azure.ai.agents` and
  `azd extension install azure.ai.projects`.
- A subscription/region supporting hosted agents, the chosen model deployment,
  Azure SQL, and private deployment scripts, with sufficient quota.
- Resource creation, role assignment, and managed-identity assignment permissions
  for a **new, dedicated** resource group.
- Permission to inspect the deployed agent's service principal. Scripts do not
  grant tenant directory permissions to work around failed lookups.

The supplied region/model/version are examples, not promises of subscription
availability. Confirm them and cost assumptions before deployment.

## Reuse an existing model

Use `config.existing-model.example.json` for an already-deployed model such as
`DeepSeek-V4-Flash-0731`. Set `modelMode` to `existing`, the exact deployment
name/resource ID, `modelApi` to `chat_completions`, and the shared account's
HTTPS `/openai/v1/` endpoint. Replace the example subscription/operator IDs.
The shared deployment must be in the selected subscription but **outside**
the disposable experiment group. This phase supports account-name endpoints
under `openai.azure.com` or `services.ai.azure.com`, reachable through approved
public Entra-authenticated access; it does not alter shared-account firewalls.

Do not set `modelVersion`, `modelSku` or `modelCapacity` in existing mode:
the model owner controls those settings. Bicep skips model deployment, and
the shared account/model is excluded from experiment ownership and cleanup.
The runtime uses its own managed identity and a refreshing Entra token with
scope `https://ai.azure.com/.default`; it does not retrieve account keys.
The hosted agent still exposes **Responses/2.0.0**. Only its internal model
transport changes to Chat Completions, with at most two calls and at most one
validated SQL tool execution. No automatic API or model fallback is used.

**Shared-model permission is a separate approval.** The newly deployed
agent's actual object ID needs inference access to the shared model account.
The operator's successful login and the new project's default access do not
grant this to the runtime. After verifying that identity, the shared-model
owner can review and run the following command under their authorization:

```powershell
az role assignment create --assignee-object-id '<actual-agent-object-id>' `
    --assignee-principal-type ServicePrincipal `
    --role '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd' `
    --scope '<existing-model-account-resource-id>'
```

This is the documented **Cognitive Services OpenAI User** role for the v1 API;
confirm its accepted scope and actual DeepSeek inference access in the cloud
experiment. The template does not run this command, change shared permissions
or broaden roles automatically. Record any newly created assignment ID and
have the model owner remove only that assignment after the experiment if
appropriate; `cleanup.ps1` does not manage external assignments.
Model calls still consume the shared deployment's capacity and incur its
normal inference charges. See [Azure OpenAI v1](https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle).

## Local-only quickstart

Run from this folder. On Windows, use `py -3.13` if `python` is a Store alias.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements-dev.txt
.\scripts\validate-local.ps1 -BicepPath '<path-to-bicep.exe>'
```

No local validation command provisions Azure resources, logs in, queries the
database, or invokes a paid model.

The local report is written under `.artifacts/`; it explicitly records
`cloudValidation: not_run`. A successful local report is **not** evidence of
working hosted-runtime identity, private DNS, SQL permissions, or cloud cleanup.

## Cloud workflow: approval required

**Do not execute these commands until the resource, permission, cost, and cleanup
review in [deployment approval](docs/deployment-approval.md) is complete.**
The `-ApproveAzureChanges` switch records operator intent; it is not a substitute
for organizational authorization.

Prepare local configuration before selecting authentication or deploying:

```powershell
Copy-Item .\config.example.json .\config.local.json
# For an existing model, copy config.existing-model.example.json instead.
# Replace every placeholder; confirm the model, region, capacity and operator ID.
```

### Optional isolated Azure CLI authentication

If tenant-explicit azd login works but its default-context token acquisition
fails, do not repeatedly provision resources or change Conditional Access
policy. The installed azd version can require default user claims while
resolving a subscription's tenant, before applying that tenant.

For an already signed-in **user**, explicitly select azd's supported Azure CLI
delegation in a project-isolated profile:

```powershell
.\scripts\use-azure-cli-auth.ps1 -ConfigPath .\config.local.json
```

The helper verifies that Azure CLI already selects the approved subscription
and that its signed-in user object ID matches `operatorPrincipalId`. It does not switch accounts,
log in, change tenant policy, or change global azd configuration. It sets
`AZD_CONFIG_DIR` to the ignored `.artifacts\azd-cli-auth` directory and enables
`auth.useAzCliAuth` there. This is an explicit operator choice, not an automatic
fallback after an authentication failure.
It affects operator CLI authentication only; the hosted agent still uses its
own managed identity, never the operator's credentials.

Run the helper in **each new PowerShell process**, then run preflight and the
lifecycle commands in that same process. If preflight reports missing
extensions in the isolated profile, install the reviewed versions there:

```powershell
azd extension install azure.ai.agents --version 1.0.0-beta.15 --no-prompt
azd extension install azure.ai.projects --version 1.0.0-beta.10 --no-prompt
.\scripts\preflight.ps1 -ConfigPath .\config.local.json -CheckAzure
```

Keep the entire profile out of Git. Closing the shell ends its process-local
selection; it does not log out other sessions. Authentication failures must
still be resolved through the tenant's approved sign-in process.

### Staged deployment

```powershell
.\scripts\preflight.ps1 -ConfigPath .\config.local.json -CheckAzure

.\scripts\deploy.ps1 -ConfigPath .\config.local.json -Stage Provision -ApproveAzureChanges
.\scripts\deploy.ps1 -ConfigPath .\config.local.json -Stage Agent -ApproveAzureChanges
```

Inspect the deployed agent's identity, not the Foundry project's identity:

```powershell
azd ai agent show sql-probe -e '<environmentName>' --output json
.\scripts\deploy.ps1 -ConfigPath .\config.local.json -Stage Initialize `
    -AgentPrincipalId '<actual-agent-object-id>' -ApproveAzureChanges
.\scripts\validate-agent.ps1 -ConfigPath .\config.local.json -ApproveAzureChanges
```

The initializer checks the supplied object ID against agent metadata, resolves
its application/client ID, and creates the fixed database user
`bpi_probe_agent`. These identifiers are different: the SQL SID for this
service principal is based on its application/client ID.

SQL public access stays disabled. Initialization runs in the private execution
environment, never by temporarily allowing public access or all Azure services.
The new probe server's Entra administrator is the separate initializer identity.
It must not be used by the agent and remains privileged until the isolated
experiment is deleted.

Do not run `azd up` or `azd down` for this package. The stage scripts own
provisioning, explicit approval, resource inventory, and deletion guards.
Existing Azure SQL adoption is a later full-template milestone; these probe
scripts intentionally reject existing resource groups.

## Cleanup and ownership

`cleanup.ps1` now performs ordered, resumable teardown: project Capability
Hosts, account Capability Hosts, project, account, service-managed subnet-link
release, initializer network associations, then the remaining resource group.
It waits for asynchronous deletion instead of treating an accepted request
as completion. Never start by deleting the group or directly changing
`legionservicelink`.

After preserving evidence, preview the owned targets without changing Azure
or local ownership state, then execute with explicit approval:

```powershell
.\scripts\cleanup.ps1 -ConfigPath .\config.local.json `
    -ConfirmResourceGroup '<exact-resource-group-name>' -WhatIf

.\scripts\cleanup.ps1 -ConfigPath .\config.local.json `
    -ConfirmResourceGroup '<exact-resource-group-name>' -ApproveAzureChanges
```

Cleanup checks the subscription, exact group name, ownership tags, local state,
and resource inventory before requesting confirmation. It refuses unknown
resources, unexpected projects and mismatched account incarnations; it never
adopts customer groups. State is stored in the ignored
`.artifacts/<environment>/state.json`; retain it for cleanup and diagnosis.
Timeouts are explicit failures, not cleanup success. Each wait operation
defaults to 1800 seconds with 15-second polling, configurable using
`-WaitTimeoutSeconds` (1-3600) and `-PollIntervalSeconds` (1-60).
This is not an overall experiment-duration limit. Rerun the same command after
reviewing a timeout; recorded progress does not replace fresh Azure checks.

If provisioning failed or the inventory differs, inspect Azure and the state
before proceeding. Do not edit the state just to bypass a guard.
Temporary execution containers may be removed by deployment-script retention;
their supporting storage, NAT/IP and private-network resources still need
experiment cleanup.
The script does not delete Entra directory objects or external role
assignments. Soft-deleted accounts are retained by default. Permanent purge
requires separate `-ApproveFoundryPurge` authorization and verified account
incarnation evidence; `-ApproveAzureChanges` alone never approves purge.
If the group is already absent, the script is always read-only, even with
purge approval: it reports the exact retained soft-deleted account rather
than claiming nothing remains. Purging that residual is a separately reviewed
operation, not performed by the absent-group path.
See [teardown requirements](docs/deployment-approval.md#ordered-teardown-required)
for retention and recovery boundaries.

## Security and scope

- Entra authentication and explicit approved-view permissions, not SQL passwords.
- Metadata visibility on the synthetic base table permits permission checks,
  without granting SELECT on that table.
- No database-wide reader role, runtime DDL, DML, or unrestricted query input.
- TLS certificate/hostname validation is required.
- No project-identity or public-network fallback.
- No model-generated claims used as proof of query execution.
- Local state and reports are excluded from Git. Never commit tokens, connection
  secrets, customer data, or raw authentication responses.

The full analyst application, AdventureWorksDW import, adaptive investigation,
App Service login UI, and existing-database path are **not implemented in this
milestone**. Their requirements remain in the plan.
