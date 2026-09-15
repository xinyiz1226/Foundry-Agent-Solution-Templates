# Workbench hosting and authorization: next implementation slice

## Status and decision boundary

The operator selected the recommended architecture on September 15, 2026:
Linux App Service, Entra single-operator authorization, a web managed
identity, and agent-scoped Foundry Agent Consumer. This follows the local
workbench at `444e974` and design at `bbdf975`.

Architecture selection is not approval to create resources, grant roles,
register directory applications, enable an endpoint, or incur recurring
hosting charges. The [read-only preflight](workbench-hosting-preflight.md)
records the observed prerequisites and remaining approvals.
[Authorization and a separate cloud client](cloud-workbench.md) now have
local signed-token/HTTP/UI-fixture coverage and a subsequent
[private source deployment](guarded-deployment.md). They have not been
runtime-validated against Azure ingress, browser WebSockets, or effective
permissions.

The operator subsequently approved one empty B1 plan/site in the same
resource group as the Foundry project. After an East US quota rejection,
the operator selected West US 2, where
[resource creation succeeded](web-host-deployment.md). The app remains
stopped with public access disabled; its retained B1 plan continues billing.
Directory/role changes, application deployment and agent enablement remain
outside that approval.

The operator subsequently approved the identity-only step.
[Observed configuration](web-identity-configuration.md) now includes the
single-tenant registration, operator assignment, OIDC-only consent, protected
login credential, mandatory Easy Auth, system-assigned web identity and
agent-scoped Consumer grant. The app is still stopped/public-access-disabled,
the agent is still disabled, and that identity-only step deployed no code.
Later explicit approval enabled private artifact staging and source
deployment, not site start or public access. Live caller isolation and
WebSocket behavior remain unverified.

The first release remains a **single-operator** reference workbench, as
agreed in the [implementation plan](implementation-plan.md). The next cloud
probe must still use the fixed synthetic sample. Real model integration,
generic schemas, additional document types, and multi-user data isolation
are separate work.

Read the [primary-source findings](workbench-hosting-auth-research.md)
alongside this plan. An installed SDK behavior, a documented platform
contract, and a successful live authorization test are different evidence.

## Current implementation boundaries

| Surface | Observed implementation | Consequence |
| --- | --- | --- |
| [Local Streamlit page](../workbench.py) | Reads the configured job and sends explicit commands; no authenticated operator context. | Keep it loopback-only; it is not the cloud entry point. |
| [Cloud Streamlit page](../cloud_workbench.py) | Guards sources, reads, results and commands with a signed, short-lived single-operator proof. | Requires the separately approved Easy Auth v2/token-store configuration and live acceptance matrix. |
| [Workbench client](../src/information_extraction/workbench_client.py) | Local adapter remains loopback-only; the separate cloud adapter shares projection/command rules and adds guarded service authentication and bounded session reuse. | No URL-switch authentication fallback; no automatic mutation retry or routing reset. |
| [Hosted handler](../src/information_extraction/hosted_app.py) | Checks configured job ownership, sample identity, request shape, and durable execution ownership. | These checks are not caller authorization. All four actions need an authorized entry path. |
| [Local launcher](../scripts/run_workbench.py) | Launches a local backend and Streamlit, clearing inherited hosted settings. | It is not a cloud startup command. Do not launch the offline backend inside the web app. |
| [Hosted probe](hosted-smoke-results.md) | Gateway denied an unauthenticated request; shared-project invocation permissions were accepted for that probe only. | An anonymous 401 does not prove rejection of an unauthorized signed-in user. |

The installed Invocations 1.1.0 endpoint populates request context by copying
`x-agent-user-id` and `x-agent-foundry-call-id` from incoming headers. Core
2.1.0 exposes that context publicly, but its header documentation describes
`user_id` as a per-user state partition key, not an Entra object-ID claim.
The opaque call identifier is specific to container protocol 2.0.0; the
historical deployment recorded an Invocations `ProtocolVersionRecord` of
`1.0.0`. That record is not evidence of the protocol-2.0.0 identity contract.
The subsequent [guarded update](guarded-deployment.md) reconciled the SDK
field and recorded service acceptance of an explicit `2.0.0` declaration
for version 2. Its endpoint remains disabled; runtime identity propagation
still needs a bounded probe.

Consequently, do not implement an operator allowlist by comparing
`request.state.user_id` with an Entra object ID, parsing the call identifier,
or trusting a browser-supplied identity header. SDK context plumbing alone
does not establish the live ingress anti-spoofing boundary. Do not silently
change the container protocol as part of adding authentication.

## Selected topology, subject to feasibility and resource approval

Use **Linux App Service** for Streamlit and a service-to-service managed
identity for the web process, subject to the gates below. Keep extraction
in the existing Foundry/native-task design:

```text
Approved operator's browser
  -> HTTPS web authentication
  -> server-side operator authorization for every read and command
  -> web application's managed identity
  -> Foundry gateway with restricted effective invocation permissions
  -> synthetic hosted handler and native task worker
  -> runtime identity -> private Blob container
```

This topology is acceptable only if an unapproved ordinary caller cannot
use the Foundry gateway directly. A login screen protecting only Streamlit
does not satisfy that requirement.

Inventory every callable alias for the chosen backend, including any
published application, agent/version, and session-specific route. Protecting
one friendly endpoint is insufficient if another authorized route reaches
the same job and ledger.

Do not assume a fresh project under the existing Foundry account provides
isolation. Inspect effective permissions at the target and every ancestor.
If shared/inherited invocation grants defeat the boundary, do not revoke
other users' existing access to make the demo pass. Instead propose a
separately approved isolated Foundry scope, or a separately designed,
cryptographically verifiable backend authorization mechanism.

Current documentation supports **Foundry Agent Consumer** on an individual
agent endpoint. Prefer that narrow grant for the web identity rather than
project-wide access. This is not an isolation guarantee in the presence of
other effective grants; see research sources [S1], [S2], and [S15].

Treat resource/identity administrators who can change deployments or grant
roles as trusted administrators, not as ordinary callers this application
can prevent from changing its policy.

### Human identity and service identity are separate

Use tenant-specific operator identity and explicit authorization, not email
suffix matching, a display name, or "any signed-in user." Start with one
approved operator; group-based access is not needed for this slice.

With service-to-service invocation, the gateway sees the **web application**,
not a delegated human principal. Do not describe that as on-behalf-of
authentication or per-user backend RBAC. Any operator audit attribution
must originate in authenticated server-side context and be linked to the
durable request ID; an unsigned user ID in the request body is not proof.

Do not place credentials, bearer tokens, cookies, or client secrets in the
browser, session-state job records, source archive, invocation payload,
ordinary logs, or Git. Identity-provider configuration/secrets, if required,
must use the selected hosting platform's protected configuration path and
an approved rotation procedure.

Streamlit's long-lived WebSocket adds a separate acceptance condition:
authentication at connection establishment is not proof of fresh
authorization on each later action. Define session expiry and revocation
behavior, recheck server-side policy before reads and commands, and test
an already-connected browser. Do not claim immediate directory-assignment
revocation without verifying it.

The local implementation now bounds a signed Entra v2 ID token to the
earlier of its `exp` and 900 seconds after `iat` by default, rechecks server
configuration and current request context on every protected operation, and
checks again before displaying a backend read. Its
[documented contract](cloud-workbench.md#human-identity-proof-and-expiry)
requires Easy Auth's token store and a matching web-registration audience.
This is a concrete stale-header limit, not evidence of live Entra assignment
refresh or a completed WebSocket test.

Revoking operator access must prevent later operator actions within the
defined policy window. It is not automatically cancellation of an already
accepted native round, which retains its original bounded authorization.
Previously delivered browser content also cannot be retroactively erased
by a server-side permission change.

## Minimum resource and permission inventory

These are requested capabilities, not instructions to create resources now.
Exact role definitions, scopes, and hosting constraints must be checked
against the primary-source findings and the approved target environment.

| Component | Reuse/new decision | Required boundary |
| --- | --- | --- |
| Linux web app and hosting plan | Reuse a compatible approved plan, or approve a new plan and its recurring cost. | Supported Python runtime, Streamlit WebSocket operation, HTTPS, protected ingress and health behavior. |
| Web identity-provider registration / enterprise application | Reuse only if ownership, redirect URIs and audience/policy are appropriate; otherwise approve a dedicated registration. | Tenant-specific authentication, required enterprise-app assignment, explicit tenant/object-ID application allowlist, administrative consent, defined session policy. |
| Web application managed identity | Prefer the web app's system-assigned identity for gateway calls. | Agent-scoped **Foundry Agent Consumer**, not a deployment role; no Blob data access merely to display results. |
| Foundry account/project/agent | Existing project is conditional on effective-permission isolation; otherwise request a suitable isolated scope. | Unapproved callers denied even when bypassing the web app. No changes to unrelated agents or grants. |
| Hosted runtime identity and Blob container | Reuse the dedicated container when approved; grant the actual new runtime principal only if one is created. | **Storage Blob Data Contributor** on the required container; a Blob prefix is not an authorization boundary. |
| Deployment/identity administrator | User or separately approved administrative identity. | Provisioning, role assignment, application assignment/consent; not permissions granted to the running web app. |

Do not add ACR, APIM, Key Vault, a new storage account, a logging workspace,
or another orchestration service unless a selected design actually requires
it and its cost/access has been approved. Do not assume stopping a web app
eliminates its hosting-plan charges.

Use the Foundry token scope `https://ai.azure.com/.default`; the endpoint
permission is
`Microsoft.CognitiveServices/accounts/AIServices/endpoints/interact/action`.
Agent Consumer's role ID is `eed3b665-ab3a-47b6-8f48-c9382fb1dad6`. The
[research](workbench-hosting-auth-research.md#3-foundry-endpoint-token-and-least-privilege-grant)
records the exact agent resource scope and its management-access limitations.

Backend MI does not make the web login flow secretless. Confirm standard
Easy Auth login-credential storage/rotation or explicitly select its
user-assigned-MI/federated-credential alternative. No OBO or
`UserIdentityImpersonation` permission is proposed for this single-operator
slice. Here, "private Blob" means identity-gated, non-anonymous access;
network-private endpoints require a separately approved network design.

## Implementation order

1. **Resolve the environment gates.** Confirm web runtime support for this
   package's Python 3.13+ requirement; choose the hosting/authentication
   mechanism, one operator, the effective Foundry authorization scope, and
   budget/stop conditions. Do not lower Python requirements or introduce a
   container registry without a separately justified change.
2. **Implement web authorization at a small server-side boundary.** Missing,
   invalid, expired, wrong-tenant, and unauthorized contexts must fail closed
   before any job read or mutation. Local synthetic mode remains explicitly
   separate; it must never become a cloud authentication fallback.
3. **Add a separate authenticated cloud transport.** Use the approved
   endpoint and identity; preserve exact request bodies, limits, error
   semantics, and read-only rediscovery. Do not weaken `WorkbenchClient`'s
   loopback guard or enable automatic mutation retries.
4. **Wire resource definitions and identity grants only after approval.**
   Keep web and agent startup/dependencies separate, preserve the source
   package allowlist, and document required administrative prerequisites.
5. **Run the bounded synthetic acceptance matrix below.** Keep the cloud
   probe model-free; record the deployed source hash and observed caller
   outcomes. Stop only the newly approved services/sessions afterward.

Steps 2-3 now have code and local fixture evidence. A separately approved
identity slice configured the existing resources, with readback evidence.
The subsequent [guarded deployment slice](guarded-deployment.md) added web
packaging and created backend version 2 without enabling or invoking it.
A further explicit approval enabled a separate trusted artifact container,
an operator-only container upload grant, remote web build/deployment and
startup configuration. Repeatable deployment definitions, actual web
startup and the live acceptance matrix remain unfinished; the web host
remains stopped/public-access-disabled.

Cloud transport must distinguish a durable job ID from the gateway's
ephemeral `agent_session_id` routing selector. Reuse a known selector within
the bounded probe rather than creating a hosted session on every poll.
Losing that selector must not create a new job or silently replay a mutation.
The existing [probe](hosted-smoke-results.md) records response-header capture
and query-parameter reuse; it is not a multi-instance web-session design.

Review polling frequency and bound session creation/compute duration
separately from the five-attempt allowance. Read-only polling can still
consume hosted compute and storage requests. A model-call cap is not an
infrastructure cost cap.

## Acceptance matrix

| Probe | Required observation |
| --- | --- |
| Anonymous browser / API caller | No job contents or mutation accepted; correct login/denial behavior for the selected surface. |
| Signed-in but unassigned or wrong-tenant operator | Denied before any job read, HTTP intent, authorization, or model attempt. |
| Forged identity headers, body fields, or session selector | Cannot acquire operator or backend privileges. |
| Authorized web identity | Can read current/status and submit bounded start/resume through the intended gateway. |
| Ordinary unapproved user calling Foundry directly | Denied despite bypassing the web page; must use an actually unauthorized test identity, not the administrator. |
| Expiry / revocation with an open WebSocket | No later read or mutation beyond the defined session/policy boundary; reconnect behavior is explicit. |
| Limited round, refresh, lost acknowledgment, reconnect | Same durable job and exact saved request; no refreshed allowance or repeated committed chunk. |
| Browser closes after accepted work | Accepted native work remains independent of the web connection; observe it later without a new authorization. |
| Credential, gateway or Blob failure | Visible sanitized failure; no local fallback, silent empty job, or automatic mutation retry. |
| Stop and cost observation | Record owned web/agent/session state and retained resources; distinguish application stop from plan deletion/billing. |

Local tests must exercise the chosen public authorization/transport seams
before the cloud probe. The identity fixtures must represent the selected
trusted ingress contract; forged local headers cannot establish that Azure
asserts them. The final direct-call and WebSocket checks require separately
approved live evidence.

## Inputs needed before resource operations

Confirm the allowed operator's tenant/object identity, web hosting reuse or
new-resource choice, compatible region/runtime, administrative permissions
for the chosen identity setup, effective gateway role assignments, an
unapproved test identity, and the maximum duration/cost plus stop procedure.
Keep environment-specific values outside the public contribution.

If any authorization boundary is unresolved, report the probe as **no-go**
rather than deploying a login-only workbench and treating it as protected.
G0 remains incomplete until the applicable live probes pass.
