# Workbench hosting and operator-authorization research

**Sources retrieved:** September 15, 2026. **Scope:** primary-source research
and local SDK inspection, not deployment or a target-resource permissions
audit. No Azure resource changes or real model calls were made.

## Recommendation

Prefer one Linux App Service running Streamlit, Microsoft Entra built-in
authentication, an explicit single-operator policy, and a dedicated web
managed identity calling the Foundry agent endpoint. Keep native execution
and Blob persistence outside the web process. This is a recommendation,
subject to the [implementation gates](workbench-hosting-auth-plan.md).

The important correction is that current documentation **does support
agent-scoped endpoint RBAC**. However, it is additive with broader grants:
assigning a narrow role to the web identity cannot remove existing callers'
inherited access. Reuse the shared project only after effective access and
direct-call negative tests establish the required boundary. A new project
under permissive ancestors is not sufficient isolation by itself. [S1][S2]

## 1. Hosting facts and unresolved deployment checks

App Service's built-in Python runtime is Linux-only and supports custom
startup commands. Linux WebSockets are always enabled; `webSocketsEnabled`
does not apply to Linux. The documented Free Linux limit is five WebSocket
connections. These facts establish a hosting candidate, not a successfully
deployed Streamlit configuration. [S3][S4]

The package currently requires Python 3.13+. Microsoft documents runtime
discovery with `az webapp list-runtimes --os linux`; that check was **not run**
here. Verify a supported compatible runtime, dependency installation,
application root, expected listener port, and readiness in the approved
environment. Run the Streamlit server, not Gunicorn against a Streamlit
script. Keep CORS/XSRF protections. Do not lower Python requirements to fit
an old documentation example. [S3][S4][S5]

One Basic B1 instance is a possible initial estimate, not a guaranteed
capacity requirement or an approved purchase. A compatible existing Linux
plan may be preferable. Dedicated-plan charges continue for retained plan
instances; an empty plan can still incur charges. Stopping the application
must not be presented as eliminating plan cost. [S6]

Container Apps is also viable: its documented ingress supports WebSockets,
and it offers built-in authentication and Consumption scale-to-zero billing.
App Service is recommended here to avoid introducing a UI container and
environment/revision/scaling choices unless existing infrastructure or a
measured runtime/cost requirement makes Container Apps simpler. Neither
hosting option fixes permissive Foundry authorization. [S7]

## 2. Human operator authorization

Single-tenant login does not restrict access to named operators. Use a
single-tenant web registration/enterprise application, require
authentication, require enterprise-app assignment, and assign the approved
individual. Assignment-required applications need the documented
administrator-consent setup. Global Administrators are exempt from that
assignment gate, so assignment alone is not an application operator
allowlist. [S8]

Recommend an application-side allowlist of tenant/object-ID pairs before
protected reads and commands. Use verified identifiers, not email suffixes
or display names. This does not prevent trusted administrators from changing
the application or its policy. Individual assignment avoids the initial
need for group-assignment licensing and group-membership semantics;
enterprise-app group assignment requires Entra P1/P2 and does not cascade
through nested groups. [S8][S9]

App Service also documents `authsettingsV2` restrictions:
`allowedApplications` checks application IDs (`appid`/`azp`), whereas
`allowedPrincipals.identities` checks object IDs (`oid`) and has a 500-total-
character limit. Configured requirements combine with AND; failed checks
return 403. They are different controls, not interchangeable lists of
operators. Browser-cookie and WebSocket behavior still need validation.
[S10]

Within App Service's protected authentication boundary,
`X-MS-CLIENT-PRINCIPAL` carries platform-injected Base64 JSON claims that
external requests cannot supply as protected headers. It is not itself a
signed JWT. Account for documented claim-name mapping and fail closed on
missing, malformed, ambiguous or wrong-tenant claims. This App Service
contract must not be assumed at the Foundry container. [S11]

### WebSocket expiry and revocation remain a gate

Streamlit's upstream `st.context.headers` documents headers from the
**initial request**. Rechecking the same in-memory allowlist against that
initial identity is not fresh verification of enterprise-app assignment,
directory membership, or the Entra session. [S12]

Define an enforceable application-session lifetime, policy refresh and
invalidation rules, and acceptable revocation latency before deployment.
Test operator removal, enterprise-app unassignment, logout, expiry,
reconnection, and later reads/mutations over an already-open WebSocket.
The inspected identity-header and Streamlit contracts do not establish
instant revocation. Upstream Streamlit `develop` is not a substitute for
checking the installed/deployed version. [S11][S12]

## 3. Foundry endpoint, token and least-privilege grant

The current documented agent endpoint uses:

```text
POST https://<account>.services.ai.azure.com/api/projects/<project>/agents/<agent>/endpoint/protocols/invocations?api-version=v1
Entra token resource: https://ai.azure.com
SDK scope:           https://ai.azure.com/.default
```

This is distinct from the container-local `/invocations`, an ARM audience,
and the web login application's audience. Agents use Entra authentication,
not an API-key substitute. [S13][S14]

The documented agent-endpoint data action is:

```text
Microsoft.CognitiveServices/accounts/AIServices/endpoints/interact/action
```

The recommended built-in endpoint role is **Foundry Agent Consumer**:
`eed3b665-ab3a-47b6-8f48-c9382fb1dad6`. Its documented narrow scope is:

```text
/subscriptions/<subscription>/resourceGroups/<resource-group>/providers/Microsoft.CognitiveServices/accounts/<account>/projects/<project>/agents/<agent>
```

Agent-scope assignment is evaluated for agent endpoint access, not broader
agent management. Project-scope Consumer reaches all agent endpoints in
that project. Current documentation describes narrower assignment through
CLI; do not substitute an account-scoped portal grant for the proposed
agent scope. Agent **applications** instead use their separate
`.../applications/invoke/action` permission and scope. [S1][S15]

Review ancestor grants, group membership, custom roles, session management,
and agent/grant modification rights. An ordinary user with an effective
invoke grant can bypass a web login screen. Azure Owner/Contributor are not
automatically data-plane callers merely because they manage resources, but
administrative powers can change the access boundary. Foundry User at
project scope also has documented session-management access. [S2][S15][S16]

## 4. Trusted context is version-specific and opaque

For container protocol **2.0.0**, the runtime contract says
`x-agent-user-id` and `x-agent-foundry-call-id` are platform-generated from
verified identity. The user identifier is an opaque global per-user key;
the call identifier is opaque per request and is forwarded unchanged to
supported Foundry services. The documentation does not define either as an
Entra object ID, tenant ID, group claim, or locally decoded user token. [S17]

The same contract distinguishes caller-controlled `x-client-*` pass-through
headers from platform identity. Incoming credential headers, including
`Authorization`, as well as `Cookie`, `Host`, and `x-forwarded-*`, are not
forwarded to the container. Therefore, do not invent gateway-token JWT
validation inside the handler or trust an arbitrary asserted user header.
[S17]

Local inspection of Core 2.1.0 and Invocations 1.1.0 found that the endpoint
copies identity headers into `FoundryAgentRequestContext`; this is SDK
plumbing, not an independent ingress verification mechanism. Its
`platform_headers()` forwards the opaque call ID, not `user_id`, for
downstream identity resolution. A backend allowlist of explicitly enrolled
opaque callers would need separate protocol, managed-identity mapping,
enrollment and spoofing validation. It is not selected here.

### Reconcile protocol evidence before changing deployment

The migration/isolation documents require container protocol 2.0.0 and
identify supporting SDK minimums. They include deprecation dates for older
protocol/backend paths. Meanwhile, this repository's historical successful
probe records `ProtocolVersionRecord(protocol="invocations",
version="1.0.0")` with Projects 2.4.0. That record does not establish the
new identity guarantee, and the documentary version/timeline discrepancy
has not been reconciled with the target service. [S16][S18]

REST API `v1`, SDK package versions, protocol records, and the platform's
container identity contract must not be treated as interchangeable version
numbers. Preserve the historical result and source hash. Resolve the exact
supported declaration and test identity behavior in a separately approved
probe; do not silently upgrade a protocol or infer verified identity from
the newer installed SDK alone.

The current migration documentation labels hosted agents GA, while native
resilient execution remains explicitly Preview with separate limitations.
Neither statement upgrades the evidence or readiness of this template.
[S18][S19]

## 5. Service identity, OBO and delegation are different choices

A system-assigned App Service managed identity can represent the web service
without a backend client secret and has a lifecycle tied to that web app.
The human operator then needs no direct Foundry or Blob grant for this
path. The hosted agent's runtime identity is separate and must be the
actual principal used for its Blob grant. The web service identity does
not automatically preserve the human identity at Foundry. [S20][S18]

OBO is a user-token exchange pattern requiring the correct incoming audience,
delegated scopes, consent and confidential-client configuration. It does
not convert an app-only MI token into a human token. An end-to-end
Streamlit/Easy Auth/Invocations OBO configuration was not verified here and
is not the baseline. Forwarding an Easy Auth token is not OBO; OBO would
not itself make a user's Foundry rights usable only through this UI. [S21]

Foundry separately documents `x-ms-user-identity` for trusted middle-tier
delegation, requiring:

```text
Microsoft.CognitiveServices/accounts/AIServices/agents/endpoints/UserIdentityImpersonation/action
```

That permission is absent from built-in roles; an unprivileged caller
receives 403. The middle tier remains responsible for the authenticated
user binding and session routing. Documented delegated sessions do not
automatically fence delegated users from one another. Do not add this
extra permission to the single-operator baseline. [S15][S16]

## 6. Login credentials, storage and cost boundaries

Backend managed identity does **not** automatically make web login
secretless. The standard Easy Auth setup uses a login client credential
with a rotation owner. A documented alternative uses a user-assigned
managed identity and federated identity credential; select that explicitly
if required by policy rather than claiming it is already configured.
[S10][S20]

For Blob, distinguish authorization-private containers from network-private
endpoints. A private endpoint does not automatically disable public endpoint
access. The existing synthetic slice established identity-gated data access,
not a new private-network design. Recommend the actual runtime identity's
Storage Blob Data Contributor grant at the required container scope; give
the web identity no Blob grant when results travel through the backend.
No browser-delivered SAS is needed for this slice. [S22][S23]

Native resilient tasks do not restore local variables or guarantee
exactly-once model side effects. Keep existing application claims,
checkpoints and bounded authorizations. Current lifecycle documentation
describes idle compute deprovisioning, but active polling, sessions, Blob
operations and web-plan charges remain separate cost concerns. No timeout
or deletion behavior was validated against Azure in this research round.
[S19][S24][S6]

## Primary sources

Links below identify the retrieved official source documents; branch links
can evolve after the retrieval date. Interpret version-sensitive findings
with the explicit caveats above.

- **[S1]** [Foundry RBAC: Consumer and single-agent scopes](https://github.com/MicrosoftDocs/azure-ai-docs/blob/main/articles/foundry/concepts/rbac-foundry.md#L60-L126).
- **[S2]** [Azure RBAC: additive grants, scope and data-plane distinctions](https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/role-based-access-control/overview.md#L83-L113).
- **[S3]** [App Service Python runtime discovery and custom startup](https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/app-service/configure-language-python.md).
- **[S4]** [App Service Linux FAQ: ports and WebSockets](https://github.com/MicrosoftDocs/SupportArticles-docs/blob/main/support/azure/app-service/faqs-app-service-linux-new.md).
- **[S5]** [Streamlit server configuration](https://github.com/streamlit/streamlit/blob/develop/lib/streamlit/config.py).
- **[S6]** [App Service plan costs](https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/app-service/overview-hosting-plans.md#L67-L94) and [retained empty plans](https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/app-service/app-service-plan-manage.md#L131-L136).
- **[S7]** Container Apps [ingress](https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/container-apps/ingress-overview.md), [authentication](https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/container-apps/authentication.md), and [billing](https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/container-apps/billing.md).
- **[S8]** [Restrict an Entra app to assigned users](https://github.com/MicrosoftDocs/entra-docs/blob/main/docs/identity-platform/howto-restrict-your-app-to-a-set-of-users.md#L15-L67).
- **[S9]** [Enterprise-app individual/group assignment requirements](https://github.com/MicrosoftDocs/entra-docs/blob/main/docs/identity/enterprise-apps/assign-user-or-group-access-portal.md#L18-L39).
- **[S10]** [App Service Entra provider configuration, authorization and login credentials](https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/app-service/configure-authentication-provider-aad.md).
- **[S11]** [App Service injected identity claims](https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/app-service/configure-authentication-user-identities.md#L20-L45).
- **[S12]** [Streamlit initial-request context headers](https://github.com/streamlit/streamlit/blob/develop/lib/streamlit/runtime/context.py#L178-L222).
- **[S13]** [Hosted-agent migration: endpoint invocation](https://github.com/MicrosoftDocs/azure-ai-docs/blob/main/articles/foundry/agents/how-to/migrate-hosted-agent-preview.md#L480-L516).
- **[S14]** [Foundry authentication audiences and support](https://github.com/MicrosoftDocs/azure-ai-docs/blob/main/articles/foundry/includes/concepts-authentication-authorization-foundry-content.md).
- **[S15]** [Hosted-agent endpoint and impersonation permissions](https://github.com/MicrosoftDocs/azure-ai-docs/blob/main/articles/foundry/agents/concepts/hosted-agent-permissions.md#L425-L485).
- **[S16]** [Session isolation, delegation and protocol caveats](https://github.com/MicrosoftDocs/azure-ai-docs/blob/main/articles/foundry/agents/how-to/isolate-sessions-per-user.md).
- **[S17]** [Hosted runtime identity and header forwarding contract](https://github.com/MicrosoftDocs/azure-ai-docs/blob/main/articles/foundry/agents/concepts/hosted-agent-contract.md#L318-L378).
- **[S18]** [Hosted-agent migration and version requirements](https://github.com/MicrosoftDocs/azure-ai-docs/blob/main/articles/foundry/agents/how-to/migrate-hosted-agent-preview.md).
- **[S19]** [Long-running resilient execution and Preview limitations](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/long-running-agent-resilience).
- **[S20]** [App Service managed identities](https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/app-service/overview-managed-identity.md).
- **[S21]** [Microsoft identity platform OBO flow](https://github.com/MicrosoftDocs/entra-docs/blob/main/docs/identity-platform/v2-oauth2-on-behalf-of-flow.md#L15-L68).
- **[S22]** [Container-scoped Blob data roles](https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/storage/blobs/assign-azure-role-data-access.md#L79-L103).
- **[S23]** [Storage private endpoint versus public endpoint](https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/storage/common/storage-private-endpoints.md#L23-L45).
- **[S24]** [Hosted-agent lifecycle](https://github.com/MicrosoftDocs/azure-ai-docs/blob/main/articles/foundry/agents/how-to/manage-hosted-agent.md).
