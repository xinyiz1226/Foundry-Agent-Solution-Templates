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
| Storage mount or deployment script fails | Check private file DNS, initializer role propagation, delegation and platform support. |
| Failed initialization does not rerun | After fixing the cause and reapproving execution, repeat Initialize with `-RetryInitialization`; no implicit new force-update marker is generated. |
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
links; ordered teardown is a manual prerequisite.

The updated integrated offline suite passed **90 tests**, including compiled
Bicep checks, JSON-persisted output casing, configured/default authentication
contexts, secret-safe error-code reporting, and teardown guards. The real
default-context authentication failure is now caught by preflight before
resource creation. A Cost Management query was throttled (HTTP 429); actual
billed cost remains unknown.

No hosted agents were invoked. Hosted Linux dependencies, real agent token
identity/SID mapping, actual private routing, model access, private
initialization, idle/resume and final costs remain unverified. Active resource
group deletion is verified; soft-deleted-account retention remains explicit.
