# Web identity configuration: observed Azure state

## Scope and status

On September 15, 2026, the operator separately approved configuring the
existing web host's login and service identity, without application
deployment, public access, agent enablement, or model calls.

The approved identity/configuration operations completed and were read back.
**This is configuration evidence, not a working deployed application or
proof of end-to-end caller isolation. G0 remains incomplete.**

The Web App remains **Stopped** with **public network access Disabled**,
Python 3.13, an empty startup command, Always On off, FTP disabled, and
site/SCM TLS 1.2. The existing hosted agent remains **disabled**. No code
was uploaded, no agent/session was invoked, and no real model was called.
The retained West US 2 B1 plan still incurs charges.

Exact resource, application, credential-key, grant and operator identifiers
are retained in private operational evidence, not in this contribution.
The earlier [empty-host record](web-host-deployment.md) remains historical:
the host now has identity/authentication settings, but still no workbench
application code.

## Directory login configuration

| Check | Verified configuration |
| --- | --- |
| Login registration | Dedicated, single-tenant (`AzureADMyOrg`), owned by the operator. |
| Redirect URI | Only the owned HTTPS site's `/.auth/login/aad/callback`; no wildcard or localhost callback. |
| Browser grant | ID-token issuance enabled for the login flow; implicit access-token issuance disabled; not a fallback public client. |
| Requested permissions | Delegated `openid` and `profile` only; no `User.Read`, directory data, or application permissions. |
| Enterprise application | Dedicated, enabled, owned by the operator, with assignment required. |
| User assignment | Exactly one assignment: the approved tenant-local operator, using the default app role. |
| Consent | Microsoft Graph accepted an `AllPrincipals` delegated consent record for this application and **only** `openid profile`. |

No directory user or group was created, and no administrator role was
assigned. A direct directory-role membership read returned no roles; that
read is not a complete effective-permission assessment. The successful
operations and resulting consent record are the evidence, not a claim
that the operator holds a particular directory administrator role.

The consent record does not admit every tenant user to the workbench.
Enterprise-app assignment, the Easy Auth principal filter, and the
application-side operator check remain separate requirements. Their actual
browser enforcement still needs the later live matrix.

## Login credential handling

One new client secret was created with a **90-day lifetime**, expiring on
**December 14, 2026 (UTC)**. It was transferred in process memory directly
to the owned App Service's encrypted-at-rest application configuration,
then compared with a protected readback. Its value was not printed, placed
in command-line arguments, written to local artifacts, or committed.
Operational evidence contains only its key ID, expiry and storage status.

`INFORMATION_EXTRACTION_WEB_LOGIN_SECRET` is marked as a slot-sticky setting.
Only setting names/stickiness and credential metadata were used for
independent reporting. App Service configuration readers and directory
administrators remain trusted administrators; this is not a Key Vault or
secretless-login deployment.

Rotate **before December 14**, allowing time to verify the replacement.
Create a replacement short-lived credential without resetting all existing
credentials, securely replace this setting, and verify login during a
separately approved live window before removing only the old credential's
key ID. There is no automatic rotation or reminder in this slice. Do not
rerun initial-creation steps blindly after an interrupted operation.

## Easy Auth and operator settings

Direct ARM `authsettingsV2` readback established:

- Authentication enabled and required, with unauthenticated requests
  redirected to the Entra login provider and no authentication-exempt paths.
- Tenant-specific v2 issuer, exact web-registration client/audience, and
  only the approved operator's tenant-local object ID in the principal filter.
- Login requests `openid profile`, uses the protected secret setting, and
  has the token store enabled.
- Fixed 15-minute session-cookie lifetime, zero token-refresh-extension
  hours, nonce validation enabled, and HTTPS required.

The application settings now provide the tenant/client/operator IDs,
900-second maximum ID-token age, existing Foundry project endpoint and
synthetic agent name expected by [the cloud entry point](cloud-workbench.md).
No startup command was configured and no endpoint was opened.

Use the **`properties`** projection of the ARM resource when checking these
values. A top-level-field projection of the CLI auth response returned nulls;
the authoritative direct ARM read confirmed the configuration. Null query
results alone are not evidence that authentication is disabled.

Cookie configuration does not by itself terminate an already-open
WebSocket. The local code's signed-token time checks are still required,
and actual logout, expiry, token-store refresh and reconnect behavior
remain live deployment gates.

## Web managed identity and access inventory

The owned Web App now has a system-assigned managed identity in the expected
tenant. A subscription-scoped assignment query for that exact principal
returned **one role assignment**: **Foundry Agent Consumer**, scoped to the
existing target **agent**, not the whole project/account/resource group.

The verified role definition has no management actions and only:

```text
Microsoft.CognitiveServices/accounts/AIServices/endpoints/interact/action
```

No Blob data or deployment role was granted to the web identity. The hosted
runtime's existing storage grant was not changed.

The selected agent-scope inventory now returns ten assignments including
inheritance: the earlier nine plus the new web-identity grant. Existing
operator and administrator grants were not removed or narrowed. The two
existing non-operator service principals' OpenAI User role lacks the
explicit agent-endpoint interaction action, but includes OpenAI Responses
and Assistants actions. That is **not** proof that every alternate calling
route is blocked.

The resource provider advertised the project-application listing surface.
Listing the selected project's applications with its supported
`2026-05-15-preview` API returned **zero applications**, with no continuation
link. This is a scoped published-application inventory, not proof about all
protocol/version/session routes or future aliases.

Full group/PIM/deny/effective-access analysis and an actual unapproved
ordinary caller test remain outstanding. An appropriate non-administrator
test identity has not been supplied; none was created or impersonated.
The workbench login must not be treated as protecting a caller who has an
independent effective Foundry invocation grant.

## Next approval and acceptance gates

The existing agent's source binding is still the historical `c852762`
archive recorded in [the hosted smoke](hosted-smoke-results.md). It predates
the workbench's `current` action and durable HTTP intent discovery.
**Deploying only the web page would not provide the required backend
interface.** No agent version was changed in this identity slice.

Before a separately approved synthetic deployment:

1. Reconcile the hosted protocol declaration and prepare distinct,
   allowlisted web and updated backend artifacts. Do not substitute the
   local launcher or assume the old agent already serves `current`.
2. Obtain the unapproved non-administrator test identity and complete the
   direct-call/alternate-route permission checks.
3. Approve code deployment, agent update/enablement, web access/start,
   finite probe duration/request/session limits and owned-resource stop
   conditions. These are not covered by the identity-only approval.
4. Exercise login, rejection, open-WebSocket expiry, read-only reconnect,
   explicit start/resume and exact saved-request retry using synthetic data
   and no real-model calls. Record actual deployed hashes and caller results.

The empty-host Bicep file is not a complete identity deployment definition.
Do not rerun it as an authenticated-workbench deployment or assume it
captures directory consent, credential rotation and the new role/configuration
state. Full repeatable Bicep/azd deployment remains separate work.
