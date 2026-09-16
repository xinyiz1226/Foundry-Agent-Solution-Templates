# Cloud workbench code: authorization and transport

This is **source-deployed code, not a running or live-validated application**.
The code-only slice did not create directory registrations, credentials,
identities or grants. A subsequent, separately approved
[identity-configuration slice](web-identity-configuration.md) configured
those controls on the existing App Service. A subsequent
[approved private deployment](guarded-deployment.md#private-web-deployment-approved-and-completed)
completed source upload, remote Oryx build and deployment. The app remains
stopped/public-access-disabled; its B1 plan still bills. No agent was
enabled or real model called. **G0 remains incomplete.**

A subsequent [direct caller probe](guarded-deployment.md#real-caller-access-positive-current-read-and-negative-direct-call)
temporarily enabled the backend, verified an operator's `current` read
and an unapproved user's HTTP 403, then disabled it and stopped the new
session. Those callers used isolated CLI profiles, not the deployed web
managed identity or browser ID-token flow.

A later [anonymous-login diagnosis](guarded-deployment.md#anonymous-login-precheck-aborted-window-and-diagnosis)
recorded three root-request HTTP 401 responses with no redirect, including
one with `Accept: text/html`. It closed the web-only diagnostic within its
60-second budget and left the agent disabled. This did not establish the
root cause or complete browser acceptance; no authentication controls were
relaxed.

A separately approved [browser comparison](guarded-deployment.md#browser-versus-script-and-explicit-login-comparison)
then observed Requests HTTP 401 but isolated Edge HTTP 302 to the configured
tenant, both for the root page and the explicit AAD login route. The private
window precheck now uses browser navigation rather than treating Requests
as a browser substitute. No authentication settings changed. Login
initiation is demonstrated, not operator sign-in, callback validation,
the protected page, or managed-identity integration. The site is closed again.

A later [human-window attempt](guarded-deployment.md#human-browser-window-opened-then-closed-without-an-acceptance-result)
passed that precheck and opened the operator browser, but obtained no human
login/rejection result. It closed early with the original five sessions
still idle and no new sessions. Missing human feedback is not an
authentication success or failure.

## Entry points and public interfaces

| Surface | Purpose |
| --- | --- |
| `workbench.py` / `scripts/run_workbench.py` | Existing loopback-only, unauthenticated synthetic preview. Never use these as cloud startup. |
| `cloud_workbench.py` | Separate Streamlit entry point for a subsequently approved, protected App Service deployment. Never starts a backend worker. |
| `OperatorAuthorizer.authorize(id_tokens)` | Verify exactly one Entra ID token against the single-operator policy, or raise a sanitized `AuthorizationError`. The input is the header-value sequence, not a cached authorized flag. |
| `CloudWorkbenchClient.current/start/resume/retry` | Same typed projections and bounded command behavior as the local client, using a credential and mandatory fresh authorization callback. |

The two clients share projection parsing and command construction. The local
client still accepts only `http://127.0.0.1:PORT`; setting its URL to a cloud
endpoint is not supported. The cloud entry point has no local fallback.
Source blocks, candidates, evidence, pending requests, and action controls
are all inside the guarded UI fragment. Errors clear its protected content
rather than presenting a failure as an empty job.

## Human identity proof and expiry

The selected implementation requires App Service Easy Auth with its token
store enabled and a **tenant-specific Entra v2.0 login**. App Service documents
the `X-MS-TOKEN-AAD-ID-TOKEN` request header when that store is enabled.
The application additionally verifies the token's RS256 signature using the
configured tenant's signing keys, exact web-registration audience and issuer,
tenant/object-ID allowlist, token version, and required integer time claims.
Missing, ambiguous, malformed, forged, wrong-tenant, wrong-audience,
unauthorized, future-dated, and expired proofs fail closed.

This deliberately does **not** assume `X-MS-CLIENT-PRINCIPAL` contains an
expiry claim, or trust unsigned identity-header values as JWTs. It does not
use the Foundry `x-agent-user-id` partition key as an Entra object ID. Entra
v1 tokens, access-token-only contexts, bearer-only browser clients without
the configured ID-token header, and other identity providers are not a
supported login configuration. Do not weaken verification to make such a
deployment appear healthy.

**Default maximum token age: 900 seconds from the signed `iat`.** Access
expires at the earlier of that age limit and signed `exp`, with no expiry
grace. Reads, reconnects, button clicks, and resource-cache hits never reset
that age. `nbf` and `iat` must not be in the future. The configured ceiling
may be 60-3600 seconds; it is a server policy, not a browser preference.

Every cloud read/command obtains the **current Streamlit execution context**,
not the first browser's cached token. Policy/environment configuration is
checked again at each gate; a captured fragment whose configuration changed
is rejected. Authorization is also rechecked after a potentially slow
backend read, before rendering its result. On denial or expiry the page
shows sign-out and sign-in/reconnect links; it does not refresh provider
tokens automatically. A stale Easy Auth token store can require sign-out
and a new sign-in, not merely a page refresh.

Streamlit's context still represents the initial WebSocket request. The
signed-token time limit makes a stale header bounded; it does **not** turn
that header into a fresh directory lookup. Enterprise-app unassignment,
Entra logout/revocation, token-store refresh, and already-connected browser
behavior need live testing. An existing proof is accepted only until its
local time limit, but freshly issued proofs depend on the configured
identity-provider policy. No immediate directory-revocation guarantee is
claimed. Previously delivered content cannot be retroactively erased, and
denying further operator actions does not cancel an already accepted
bounded native round.

Signing-key discovery uses only the configured public-cloud tenant endpoint,
not token-supplied URLs. Key responses are limited to 64 KiB; keys are cached
for five minutes. Unknown keys are rejected until cache refresh, and failed
refreshes block access without using stale keys. An issuer failure suppresses
further key requests for 30 seconds. There are no redirects or environment
proxies. Key rotation can temporarily deny access; it never disables
signature verification.

Easy Auth remains responsible for the browser's OIDC login, state/nonce
handling, token-store/session handling, and protected header injection.
JWT verification here is an additional operator check, not a replacement
login implementation. The live ingress configuration remains a deployment
gate.

## Service identity and gateway routing

The web process constructs `ManagedIdentityCredential`, not a developer
credential chain. Only its service token is sent to the exact configured
Foundry Invocations endpoint with scope `https://ai.azure.com/.default`.
Human ID tokens are never copied to gateway headers/payloads, UI output,
durable requests, or `st.session_state`. The web app needs agent-scoped
Foundry Agent Consumer, not Blob permissions or a deployment role.

The cloud client preserves one response `x-agent-session-id` and uses it
only as the `agent_session_id` query parameter. This selector is ephemeral
routing, **not** durable job identity or authorization. Shared process-local
client state prevents each browser poll from bootstrapping another session;
concurrent callers cannot bootstrap competing sessions.

Default client limits are **900 seconds and 120 outgoing gateway requests**.
Cloud UI polling is every ten seconds, rather than the local two-second
interval. Reads count toward the request limit and can consume hosting and
Blob operations even though they do not authorize extraction.

An uncertain initial sessionless request, missing/ambiguous selector, or
contradictory selector fails closed rather than trying another session.
A missing selector on a later response also quarantines routing; no live
contract permitting such an omission has been established.
A stale selector is never silently dropped to bootstrap a replacement.
HTTP, credential, authorization, malformed-response, and routing failures
remain visible. There are no redirects or automatic mutation retries.
Explicit saved-request retry retains the exact original body, request ID,
revision, allowance, and deadline, even when the backend must reject an
expired saved intent.

The lifetime limit gates new HTTP admissions; it is not a total-request or
credential-acquisition deadline. Each HTTPX operation uses at most ten
seconds or the remaining lifetime, whichever is smaller. Token acquisition
and already-running server work are not cancelled by these checks.

The shared cache stores routing/credentials and signing keys, **not a caller's
authorized status**. Only transient notices/widgets use Streamlit session
state; job and request identities remain in the durable backend.
Ordinary process shutdown closes owned clients/credentials. A process
restart or explicit cache replacement loses the ephemeral routing/budget
state; these are not global multi-process limits. For a later probe use one
web process, an externally bounded duration, and explicit owned-session
cleanup. Exhausting a client limit does not stop or delete a hosted session.
Do not restart the app automatically to defeat the limit.

## Configuration contract for a future deployment

Do not configure, start, or upload the app as part of reproducing local tests.
Values below belong in approved server configuration, never in committed
environment files or browser input.

| Variable | Required value |
| --- | --- |
| `INFORMATION_EXTRACTION_WEB_TENANT_ID` | Tenant UUID, not `common` or `organizations`. |
| `INFORMATION_EXTRACTION_WEB_CLIENT_ID` | Dedicated web login registration's application UUID; not the managed identity or Foundry audience. |
| `INFORMATION_EXTRACTION_WEB_OPERATOR_ID` | Approved user's object UUID in that tenant; not an email/display name. |
| `INFORMATION_EXTRACTION_WEB_MAX_TOKEN_AGE` | Optional maximum signed-token age in seconds, default 900, allowed 60-3600. |
| `INFORMATION_EXTRACTION_PROJECT_ENDPOINT` | Exact `https://<account>.services.ai.azure.com/api/projects/<project>`, without query, credentials, fragment, or alternate port. |
| `INFORMATION_EXTRACTION_AGENT_NAME` | Explicit existing synthetic hosted agent name. |

The `cloud-workbench` optional dependency set includes Streamlit, HTTPX,
Azure Identity, and PyJWT's cryptographic support. It excludes the hosted
worker and real-model SDK extras. A future App Service startup must launch
Streamlit against **`cloud_workbench.py`**, with the approved host/port and
CORS/XSRF settings. It must not run the local launcher or hosted `main.py`.
The [separate web source target](guarded-deployment.md#separate-source-artifacts)
is available through `scripts/package_source.py --target web --check`.
It maps `requirements-web.txt` to the ZIP root `requirements.txt`; the
hosted target and its 14-file allowlist are unchanged. Private web upload,
remote build and startup configuration are now recorded in the approved
deployment. A later private probe confirmed platform startup and restored
the stopped state; Streamlit/browser acceptance and repeatable identity
resource definitions remain separate work. The guarded slice also created
backend version 2 without enabling or invoking it.

## Reproduce the local checks

From `information-extraction`, in a Python 3.13+ environment:

```powershell
& .\.venv\Scripts\python.exe -m pip install -e '.[cloud-workbench,test]'
& .\.venv\Scripts\python.exe -m unittest `
    tests.test_workbench_auth tests.test_cloud_workbench_client `
    tests.test_cloud_workbench_ui tests.test_workbench_client `
    tests.test_workbench_ui -q
```

Tests use ephemeral RSA keys, signed identity fixtures, injected clocks,
external HTTP/credential fixtures, and actual Streamlit `AppTest` execution.
They never authenticate to Entra, fetch real tenant keys, invoke Foundry, or
call a model. The existing optional native/process tests still cover the
local backend. AppTest reruns with retained/replaced request-header fixtures
are not a real browser WebSocket or Easy Auth validation result.

Before cloud execution, complete the [authorization plan](workbench-hosting-auth-plan.md)
gates: approved login/credential configuration, managed identity/grants,
effective Foundry permissions and direct-call negative test, exact container
protocol understanding, web packaging, live WebSocket expiry/reconnect, and
budget/stop evidence. Protecting this page alone does not restrict ordinary
users who already hold an effective direct Foundry invocation grant.

Primary contracts: [App Service provider token headers](https://learn.microsoft.com/en-us/azure/app-service/configure-authentication-oauth-tokens),
[Entra ID-token claims](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference),
and the existing [hosting/authentication research](workbench-hosting-auth-research.md).
