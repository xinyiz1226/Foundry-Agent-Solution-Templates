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

```powershell
Copy-Item .\config.example.json .\config.local.json
# Replace every placeholder; confirm the model, region, capacity and operator ID.
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

After preserving the needed evidence:

```powershell
.\scripts\cleanup.ps1 -ConfigPath .\config.local.json `
    -ConfirmResourceGroup '<exact-resource-group-name>' -ApproveAzureChanges
```

Cleanup checks the subscription, exact group name, ownership tags, local state,
and resource inventory before requesting confirmation. It refuses unknown
resources and never adopts customer groups. State is stored in the ignored
`.artifacts/<environment>/state.json`; retain it for cleanup and diagnosis.

If provisioning failed or the inventory differs, inspect Azure and the state
before proceeding. Do not edit the state just to bypass a guard.
Temporary execution containers may be removed by deployment-script retention;
their supporting storage, NAT/IP and private-network resources still need
experiment cleanup.
The script does not delete Entra directory objects or purge soft-deleted
Foundry resources. Review any retained identities and name-reuse constraints
with the operator.

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
