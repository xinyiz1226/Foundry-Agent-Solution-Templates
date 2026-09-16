# Business Performance Investigator

**Current deliverables: a deterministic baseline, a bounded adaptive engine
with offline replay evaluation, and a verified private-SQL connectivity package,
not the full analyst application.
Hosted-agent model access, private SQL, controlled same-session compute resume
and the fixed analytical baseline have been verified in Azure. Real DeepSeek
adaptive investigation remains incomplete: the latest run completed comparison
and territory discovery, then rejected an invalid filter before product
drilldown.**

The local follow-up now constrains filters to discovered string IDs and allows
one budgeted correction in the hosted path. Its
[offline correction behavior](docs/adaptive-evaluation.md#optional-single-filter-correction)
is covered locally; it has not changed the failed live acceptance outcome.

Cloud experiments are disposable and require verified resource teardown and
revocation of their exact temporary model permissions. Soft-deleted Foundry
accounts are retained without purge; actual billed cost remains unknown.
See the [live experiment record](docs/cloud-analysis-validation.md#recorded-live-experiment-2026-09-16)
for outcomes and cleanup evidence. This is not yet a customer-ready analyst app.

The solution investigates business metric changes without requiring Fabric
or Databricks. Start with the [local analysis baseline](docs/baseline.md) for
metric comparisons, reconciled territory/product changes and reproducible
evidence. It creates no cloud resources and calls no model.
The [adaptive evaluation](docs/adaptive-evaluation.md) adds bounded model-selected
investigation and a reproducible replay comparison. The
[analytical hosted service](docs/hosted-analysis.md) and
[private sample initializer](docs/analysis-initialization.md) support separately
approved cloud experiments; replay is not evidence of live model quality.

The separately deployed connectivity probe checks a smaller prerequisite:

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

The initializer uses an explicit NAT gateway and static public IP for
outbound downloads. These add persistent costs until cleanup; they do not open
SQL publicly. Review this addition and the revised cost subtotal before approval.

## Contents

| Path | Purpose |
|---|---|
| `agent/` | Source-deployed hosted agent, fixed SQL probe, pinned dependencies |
| `analysis/` | Shared metrics/tools, adaptive loop, comparison harness and private hosted SQL session |
| `data/` | Pinned official AdventureWorksDW provenance, single-currency scope and license |
| `evaluation/` | Hand-worked synthetic ledger and hash-pinned report configuration |
| `sql/analysis-view.sql` | Proposed matching Internet Sales view; not deployed by the probe lifecycle |
| `infra-bicep/` | Core private-SQL resources and separate initialization deployment |
| `scripts/` | Local validation, preflight, approval-gated lifecycle, cloud evidence validation |
| `tests/` | Local runtime and lifecycle contracts; no live database required |
| `config.example.json` | Non-deployable placeholders; copy and review before use |
| `config.existing-model.example.json` | Reuse an externally managed Azure model deployment without creating or resizing it |
| `docs/deployment-approval.md` | Resources, permissions, cost assumptions, and approval checklist |
| `docs/validation.md` | Local versus cloud checks and failure investigation |
| `docs/baseline.md` | Business-analysis workflow, twelve reference cases and execution boundaries |
| `docs/adaptive-evaluation.md` | Bounded adaptive investigation and fair replay comparison |
| `docs/hosted-analysis.md` | Analytical service, private snapshot contract and live-validation gaps |
| `docs/cloud-analysis-validation.md` | Local preparation and separately authorized analytical cloud acceptance |

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
  Azure SQL, and private Azure Container Instances, with sufficient quota.
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
transport changes to Chat Completions. The connectivity probe uses at most two calls and at most one
validated SQL tool execution. No automatic API or model fallback is used.
The separate analytical service uses the limits documented in
[adaptive evaluation](docs/adaptive-evaluation.md).

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
`bpi_probe_agent`. Object ID and application/client ID are distinct concepts,
although a Foundry `ServiceIdentity` can report the same GUID for both.
Always use the directory-verified application/client ID for the SQL SID.

Initialization runs directly in a private ACI using a digest-pinned Microsoft
Azure PowerShell 14.0 image. It does not use Deployment Scripts or mount
Azure Files, because that service requires a trusted-services storage bypass.
The initializer downloads pinned `SqlServer` 22.4.5.1, uses its own managed
identity, and emits a bounded completion marker after the SQL transaction.
The lifecycle checks its identity, subnet, image, exit status and marker
before recording initialization as successful. A 15-minute execution wait
timeout stops the owned initializer compute and reports failure.
An existing completed initializer is inspected, not rerun; an explicit
`-RetryInitialization` is required to redeploy it, and in-flight work cannot
be restarted through that flag.

The core template currently retains the earlier private initialization
storage/file endpoint/DNS resources for compatibility with existing ownership
state. Direct ACI does not consume them; they remain private, owned, billable
until cleanup, and included in the inventory.

SQL public access stays disabled. Initialization runs in the private execution
environment, never by temporarily allowing public access or all Azure services.
The new probe server's Entra administrator is the separate initializer identity.
It must not be used by the agent and remains privileged until the isolated
experiment is deleted.

Do not run `azd up` or `azd down` for this package. The stage scripts own
provisioning, explicit approval, resource inventory, and deletion guards.
Existing Azure SQL adoption is a later full-template milestone; these probe
scripts intentionally reject existing resource groups.

### Same-session resume validation

The default validator creates a new session. To test recovery of an existing
one, preserve its ID, stop **only that session** using `azd ai agent sessions
stop`, verify that it becomes `idle`, and invoke:

```powershell
.\scripts\validate-agent.ps1 -ConfigPath .\config.local.json `
    -SessionId '<verified-probe-session-id>' -ApproveAzureChanges
```

This reuses the session with a fresh conversation. Verify that the same
session returns to `active` without a changed creation timestamp and that
the SQL evidence passes again. Controlled stop/resume does not prove the
platform's natural idle-timeout behavior.

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
The direct initializer stops after completion but remains an owned container
resource until cleanup. Its supporting NAT/IP and private-network resources,
plus any legacy deployment-script/storage resources, also need cleanup.
Ordered cleanup validates the exact terminal initializer before deleting it,
then waits for container absence and safe subnet teardown before detaching NAT.
Running, unknown or mismatched containers are rejected. A failed legacy
Deployment Scripts resource is allowed only as terminal work, not bypassed.
An exact owned initializer `acisal` may remain after ACI deletion. Only when
its identity/type/state match, `allowDelete` is Boolean true, and no execution
or other initializer associations remain may normal network/group deletion
be attempted. All other SALs remain blockers. The script never directly edits
SALs or removes the ACI delegation; Azure rejection still means incomplete cleanup.
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

The full analyst application, loading AdventureWorksDW into Azure SQL, adaptive investigation,
App Service login UI, and existing-database path are **not implemented in this
milestone**. Their requirements remain in the plan.
