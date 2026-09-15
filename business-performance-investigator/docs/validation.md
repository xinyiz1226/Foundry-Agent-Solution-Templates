# Validation and troubleshooting

## Local checks

`scripts/validate-local.ps1` runs dependency consistency checks, unit and
lifecycle tests, and Bicep compilation. It writes a local-only report to
`.artifacts/local-validation.json`, including `cloudValidation: not_run`.

Mocks establish bounded-query behavior, configuration rejection, error handling,
and lifecycle guards. They do not prove a deployed credential endpoint, DNS
route, driver/native-library availability, or database SID mapping.
Import and package checks on a Windows workstation also do not prove a Linux
hosted-runtime build.

## Cloud evidence, after approval

Required evidence:

1. Agent is deployed and active at the version being tested.
2. SQL resolves exclusively to the approved private endpoint address from the
   actual agent process, not merely from the initializer.
3. TLS verifies the server hostname and certificate.
4. The connected database principal is `bpi_probe_agent` and its SID corresponds
   to the approved agent application/client ID.
5. The fixed view yields probe ID `1`, label `private-sql-probe`, amount `42.00`.
6. Effective base-table and database write/DDL permissions are absent.
7. Azure SQL public network access is still disabled.
8. The probe repeats after session idle/resume; connection renewal works.
9. Cleanup removes the experiment's resources and preserves unrelated assets.

The agent's deterministic probe evidence, not an LLM-authored narrative,
establishes database results. Store only the evidence required for this
synthetic fixture, not tokens or arbitrary database data.

Record the session/version and repeat invocation behavior. A second invocation
in a new session does not prove idle/resume of the first session; test that
separately and document it as pending until performed. Do not bulk-delete all
project sessions when cleaning up one probe.

## Failure guide

| Symptom | Check / required response |
|---|---|
| Python command opens Store or is missing | Use installed `py -3.13`; create the project virtual environment. |
| SQL capabilities return `Visible` | The SKU can be listed while provisioning is restricted. Use an approved available region or obtain a subscription-limit exception; do not treat the listing as availability. |
| Existing model rejects inference | Verify the actual agent identity has the model owner's approved inference role, the configured API is advertised, and the endpoint is reachable. Never retrieve keys or substitute another identity. |
| Extension appears in the azd catalog but preflight rejects it | Inspect `installedVersion`, not the catalog's `version`. Install or update the extension to the manifest's required minimum. |
| Agent SDK or TLS dependency import fails | Check exact package versions and platform wheels. Do not switch to a new runtime/image silently. |
| No agent principal in azd metadata | Inspect extension/runtime versions. Do not look up a similarly named principal or substitute the project identity. |
| Directory service-principal lookup denied | Ask the authorized operator for the required directory access; scripts do not grant consent. |
| SQL name resolves publicly | Check the SQL private endpoint approval, zone link, and agent VNet injection. Do not add public firewall rules. |
| Private address resolves but connection times out | Check NSG rules and SQL Proxy/Redirect ports. Search-oriented 443-only rules do not allow SQL. |
| TLS validation fails | Confirm the normal server FQDN and trusted CA bundle. Never set TrustServerCertificate or disable hostname validation. |
| Token login fails | Check actual identity, token audience, client/object ID distinction, and contained database user. Never print the token. |
| Initializer cannot download image/module | Check its required outbound route and approved registry/gallery endpoints; SQL public access is unrelated. |
| Legacy deployment script rejects storage firewall settings | Deployment Scripts requires a trusted-services bypass even in its private-endpoint example. The current direct ACI initializer avoids that dependency; do not weaken storage or SQL networking to resume an old script. |
| Initializer ARM deployment succeeds but SQL is not ready | Container provisioning is not script completion. Require the pinned image/identity/subnet, zero process exit code and the exact completion marker. |
| Failed initialization does not rerun | After fixing the cause and reapproving execution, repeat Initialize with `-RetryInitialization`; a completed/failed container is not implicitly redeployed, and running initialization cannot be restarted. |
| Result mismatch or extra permissions | Treat as failed validation, not a successful answer; inspect fixture and grants. |
| Resource inventory differs at cleanup | Inspect the additional resources. Do not edit ownership state merely to bypass the guard. |

## Completion wording

Before cloud execution, the strongest claim is:

> The local validation package is implemented and locally checked.
> Azure identity, private connectivity, actual permissions and cleanup remain unverified.

After a cloud run, report each check independently, including failure and
not-run states. Do not mark the complete Business Performance Investigator
application finished when only its connectivity probe works.

## Recorded local evidence

On 2026-09-15, the package passed 65 offline tests with Python 3.13 and
standalone Bicep 0.47.16. Both Bicep entrypoints compiled. Tests include actual
installed Responses SDK request/streaming behavior, driver TLS rejection
contracts, strict permission/evidence handling, PowerShell parsing, ownership
guards, and manifest/lifecycle/Bicep interface checks.

The pinned SqlServer PowerShell module 22.4.5.1 was imported locally and its
used parameters checked. The initializer's generated T-SQL parsed with
Microsoft ScriptDom's TSql170Parser without contacting a database.

The SQL driver's certificate helper emits upstream pyOpenSSL deprecation
warnings. Its version is pinned; rejection tests pass, but this remains an
upgrade-maintenance item rather than a reason to disable validation.

Subsequent local preflight passed with Azure CLI 2.90.0, azd 1.34.0,
`azure.ai.agents` 1.0.0-beta.15 and `azure.ai.projects` 1.0.0-beta.10.
The extension regression test rejects absent, outdated and malformed installed
versions; catalog availability alone must not pass preflight.
The operator subsequently completed tenant-scoped Azure CLI/azd login.
Check azd status with the same `--tenant-id` used for login; an unscoped check
returned `unauthenticated` while the scoped check returned `success`.
A live ARM subscription read and limited management/directory permission
checks passed. Regional catalog/quota reads were performed without inference.

After explicit authorization, `Microsoft.Sql` registration completed.
East US 2 and East US SQL capabilities returned `Visible` with provisioning
restricted. Regression coverage rejects that state instead of interpreting
listed SQL Basic support as availability. The operator then selected Central
US, where the existing read-only preflight **passed** with the shared-model
configuration; SQL Basic 5 DTU/2 GB/LRS and initializer/network quota were
checked. At that checkpoint, provisioning and model invocation had not run.
Detailed findings are in [deployment approval](deployment-approval.md).

Existing-model reuse was then implemented and the integrated offline suite
passed **84 tests**, including compiled Bicep checks. The selected deployment
is `DeepSeek-V4-Flash-0731`, called through Chat Completions; the external
hosted-agent protocol stays Responses/2.0.0. Tests cover endpoint validation,
SDK request shapes, bounded calls, malformed/multiple tools, private reasoning
continuation, model errors, exact SQL evidence, skipped model provisioning
and shared-model ownership boundaries. Read-only checks confirmed the actual
deployment metadata and allowed account endpoint; no inference call was run.

The subsequent approved Central US infrastructure deployment succeeded, but
agent deployment did not. Azure CLI camel-cased output names caused an initial
lookup failure; case-insensitive, unambiguous lookup fixed the original
persisted-state reproduction. `azd deploy` then failed with `AADSTS530036`.
Explicit-tenant ARM/Foundry tokens succeed, while the default-context ARM
request fails. Preflight now tests both contexts without retaining tokens.

Immediate cleanup hit asynchronous Foundry and network dependencies. SQL,
private endpoints/DNS, initializer storage/identity and NAT/public IP were
removed. Azure subsequently finished account/Capability Host deletion and
released the subnet association. Guarded deletion of the active resource group
was confirmed at 2026-09-15 07:45:14 UTC. The new Foundry account remains
soft-deleted; no permanent purge or external role changes were performed.
Group deletion now refuses active Foundry accounts and service-managed subnet
links. That initial safety guard preceded the ordered automation described below.

The updated integrated offline suite passed **90 tests**, including compiled
Bicep checks, JSON-persisted output casing, configured/default authentication
contexts, secret-safe error-code reporting, and teardown guards. The real
default-context authentication failure is now caught by preflight before
resource creation. A Cost Management query was throttled (HTTP 429); actual
billed cost remains unknown.

The follow-up authentication and teardown changes passed **126 integrated
offline tests** with compiled Bicep checks. The opt-in isolated azd profile
uses the same verified Azure CLI user, tenant and subscription; configured
and default ARM/Foundry token checks and full read-only preflight passed.
No global azd login or tenant policy was modified.

Ordered cleanup now has entrypoint-level regression coverage for dependency
order, partial/resumed deletion, explicit 404 versus permission errors,
timeouts, ownership/incarnation mismatches, unexpected projects, unapproved
purge, already-absent groups, and `-WhatIf`. A real read-only cleanup preview
against the prior deleted experiment reported its exact retained soft-deleted
account and confirmed that neither Azure nor local state was changed.
No new deployment or destructive teardown was run for this follow-up.

### Second approved cloud experiment, 2026-09-15

The second isolated run successfully deployed `sql-probe` version 1. The
Agent stage now exports both `AZURE_AI_PROJECT_ENDPOINT` and the extension's
required `FOUNDRY_PROJECT_ENDPOINT` from the same verified deployment output.
Its actual directory `ServiceIdentity` was verified; object ID and application
ID happened to be equal, but both were independently checked.

Private Deployment Scripts initialization failed before SQL execution because
its storage integration requires `AzureServices` bypass. Rather than relax
`publicNetworkAccess: Disabled` or `bypass: None`, initialization moved to
direct ACI in the same approved subnet with the same initializer identity/NAT.
The Microsoft Azure PowerShell image is digest-pinned; the container completed
with exit code zero and the required SQL evidence marker. Legacy storage/file
endpoint/DNS resources remain in the core inventory but are unused by ACI.

The first hosted invocation passed at **08:53:09 UTC**:

| Evidence | Result |
|---|---|
| Existing DeepSeek model | Actual agent-identity inference and bounded tool execution passed |
| Hosted Linux / SQL driver | Agent successfully executed the fixed private-SQL query |
| Private connectivity | DNS matched the approved endpoint; SQL public access remained disabled |
| TLS | Certificate/hostname validation and full-session encryption enabled |
| SQL identity | `bpi_probe_agent`; SID matched the verified application/client ID |
| Fixture | `(1, 'private-sql-probe', 42.00)` |
| Effective permissions | View SELECT allowed; checked base-table/DML/DDL/control permissions denied; no unknown checks |

The exact session was then stopped and observed as `idle`. Validation with
`-SessionId` reused that session, with a fresh conversation, and passed the
same probe again. The session returned to `active`, preserving its ID,
version and creation timestamp; last-access time increased. Compound evidence
was recorded at **08:58:27 UTC**.

This proves **controlled stop -> idle -> same-session resume**, not natural
automatic idle-timeout behavior. `cloud-probe-first.json`, `cloud-probe.json`
and `resume-evidence.json` are separate ignored evidence artifacts; the
single-invocation validator alone does not claim compound resume success.
Two hosted invocations were made, each bounded to two model requests and
one SQL query. The session was stopped again afterward.

The integrated suite subsequently passed **146 tests**, including compiled
Bicep, actual Agent-stage endpoint handoff, initializer completion and pinned
image consistency, retained-session argument handling, and ordered cleanup.
Cleanup regressions include the provider's exact JSON-wrapped `NotFound`
response and guarded terminal-ACI deletion/subnet release; malformed responses,
permission errors, active execution and identity/topology mismatches fail closed.
For this live run, the completed initializer was independently verified and
deleted before starting the ordered teardown; automatic terminal-ACI removal
is covered by offline entrypoint tests, not a second live container deletion.

During live host deletion, Azure returned a second response shape: HTTP 404
with `UserError` and nested `NotFoundError`. The CLI truncated its message
prefix, so cleanup correctly stopped rather than guessing absence. A direct
GET and successful empty parent list independently confirmed deletion.
The narrowly scoped compatibility fix now corroborates that exact
capability-host GET failure with a fresh, complete parent list; generic
`UserError`, permission/network failures and ambiguous results still fail.
The updated cleanup suite passed **56 focused tests**. A guarded resume
confirmed deletion of the project and active account and then waited for
service-managed subnet-link release; soft-deleted-account retention is explicit.

The subsequent 30-minute network wait exposed an overly strict cleanup guard,
not a remaining Foundry link. A live VNet read confirmed no Foundry-subnet SAL,
no initializer container or IP configuration, and only initializer `acisal`
with `linkedResourceType: Microsoft.ContainerInstance/containerGroups`,
`provisioningState: Succeeded` and boolean `allowDelete: true`.
The [network API contract](https://learn.microsoft.com/en-us/rest/api/virtualnetwork/service-association-links/list?view=rest-virtualnetwork-2025-09-01)
defines that flag as permitting deletion and uses this same ACI link shape in
its example. Cleanup now distinguishes this exact deletable initializer
residual from blocking/unknown links, with fresh ownership, topology and
no-active-work checks before mutations. It never directly deletes or patches
a SAL or removes delegation. The focused cleanup suite passed **64 tests**.
The final guarded retry reached normal owned-network and group deletion.
The final integrated run passed **159 tests** with Bicep compilation and no
skips. Azure accepted the guarded group-deletion request and its resource
inventory decreased; an accepted request alone was not proof of completion.

### Verified cleanup outcome

At **2026-09-15 10:25 UTC**, an independent `az group exists` returned `false`
for the exact second experiment, and the temporary model-assignment count
was zero. A subsequent read-only cleanup preview confirmed group absence
and explicitly reported the retained soft-deleted account. The 24-hour
fallback was cleared only after verified approved-scope cleanup.

The final local polling process had failed on an empty resource inventory
after Azure deleted the resources. This was a reporting/lifecycle error,
not a failed cloud deletion. Preserve the original state/log rather than
rewriting it to mask the failure; the separate ignored completion artifact
records authoritative absence checks. The final polling fix enumerates
resource IDs explicitly instead of reading `.id` on an empty array under
strict mode. **66 focused cleanup tests passed**, including a present group
with zero resources followed by group absence, malformed inventory rejection,
and read-only absent-group handling with the original `validated` state.

The exact temporary shared-model role was revoked and its absence verified.
Active-resource cleanup is verified; no permanent purge was approved or
performed. The second scoped Cost Management query also returned
HTTP 429, so final billed cost is unknown; group-only totals would additionally
exclude shared-model inference charges. AdventureWorks import,
business-analysis evaluation and the full analyst application remain unbuilt.
