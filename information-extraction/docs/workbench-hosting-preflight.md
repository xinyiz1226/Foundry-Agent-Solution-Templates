# Selected hosting architecture: read-only preflight

**Observed:** September 15, 2026. The operator selected the
[App Service / Entra / managed-identity architecture](workbench-hosting-auth-plan.md).
This round read resource metadata, runtime catalog entries, role definitions
and assignments, the current operator's identity/ARM permissions, and public
retail pricing. It created no resources, changed no permissions, invoked no
agent work or model, and read no Blob document contents.

Environment-specific resource names, tenant/subscription/principal IDs and
the detailed inventory remain in private session artifacts, not this
contribution.

## Observed prerequisites

| Check | Observation | What it does not prove |
| --- | --- | --- |
| Existing scoped resource group | No `Microsoft.Web/sites` or `Microsoft.Web/serverfarms` resources were listed. | There may be reusable plans elsewhere; the subscription was not broadly inventoried for web resources. |
| Microsoft.Web provider | Registered. | Resource creation permission, policy approval, regional capacity or quota. |
| Linux runtime catalog | `PYTHON|3.13` advertised as Active. | Successful dependency installation or application startup in the target environment. |
| Linux B1 location catalog | East US advertised. | Current allocatable capacity or subscription quota. |
| Endpoint role definition | Foundry Agent Consumer exists and grants only the agent endpoint `interact/action` data action. | A role has been assigned to a web identity; no such identity was created. |
| Operator identity and ARM permissions | The signed-in tenant-local object was resolved; resource-group permissions include ARM `actions: ["*"]`. | Entra app registration/admin-consent rights, absence of deny assignments or policy restrictions, or consent to use these powers. |
| Existing synthetic agent | Its metadata still reports `disabled`. | A new version, protocol negotiation, authentication flow or live invocation has been verified. |
| Dedicated storage account/container | Succeeded, Standard_LRS, HTTPS-only, TLS 1.2, anonymous and Shared Key access disabled; container public access `None`. | Network-private storage: the account's public network endpoint remains enabled. |

The CLI's runtime-list response used structured records, not a list of
strings; the successful query selected the Python runtime's `config` and
`support` fields. Treat this as catalog evidence, not a deployment result.

## Scoped authorization observations

The agent-scope assignment query with inheritance returned nine active
assignment rows. Directory display-name/group-member expansion was disabled.
Role definitions were then read by their exact IDs.

- The operator has Foundry User grants at subscription/resource-group scope
  and Foundry Owner at the account scope. Those roles include broad
  Cognitive Services data actions, so this operator is not a suitable
  unauthorized-caller test identity.
- Two existing service principals have Cognitive Services OpenAI User at
  account scope. Its observed permission definition does not include
  `Microsoft.CognitiveServices/accounts/AIServices/endpoints/interact/action`.
  Their presence alone therefore does not establish an agent-invocation
  bypass.
- Subscription-level Owner assignments to a user and groups, and Contributor
  to a service principal, remain administrative trust boundaries. Do not
  automatically label those management grants as direct data-plane invoke
  permissions, or ignore their ability to change resources/access.

The inspected active assignments did not establish an additional ordinary
caller with the endpoint-interact permission. **This is not a complete
effective-access audit.** Group membership, eligible/PIM access, deny
assignments, all administrative paths, future grants, and a real
unauthorized-caller test were not established.

The existing Foundry project is consequently still a reuse candidate.
There is no evidence from this limited inventory that immediately requires
a new Foundry account/project, but no claim that shared-project isolation
has passed. Preserve unrelated grants and the disabled probe while completing
the access checks.

## Hosting estimate

The public [Azure Retail Prices API](https://prices.azure.com/api/retail/prices)
query for App Service in East US returned the following relevant entry:

| Field | Observed value |
| --- | --- |
| Product | Azure App Service Basic Plan - Linux |
| SKU / meter | B1 / B1 |
| Type | Consumption |
| Currency / unit | USD / 1 Hour |
| Retail price | 0.017 per hour |
| Estimate at 730 hours | USD 12.41 |

This is an indicative **hosting-plan-only** retail estimate, not the
subscription's contracted invoice or a hard budget. It excludes Foundry
compute, storage, network, taxes and other services. The retrieved B1
records had an empty `armSkuName`, so a query requiring `armSkuName = B1`
returned no rows; the successful selection used product, SKU, meter and
consumption type.

A retained dedicated plan can continue billing when the web app is stopped.
Resource approval must distinguish retaining the plan from deleting the
new, exclusively owned plan after a trial. Do not delete or repurpose any
existing shared hosting plan to control this experiment's cost.

## Next approval and remaining gates

Because the inspected resource group has no web app/plan, either approve a
new dedicated Linux B1 plan and web app in the selected region, or identify
a compatible existing plan outside the inspected scope for a separate
read-only check.

That resource decision does not silently authorize directory registrations,
login credentials, enterprise-app assignments, role changes, or agent
enablement. Confirm those exact operations, the session/credential policy,
and an approved negative-test identity before the protected cloud probe.

Before deployment, implement and locally exercise the authorization and
cloud-transport seams from the selected plan. Do not deploy the existing
unauthenticated local page or weaken its loopback-only client. Keep the
synthetic probe model-free and retain the five-attempt maximum for each
explicitly authorized round.
