# Business Performance Investigator: implementation plan

Last updated: 2026-09-15.

## Status and authorization

**The Phase 1 validation package is implemented and locally checked; no cloud
deployment has been performed. The complete analyst application is not built.**

- The product scope and the next technical-validation milestone were agreed
  with the project owner.
- Public documentation and reference-template source were inspected. The local
  package now includes the minimal runtime, Bicep, lifecycle scripts, tests and
  deployment-approval materials. No end-to-end Azure deployment, real SQL
  connection, or business-analysis evaluation has been performed.
- No Azure resources have been created for this project.
- The original plan was committed as `a49097b`. Implementation followed explicit
  approval to prepare the package without deploying Azure resources.
- See `docs/validation.md` for recorded local evidence and
  `docs/deployment-approval.md` for the next approval gate. Cloud deployment
  requires separate, explicit approval.
- Recording or committing this plan does not authorize resource creation,
  tenant permission changes, paid services, or production database changes.

Project folder: `business-performance-investigator`.

Working branch: `xinyiz1226-business-performance-investigator`, created from
`main`. The baseline at project creation was `c6f4d1d`.

### Implementation clarifications

- Phase 1 owns a new disposable resource group only. Existing customer SQL
  remains a later full-template path and is rejected by the probe lifecycle.
- The initializer is the new probe server's Entra administrator. The agent is
  a distinct contained user with approved-view SELECT plus object-scoped
  metadata visibility needed for permission checks.
- The proposed infrastructure includes an initializer-only NAT gateway and
  static public IP to make private ACI outbound access explicit. This addition
  and its hourly cost require review before deployment.
- Source deployment, `python-tds`, and the deterministic evidence protocol
  passed local dependency and behavior checks, not a hosted Linux/SQL test.

## Purpose and positioning

Build a complete Microsoft Foundry hosted-agent solution template that customers
can try, adapt to their own data, and use as the starting point for further
customer engagement.

The scenario is **business metric change investigation**: compare two periods,
identify where changes are concentrated, and produce a report backed by
reproducible calculations. Sales is the initial demonstration, not a permanent
restriction on the product name.

The template must not require Fabric or Databricks. Its differentiation is a
deployable, editable, narrowly scoped application with controlled analysis
tools, business configuration, and evaluation assets, not a claim of superior
analytics capabilities.

Fabric data agents already support governed conversational analytics.
Databricks Genie Agent mode already supports multi-step investigation and
evidence-backed reports. Do not describe those capabilities as unique to this
template or claim competitive superiority without comparative evidence.

The owner's separate unstructured-to-structured data PoC is outside this
project's scope. Combining document evidence with this application is a
possible future direction, not a first-release requirement.

## Confirmed design decisions

| Area | Decision |
|---|---|
| Primary users | Business analysts and sales operations analysts who can check results and business definitions. |
| Setup persona | A developer or data engineer prepares authorized views and business configuration. |
| Core task | Compare periods, decompose metric changes, investigate relevant segments, and summarize evidence. |
| Database | Azure SQL Database only in the first release. |
| Default sample | AdventureWorksDW, initially Internet Sales only. |
| Customer data | A supported existing-Azure-SQL path, not just instructions to rewrite application code. |
| Query control | Agent selects bounded analysis tools; tools validate inputs and generate parameterized SQL. No arbitrary model-generated SQL. |
| Agent autonomy | Choose dimensions, filters, subsequent drilldowns, and stopping time based on intermediate results and execution budgets. |
| Interface | Minimal Web page with metric/period selection, optional investigation focus, report, and expandable evidence. |
| Web hosting | Azure App Service, hosting the frontend and backend together. |
| Web authentication | Microsoft Entra login; backend invokes Foundry using an authorized identity, not browser-held service credentials. |
| Pilot authorization | Approved users share one explicitly authorized data scope per isolated deployment. |
| Foundry ingress | Publicly reachable but authenticated and authorized; a Foundry private ingress endpoint is not required by the agreed scope. |
| SQL networking | Private endpoint; SQL public network access disabled by default. |
| Runtime access | Managed identity with SELECT on approved analysis views, not general write access. |
| Infrastructure | Bicep only; no first-release Terraform implementation. |
| Agent packaging | Prefer source deployment. A validated, pinned third-party SQL driver is acceptable. |
| Driver candidate | `python-tds` (`pytds` import), subject to runtime, token-authentication, TLS, and connection-recovery checks. |
| Private initialization | Template-owned temporary private execution resources are allowed; initializer identity is separate from runtime identity. |
| Completion bar | Deployable template, correct results, fixed-workflow comparison, and second-dataset configuration-only adaptation. |

### Explicit exclusions

- Fabric/Databricks dependencies or a replacement for their full governance stack.
- Automatic understanding of arbitrary schemas or a visual semantic-model editor.
- Freeform SQL generation or unrestricted database exploration.
- Per-user production row-level permission inheritance.
- Real-time monitoring, forecasting, automatic repair, business writeback, or
  autonomous operational actions.
- Claims of causal explanation, revenue impact, or optimal decisions based
  only on observational sales data.
- A full conversational product or mandatory multi-agent architecture.
- APIM, VPN, private ACR, CMK, and other reference-template infrastructure merely
  because those resources appear in another sample.

## First-release analysis contract

### Initial tables and metrics

Use `FactInternetSales`, `DimDate`, `DimProduct`, and `DimSalesTerritory`.
Product category/subcategory tables may be added later if justified by scope.
Customer names, email addresses, and postal addresses are unnecessary.

| Metric | Definition |
|---|---|
| Sales | Sum of `SalesAmount`; do not substitute tax/freight-inclusive payment totals. |
| Orders | Distinct `SalesOrderNumber`, not the number of sales-detail rows. |
| Gross profit | Total sales minus total `TotalProductCost`. |
| Gross margin | Total gross profit divided by total sales, not an average of row-level margins. |
| Time | Order date, not ship date or due date. |

Check actual schema, monetary conventions, joins, date coverage, and complete
periods before selecting demonstration questions. Do not infer a complete month
from the largest available date. Do not pre-invent a sales decline or its cause.

### Demonstration questions

1. How did sales, order count, and gross margin change between two complete
   periods?
2. Which territories contributed most to the sales change?
3. Within a selected territory, which products contributed most?
4. Did sales and gross profit move together?
5. What is established by the data, and which explanations require more evidence?

### Investigation and output

The expected flow is scope clarification, data checks, overall comparison,
adaptive dimension breakdown, deeper investigation where useful, and an
evidence-backed report.

Reports must separate:

- **Observed facts:** values and segment changes derived from tool results.
- **Hypotheses:** possible explanations, clearly not established causes.
- **Missing evidence:** additional data needed to test those hypotheses.

Every quantitative conclusion must reference its calculation evidence,
including periods, filters, metric definitions, executed query, and result.
Show absolute change contributions and offsetting increases/decreases.
If only top segments are displayed, retain an "other" total for reconciliation.
Do not force contribution percentages when the net change is zero or near zero.

Tools must constrain identifiers to approved configuration and parameterize
values. Query count, time, result size, and investigation duration need explicit
budgets. Exact limits are to be selected using measurements, not invented here.
Read-only permission alone does not prevent expensive or incorrect queries.

## Why an agent, and how to test that claim

A fixed sequence of aggregate queries plus a report is a valid baseline.
Adding an LLM is justified only if adaptive investigation produces useful
behavior beyond that baseline.

Compare the fixed workflow and agent using the same questions and data:

- Calculation correctness and evidence-backed findings.
- Coverage of relevant changes and missed material segments.
- Query count, latency, token usage, and cost.
- Appropriate stopping and explicit handling of insufficient evidence.

Do not grade success by report length. If adaptive investigation adds no
meaningful benefit, record that result and reconsider the design rather than
presenting an unsupported agent-value claim.

Prepare 12 fixed analytical cases with reference outputs calculated independently
of the model. Cover normal comparisons, zero baselines, empty results,
incomplete periods, distinct-order counting, weighted margin calculation, and
offsetting changes. Numerical results must agree at the declared precision;
dimension totals must reconcile to overall totals.

For portability, use a second synthetic sales dataset with different names and
structure. Adapt only authorized views and configuration, not agent logic.
This establishes initial adaptability, not universal schema support.

## Delivery completeness

Reference the packaging and lifecycle completeness of these templates, not
their business scenarios:

- [APIM hosted agent, InfoExtraction branch](https://github.com/xinyiz1226/Foundry-Agent-Solution-Templates/tree/InfoExtraction/apim-hosted-agent)
- [Private-network hosted agent, InfoExtraction branch](https://github.com/xinyiz1226/Foundry-Agent-Solution-Templates/tree/InfoExtraction/private-network-hosted-agent)

Detailed runtime inspection used reference commit
`c0d6ab97b345aa6468c366930e9d74512ed6f688`. Pin or recheck source references when
implementing; branch content can change.

The full template should eventually include:

- README, architecture diagram, prerequisites, quickstart, example investigation,
  limitations, cost guidance, and cleanup entrypoint.
- Hosted-agent code, pinned dependencies, deployment definition, configuration,
  bounded SQL tools, and explicit error handling.
- Minimal Web app with authentication, investigation status, report/evidence
  display, and visible failure/timeout states.
- Bicep resources, parameters, environment outputs, identities, and role setup.
- Sample data acquisition, version/provenance/license information, initialization,
  approved views, metric configuration, and portability fixtures.
- Preflight, deployment, initialization, identity binding, validation/reporting,
  and cleanup scripts.
- Unit/contract tests, numerical reference cases, deployment smoke checks,
  baseline comparison, and adaptation evaluation.
- Deployment, configuration, customization, security, cost, validation,
  operations, troubleshooting, upgrade, and cleanup documentation.

Infrastructure validation and analytical evaluation are separate deliverables.
Neither substitutes for the other.

## Immediate next milestone: minimal validation package

**Prepare this package before implementing the complete analyst application.**
Its purpose is to de-risk:

`Hosted agent -> bounded SQL tool -> agent identity -> private SQL -> approved view`

### Include

- A source-deployed minimal agent and one deterministic SQL query tool.
- A tiny isolated database, a small table, and an approved view. Full DW import
  is deferred.
- Foundry network injection, SQL private endpoint/DNS, public SQL access disabled,
  and the minimum required permissions.
- An independent initializer identity and a temporary private execution path.
- Local dependency/configuration/Bicep checks.
- Deployment-time validation scripts and cleanup handling.
- An itemized deployment-approval document covering resources, region/model
  availability, quotas, costs, required operator permissions, and teardown.

### Do not include yet

- Full Web application or App Service deployment.
- Complete AdventureWorksDW import.
- Adaptive investigation and report generation.
- Broad production networking or multiple infrastructure providers.

### Deployment acceptance checks, after separate approval

1. Agent deploys and becomes available; record runtime/dependency/protocol versions.
2. SQL hostname resolves to its private endpoint from inside the agent runtime.
3. TLS validates the server certificate and hostname; no disabled verification.
4. Acquire a SQL token using the intended runtime identity; never log the token.
5. Verify the actual database principal and read the approved view.
   `SELECT 1` alone is insufficient to prove view authorization.
6. Inspect permission metadata to confirm no unintended base-table, DDL, or DML
   access. Do not attempt writes against customer business tables.
7. Confirm SQL remains inaccessible through public-network exceptions.
8. Repeat after session idle/resume and connection renewal.
9. Verify initializer privileges are separate from runtime privileges.
10. Clean up only experiment-owned resources and preserve customer-owned assets.

## Technical findings and unresolved gates

### Networking

Official documentation distinguishes hosted-agent application outbound traffic
through the microVM's delegated-subnet NIC from registered tool-server traffic
through the data proxy. This supports investigating a direct Python SQL
connection; it is not proof that this deployment already works.

- Configure hosted-agent network injection at Foundry account creation.
- Foundry and the injected VNet must use a supported same-region configuration.
- Use separate appropriately delegated subnets for Foundry and temporary runners.
- Connect to `<server>.database.windows.net`, not the private IP or the
  `privatelink` hostname; configure the SQL private DNS zone and links.
- SQL connection policy and ports must be deliberate. Proxy/1433 is a candidate
  for the new pilot; do not change a customer's existing policy automatically.
- The Search reference has a private-endpoint NSG permitting 443 before denying
  other traffic. Copying it unchanged would block SQL; adapt rather than clone.
- Private SQL does not imply zero internet egress. Resolve package/build,
  identity, model, and image-fetch requirements explicitly.

### Runtime and driver

The inspected reference uses Python 3.13 source deployment with `remote_build`,
but has no SQL driver. Installing `pyodbc` is not proof that Microsoft ODBC
native dependencies exist. `mssql-python` also has native requirements.

`python-tds` is an approved candidate, not a verified implementation. Pin its
version and validate token callbacks, trusted CA certificates, TLS dependencies,
Python compatibility, query timeouts, and reconnect behavior.

If the source path fails, report the evidence and request approval before
switching to a custom image/ACR or relaxing any security constraint.
Resolve deployment-SDK, runtime-SDK, and Responses-protocol compatibility;
reference versions and current documentation differ.

### Identity and initialization

- Intended SQL scope: `https://database.windows.net/.default`.
- Identify the actual deployed agent principal; do not assume it is the project
  identity, Web identity, or initializer identity.
- Azure SQL resource-management roles do not grant SQL SELECT access.
- Configure a contained Entra database user and explicit SELECT grants on
  approved views. Do not grant blanket `db_datareader` merely for convenience.
- SQL Entra administrator setup and directory lookup permissions can require
  tenant/operator actions beyond Azure resource deployment permissions.
- Do not silently grant Directory Readers or tenant-wide permissions.
- A private Bicep deployment-script runner is a candidate initialization path.
  Its container execution, separate subnet, storage/file endpoint, identities,
  required egress, permissions, and cleanup must be fully accounted for.
- Applying that runner to SQL initialization is an implementation proposal,
  not an already validated end-to-end example.

### Existing-resource boundaries

The default sample path owns its new resources. The existing-SQL path must not
replace the SQL administrator, import sample data, modify business tables,
change server-wide networking, or delete the database.

The customer's technical owner prepares/approves views, principal grants,
private endpoint access, and metric configuration. Track resource ownership
explicitly in deployment and cleanup scripts.

## Cost context, not deployment approval

Illustrative USD public-retail rates retrieved on 2026-09-15 for East US
(global/Zone 1 meters where applicable):

| Component | Illustrative rate |
|---|---|
| Azure SQL Basic, 5 DTUs / 2 GB | $0.161 per day |
| One SQL private endpoint | $0.01 per hour, plus data processing |
| One private DNS zone | $0.50 per month, plus queries |
| Hosted-agent CPU | $0.0994 per vCPU-hour |
| Hosted-agent memory | $0.0118 per GiB-hour |
| Optional later Linux App Service B1 | $0.017 per instance-hour |

The smallest documented 0.5-vCPU/1-GiB sandbox therefore has an illustrative
compute rate of $0.0615 per active sandbox-hour. Concurrent sessions and idle
timeouts affect consumption.

The SQL + one endpoint + one zone subtotal is about $0.42/day or $12.70 for a
730-hour planning month. **This is not the solution's total price or a budget.**

It excludes model inference, source builds, temporary private initialization,
supporting storage/endpoints/DNS, potential managed-network resources,
telemetry, and data transfer. SQL Basic is a candidate for the tiny probe,
not a confirmed SKU for full DW analysis.

Region, model/version, quota, final SKUs, full resource inventory, experiment
duration, and an acceptable spending limit remain to be agreed before deployment.
Reprice the actual selected topology; do not imply a budget alert is a hard
spending cap. Persistent SQL, endpoints, DNS, and hosting plans can accrue costs
while idle; stopping an application is not equivalent to deleting its plan.

## Phased implementation and gates

1. **Prepare the minimal validation package and approval materials.**
   Run local/static checks; disclose what can only be verified in Azure.
2. **Request explicit deployment approval.**
   Confirm subscription/resource ownership, region, model/quota, administrative
   actions, resource list, cost assumptions, experiment duration, and cleanup.
3. **Run the smallest cloud experiment.**
   Validate actual identity, private connectivity, SQL access, and cleanup.
   Reopen architectural decisions if evidence requires material changes.
4. **Build the deterministic analysis baseline.**
   Import selected AdventureWorksDW data, configure metrics and views, implement
   tools, and produce independently checked expected outputs.
5. **Add and evaluate adaptive investigation.**
   Compare against the fixed workflow and enforce execution budgets.
6. **Deliver the authenticated analyst UI and complete lifecycle.**
   Wire App Service, approved identities, deployment, validation, and operations.
7. **Validate customer adaptation and finish the template.**
   Test the second schema, existing-resource safety, documentation, and
   repeatable deploy/validate/cleanup flows.

Do not equate the full-template scope with authorization to skip the early gates.
Step 1 has local implementation evidence. The immediate resume point is the
deployment-approval review in step 2, not automatic cloud deployment. Resolve
any local integration issues found in review before requesting that approval.

## Primary references

- [Fabric data agent](https://learn.microsoft.com/en-us/fabric/data-science/concept-data-agent)
- [Databricks Genie Agent mode](https://docs.databricks.com/aws/en/genie-agents/concepts#agent-mode)
- [AdventureWorks downloads and setup](https://learn.microsoft.com/en-us/sql/samples/adventureworks-install-configure)
- [AdventureWorks sample source](https://github.com/microsoft/sql-server-samples/tree/master/samples/databases/adventure-works)
- [SQL samples license](https://github.com/microsoft/sql-server-samples/blob/master/license.txt)
- [Hosted agents](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents)
- [Hosted-agent source deployment](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/deploy-hosted-agent-code)
- [Foundry networking deep dive](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/agents-networking-deep-dive)
- [Foundry private networking](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/virtual-networks)
- [Azure SQL private endpoints](https://learn.microsoft.com/en-us/azure/azure-sql/database/private-endpoint-overview)
- [SQL Entra service principals](https://learn.microsoft.com/en-us/azure/azure-sql/database/authentication-aad-service-principal)
- [Private deployment-script execution](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/deployment-script-vnet-private-endpoint)
- [python-tds source](https://github.com/denisenkom/pytds)
- [Azure Retail Prices API](https://prices.azure.com/api/retail/prices)
- [Foundry Agent Service pricing](https://azure.microsoft.com/en-us/pricing/details/foundry-agent-service/)
- [SQL Basic private-endpoint Bicep example](https://github.com/Azure/azure-quickstart-templates/blob/master/quickstarts/microsoft.sql/private-endpoint-sql/main.bicep)

Product APIs, availability, runtime dependencies, and prices change. Revalidate
these sources during implementation; source inspection is not deployment proof.
