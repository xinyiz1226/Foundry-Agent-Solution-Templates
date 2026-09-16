# Guarded backend update and web package

**Observed:** September 15, 2026. The existing synthetic backend now has
version **2**, with the current-job discovery and lifecycle fixes. Foundry
reports that version as `active`, but the agent endpoint remains
**disabled**. After a subsequent explicit approval, the web ZIP completed
remote Oryx build and deployment. Its existing Linux App Service remains
**stopped with public access disabled**. A later bounded private probe
confirmed platform startup. A subsequent real-caller test verified an
operator's read-only version-2 `current` request and an unapproved user's
denial on that same route. Streamlit/browser and web-managed-identity
integration remain unverified. **G0 is incomplete.**

Neither slice enabled an endpoint, invoked a hosted session, called a real
model, or changed directory configuration. The later approval added only
the dedicated deployment container and its operator upload grant, as
recorded below. The retained B1 plan continues billing.

## Separate source artifacts

The source packager now supports an explicit web target. From
`information-extraction`, with the corresponding optional dependencies
already installed:

```powershell
& .\.venv\Scripts\python.exe .\scripts\package_source.py `
    --output .\.local-data\deployment-20260915\hosted-update.zip --check
& .\.venv\Scripts\python.exe .\scripts\package_source.py `
    --target web `
    --output .\.local-data\deployment-20260915\cloud-workbench.zip --check
```

The default target remains hosted. Without `--output`, the web target uses
`.local-data\cloud-workbench.zip`. Keep historical probe archives separate;
do not overwrite an archive referenced by a previous deployment receipt.

| Target | Files | Entry | Root dependency manifest |
| --- | --- | --- | --- |
| Hosted | 14 | `main.py` | Existing `requirements.txt`, selecting `.[hosted]` |
| Web | 15 | `cloud_workbench.py` | `requirements-web.txt` mapped to `requirements.txt`, selecting `.[cloud-workbench]` |

Both targets use the existing deterministic ZIP, explicit allowlist,
source-link rejection, file/total size bounds, and isolated wheel/import
checks. The web ZIP excludes the hosted/native-task worker, Blob and
real-model adapters, local launcher, tests, credentials, and local data.
It contains no wrapper directory above the application root.

The web check executes the actual cloud entry point with missing login
configuration and verifies fail-closed behavior without network or service
calls. It does not validate Linux/Oryx dependency installation, live Easy
Auth, WebSocket headers, managed identity, or Foundry gateway access.

Recorded artifacts, stored locally and excluded from Git:

| Artifact | Bytes | SHA-256 |
| --- | --- | --- |
| Hosted update | 104002 | `1b29accc0b98e0f50eac44c18bd52af03cf679bc135642103e5ba1b2d29fa026` |
| Web | 84879 | `97cd7d7892bbe678c5bf29b13db08b6f060a4235cc9b11374001b95eea4b3c8d` |

The hosted archive's included application source matches commit
`a5d1ec47a44ab6b7ad01fede79233ce709f9132b`. The web dependency manifest and
target selection are introduced in this packaging change. Archive digests
identify source bytes, not remotely resolved dependency versions.

## Backend version 2: observed control-plane result

The update used the existing `information-extraction-g0` agent in the
existing project. Before submission, its disabled state, runtime identity,
historical source binding, and reviewed archive digest were checked.
Version creation preserved the six application settings, synthetic job and
ledger namespace, `0.5` CPU, `1Gi` memory, and production-only credentials.
No new storage access was granted.

The new definition explicitly selects:

```python
ProtocolVersionRecord(protocol="invocations", version="2.0.0")
```

The official azd implementation maps YAML protocol versions directly into
`HostedAgentDefinition.ProtocolVersions` for both source and image
deployment; it defaults to Responses `2.0.0` when none are supplied.
Together with the migration contract, this resolved which SDK field to
use, not whether every runtime behavior would work.
See [the primary-source reconciliation](workbench-hosting-auth-research.md#reconcile-protocol-evidence-before-changing-deployment).

The target service accepted the explicit Invocations `2.0.0` declaration.
Subsequent reads verified version 2 `active`, the exact **service-reported
code content hash** above, the requested protocol record, unchanged runtime
principal/settings/resources, and the endpoint still disabled. Version 1
and its historical `1.0.0` declaration remain retained. The four historical
sessions still report `idle`; no new session was invoked.

Two initial submissions were rejected with HTTP 400 because the in-memory
ZIP stream lacked the required `.zip` filename. Version inventory was
reconciled before resubmission. Supplying a named, seekable stream corrected
that upload contract; neither rejection was a protocol-version failure.
There was no downgrade, endpoint enablement, or automatic mutation retry.

`active` is provisioning status, **not application or authorization
acceptance**. This round did not execute `current`, start/resume, Blob
operations, resilient-task recovery, or protocol-2 caller-context
propagation. Historical version-1 smoke results are not version-2 runtime
evidence. A future bounded probe must verify its actual version/routing and
the runtime contract before claiming those gates passed.

## Private web deployment: approved and completed

The existing App Service has public access disabled. Do not enable public
SCM access simply to push a ZIP. Microsoft documents remotely hosted
package pull through ARM OneDeploy / `az webapp deploy --src-url` for
network-secured applications. Python source deployment also needs an
approved remote-build configuration, including
`SCM_DO_BUILD_DURING_DEPLOYMENT=true`, and a Streamlit startup command for
`cloud_workbench.py`, not the local launcher or hosted entry point.

The staging location is a **separate private deployment container
in the existing storage account**. The synthetic agent can write its ledger
container, so that container is not a trusted location for web code.
Do not grant the agent or web runtime deployment-artifact write access.
Use only approved deployment-operator permissions and a short-lived,
read-only, single-blob user-delegation SAS for the pull. Keep its URI in
memory; never print or commit it.

The first preparation round stopped without creating those resources
because approval had not been received. The operator subsequently approved
private staging and necessary upload permissions on September 15, 2026.
The following operations then completed without opening ingress or
starting the web application:

| Surface | Observed result |
| --- | --- |
| Private container | `workbench-deployments-8d99d29b` in the existing storage account, `publicAccess: None`, with an explicit deployment-ownership marker |
| Operator grant | Storage Blob Data Contributor at that container only; no new account/subscription-wide data role |
| Delegation key | Existing effective control permission was checked, then actual short-lived key issuance succeeded; no additional Delegator role was needed |
| Source blob | Digest-named ZIP, create-only upload, ownership/source metadata, and full download SHA-256 verification against the web digest above |
| Deployment credential | User-delegation SAS for one blob, read-only, HTTPS-only, 30-minute lifetime; no token or package URI printed or written to local files/Git |
| App settings | `SCM_DO_BUILD_DURING_DEPLOYMENT=true`; Streamlit usage telemetry disabled; existing settings and login secret preserved by protected readback comparison |
| Startup | Python 3.13 running only the cloud Streamlit entry, on `0.0.0.0:8000`, headless, with CORS/XSRF protections enabled and the configured browser hostname/HTTPS port |
| Submission | One ARM OneDeploy request with `type: zip`, `clean: true`, `restart: false`; HTTP 202 was treated as acknowledgment, not completion |
| Completion | Deployment `35ae2a6eadf9420ab0f3d0bb6a0ed14f` reached `status: 4`, `complete: true`, `active: true`; ended at `2026-09-15T08:45:23.7950097Z` |
| Build evidence | ARM deployment logs include an Oryx build and a deployment-success message |
| Final boundaries | Site `Stopped`, public access `Disabled`, existing Easy Auth and slot-sticky secret retained; agent endpoint still disabled |

The source artifact is the unchanged 84,879-byte web ZIP built from
`91725b68baf224eabcaf1dc6df961bdc25a79dd0`. The source hash is an artifact
identity, not a hash of the expanded remote installation or a lock on
remotely resolved dependency versions.

Deployment used the documented ARM request directly. The installed CLI's
`--src-url` path logs its package URL, so it was not used with a SAS on the
command line. Polling used ARM rather than opening public SCM access.
The supplied deployment tag was not retained by the service. The sole
non-temporary deployment on this previously empty owned site was correlated
with the acknowledged submission and observed first building, then
successful. Subsequent verification pinned that deployment ID rather than
following an arbitrary later `latest` deployment.

Independent subscription-scoped reads still returned exactly one direct
assignment for each runtime identity: the web identity's agent-scoped
Foundry Agent Consumer, and the agent identity's original ledger-container
Blob contributor. Neither received a deployment-container grant. This
does not replace the separate inherited-group/effective-caller audit.

The approved operator grant and source blob remain for subsequent
deployments; SAS expiry is not resource cleanup or revocation of that role.
The source-deployment slice did not start the application. A subsequently
approved private startup probe is recorded below; browser functionality
remains unverified. Public access and agent enablement still require the
finite synthetic probe boundary, including a real
unapproved non-administrator test identity, direct/alternate-route access
checks, WebSocket expiry/reconnect, and owned-session stop conditions.
No real-model invocation is authorized by this slice.

Sources: [network-secured ZIP deployment](https://learn.microsoft.com/en-us/azure/app-service/deploy-zip#deploy-to-network-secured-apps),
[Python build automation](https://learn.microsoft.com/en-us/azure/app-service/configure-language-python#customize-build-automation),
and [user-delegation SAS permissions](https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blob-user-delegation-sas-create-cli).
ARM status and build evidence used [OneDeploy status](https://learn.microsoft.com/en-us/rest/api/appservice/web-apps/get-one-deploy-status?view=rest-appservice-2024-11-01)
and [deployment logs](https://learn.microsoft.com/en-us/rest/api/appservice/web-apps/list-deployment-log?view=rest-appservice-2024-11-01).

## Bounded private startup: platform confirmed, integration still gated

The operator approved controlled startup and synthetic integration at
`2026-09-15T19:35:10.633+08:00`. Because no ordinary unapproved test identity
was available, this round kept public access disabled and the Foundry
agent disabled. It did not create a test user, loosen permissions, invoke
the agent, or call a model.

The first private start changed ARM site state to `Running`, but ten
observations returned worker state `Unknown` and effectively empty
container logs. This was insufficient startup evidence, not a confirmed
application error. The site was stopped before the next attempt.

One additional bounded probe temporarily enabled **Always On** to trigger
platform warmup without public traffic. The worker progressed through
network setup, Python 3.13 image pull, container creation, warmup, and auth
container startup. Retained ARM container logs recorded:

| Signal | UTC timestamp |
| --- | --- |
| Platform startup probe succeeded | `2026-09-15T11:47:16.3529111Z` |
| Site started | `2026-09-15T11:47:36.8005197Z` |

Two runtime-status observations then reported `Started` with no recorded
last error. This supports the explanation that the original no-traffic
probe did not trigger useful worker startup/telemetry. It does not prove
that Always On is permanently required.

The original checker incorrectly expected worker state `Ready` and a
Streamlit banner in the platform-log stream, so its exit code was 1 despite
the platform success signals. The private checker now separates platform
startup (`Started` plus the successful platform-probe signal) from
application functionality. Replay of the captured observations accepts
the platform result while rejecting unknown, starting, errored, and
probe-unconfirmed states. Original receipts and their exit outcomes were
retained rather than relabelled.

Each probe admitted at most ten status/log observations within a
300-second polling window. HTTP operations and cleanup had their own
timeouts; this is not a hard wall-clock or billing cap. Cleanup stopped
the owned site, restored `Always On=false`, and verified public access
remained disabled and Easy Auth unchanged. The retained B1 plan still bills.

**Platform startup is not a browser acceptance result.** No Streamlit
session, operator login, expired/reconnected WebSocket, web-identity
gateway call, or version-2 synthetic round was exercised. A same-tenant,
non-administrator identity not assigned to the web application was
requested for negative access tests, but was not supplied during that
startup round. The later real-caller test below addresses that narrow
direct-route gate. Do not replace it with an administrator test, invent a
test identity, or infer isolation from the stopped/private site.

Sources: [Always On platform requests](https://learn.microsoft.com/en-us/azure/app-service/configure-common#configure-general-settings)
and [ARM container logs](https://learn.microsoft.com/en-us/rest/api/appservice/web-apps/get-web-site-container-logs?view=rest-appservice-2024-11-01).

## Real caller access: positive current read and negative direct call

The operator subsequently supplied a test user's object ID and completed
interactive sign-in using a separate local Azure CLI profile. The profile
did not replace the operator's credentials. Authenticated Graph `/me`
confirmed the expected test identity; no password or token was requested
in chat or committed.

Read-only preflight found an enabled same-tenant Member with no transitive
memberships, application assignments, active directory roles, or matching
Azure role assignments in the inspected subscription and agent-ancestor
scopes. The subscription resource-role eligibility query also returned no
matching rows. **Directory PIM eligibility remains unverified:** Graph
denied that query because the existing operator token lacked a suitable
delegated read scope. No additional scope, role, or app assignment was
granted to bypass that limitation.

On September 15, 2026, from `13:12:19Z` to `13:12:58Z`, one bounded probe
temporarily enabled the owned agent. It admitted only two requests, both
with the identical body `{"action":"current"}`, to:

```text
POST <project-endpoint>/agents/information-extraction-g0/endpoint/protocols/invocations?api-version=v1
```

Before enabling, the probe verified the version-2 service source hash,
runtime identity, active latest-version binding, disabled endpoint, and
idle baseline sessions. Both callers' Foundry access tokens were checked
cryptographically against the tenant's signing keys, expected issuer and
audience, validity claims, tenant and object ID. The test token carried no
directory-role `wids` claim. Actor credentials were never swapped into
shared process environment variables or forwarded as body identity fields.

| Caller | Observed result |
| --- | --- |
| Authorized operator, using its own CLI profile | HTTP **200**, `synthetic_only: true`, with `current` and `pending_request` fields and one session selector |
| Unapproved test user, using its independently authenticated CLI profile | HTTP **403**, gateway code `UserError`, no synthetic application projection and no session selector |

This was an actual unauthorized-user request to an **enabled** endpoint,
paired with a working positive control, not a 403 caused by endpoint
disablement. It establishes denial for this caller and this route only.
It does not prove that every other user, inherited permission, alternate
Responses/version/session route, or future published alias is isolated.
The positive caller was the operator, **not the web managed identity**.

No start/resume operation, extraction attempt, or real-model call was
sent. There was no automatic invocation retry. The sole new session was
matched to the positive response selector, explicitly stopped, and
observed `idle`. The four baseline sessions were not stopped again.
Cleanup disabled the agent; an independent read found all five retained
sessions idle. The web app remained stopped/public-access-disabled with
`Always On=false` and its authentication configuration intact.

The remaining browser/Easy Auth, web-managed-identity gateway, WebSocket
expiry/reconnect and bounded synthetic-round checks require a
user-present test window. Initially, readiness for a maximum ten-minute
browser window was requested without a response; no public ingress was
opened at that point. The subsequently authorized attempt is recorded below.
CLI sign-in and this direct-route denial do not close those gates.

## Anonymous login precheck: aborted window and diagnosis

The first user-present window was aborted **before browser handoff**.
Public opening was attempted at `2026-09-15T23:58:48.749837Z`, but the
anonymous-login assertion failed. Cleanup completed at `23:58:59.523372Z`:
public access disabled, site stopped, Always On restored to false, and
agent disabled. No new agent session was created; all five retained
sessions were idle. No extraction or real-model call occurred.

The original precheck saved its HTTP status **after** the assertion, so
the failed receipt contains neither the actual status nor redirect
classification. That lost response cannot be reconstructed, and this
failure alone proves neither successful login protection nor its cause.
The historical receipt was preserved without invented response details.

A subsequent read-only comparison confirmed that the actual default and
bound hostname, probe URL, Streamlit browser hostname, and registered
Entra callback agree. Easy Auth still requires authentication with
`RedirectToLoginPage`, the exact tenant-specific v2 issuer, and the
operator allowlist. No hostname, authentication, role, or deployment
change was justified by that comparison.

The operational precheck now saves metadata **before** its assertion,
using [`scripts/web_login_diagnostics.py`](../scripts/web_login_diagnostics.py).
The standard-library helper records status, the selected Accept profile,
a bounded content-type classification, a UUID-shaped request ID, and a
strict redirect classification. Only the configured site's AAD login
path or the configured tenant's v2 authorization path can pass the
redirect gate. Unexpected hosts/paths, raw OAuth query/fragment values,
cookies, authorization headers, and response bodies are not persisted.
An arbitrary 200, 401, or 403 is not treated as a successful login redirect.

Local regression coverage exercises failed-response retention and
redaction. A private controller fixture also verifies that a failed
browser gate saves those diagnostics and still closes the site and agent.
These checks validate observability and cleanup, not live browser login.

### Bounded web-only differential probe

On September 16, 2026, a separate diagnostic kept the agent **disabled**
throughout. After private warmup, it allowed at most three anonymous root
GETs within a 60-second public-access budget. Each request had a fresh
cookie jar, no credentials, no redirects, and the same Requests User-Agent;
only Accept changed. No response body was read or saved.

| UTC observation time | Accept | Status | Location |
| --- | --- | --- | --- |
| `00:14:09.292251Z` | `*/*` | **401** | Absent |
| `00:14:20.434938Z` | `text/html` | **401** | Absent |
| `00:14:31.702516Z` | `*/*` | **401** | Absent |

No content type or UUID-shaped `x-ms-request-id` was available in these
responses. **Changing Accept alone did not produce a login redirect.**
No transition was observed over the sampled interval; longer propagation
or differences between a real browser and Requests have not been ruled
out. The original window's missing response remains unknown.

The configured unauthenticated action was still `RedirectToLoginPage`,
the redirect provider was `azureActiveDirectory`, and the AAD provider was
enabled. Microsoft's [authentication overview][anonymous-auth-doc] describes
browser redirects and native-client 401 responses, but does not specify a
header-detection algorithm sufficient to explain this trace. Do not infer
a User-Agent root cause from the documentation alone.

Opening was attempted at `00:14:07.376024Z`; closure was verified at
`00:14:38.786198Z`, **31.4 seconds** later and before the fixed
`00:15:07.376024Z` deadline. An independent watchdog verified closure.
A subsequent independent control-plane read confirmed the site stopped,
public access disabled, Always On false, the agent disabled, and the same
five idle sessions. No baseline session was stopped, no new session was
created, authentication was unchanged, and no model call occurred. The
backup session automation was cleared.

At this checkpoint, root cause and browser acceptance remained unresolved.
The three-request allowance was exhausted and did not authorize reopening.
The separately approved browser comparison below followed without
weakening authentication or enabling the agent. A 401 from Requests is
not a failed human sign-in, but it also does not satisfy the browser-redirect
gate.

### Browser-versus-script and explicit-login comparison

The operator separately approved this next diagnostic at
`2026-09-16T08:19:23.238+08:00`. It retained the 60-second public-access
budget and at most three initial site GETs, with the agent disabled
throughout. The browser was an isolated, headless instance of the installed
Microsoft Edge **153.0.4234.32**, not the operator's existing browser profile.
Playwright was installed only in a private diagnostic environment; no
application dependency, source archive, or Azure configuration was changed.

All three requests used `Accept: text/html`. The first comparison changed
the client from Requests to Edge; the next changed only the navigation path
within the same browser implementation. Each browser sample used a fresh
context with no previous login cookies. CDP interception admitted one
navigation per context and aborted at response headers, before any
redirect, response-body processing, or additional page request.

| UTC sample start | Client | Path | HTTP result |
| --- | --- | --- | --- |
| `00:29:02.926099Z` | Requests | `/` | **401**, no Location |
| `00:29:05.320006Z` | Isolated headless Edge | `/` | **302**, configured tenant's v2 authorization endpoint |
| `00:29:06.249056Z` | Isolated headless Edge | `/.auth/login/aad` | **302**, same tenant's v2 authorization endpoint |

Both browser redirects matched the expected HTTPS host
`login.microsoftonline.com` and configured tenant's
`/oauth2/v2.0/authorize` path. OAuth query values, cookies, tokens, and
bodies were not recorded. The receipt's `navigation_error` flag reflects
the **deliberate post-header abort**, not a failed authentication attempt.
The Entra authorization endpoint was not followed, and no login was submitted.

This identifies a **precheck-client mismatch**: requiring a Requests GET
to redirect was not a valid substitute for checking browser navigation
on this deployment. The observed browser login initiation works without
an authentication change. It does not isolate a particular User-Agent,
Fetch header, transport difference, or timing effect, and it does not
retroactively recover the first window's missing response.

The private browser-window controller now uses one bounded, isolated
browser navigation for its anonymous gate instead of Requests. It still
persists sanitized evidence before asserting the expected redirect, fails
closed on browser failure or an unexpected response, and has no API-client
fallback or 401-as-success exception. A controller regression first failed
under the old implementation with Requests 401/browser 302, then passed
after this change. Real-Edge loopback fixtures separately verified status
capture, the on-wire Accept value, fresh cookies, and no followed redirects.
These fixtures do not submit user credentials or call Azure.

Read-only configuration checks also found auth configuration version `v2`,
runtime `~1`, the `/.auth` prefix, no file-based override, and no examined
auth-override app settings. No change to the tenant, provider, callback,
secret, allowlist, roles, or deployment was needed for the observed redirects.

Public opening was attempted at `00:29:00.360516Z`; closure was verified
at `00:29:13.588605Z`, **13.2 seconds** later and before the fixed
`00:30:00.360516Z` deadline. The independent watchdog and a later independent
control-plane read verified the site stopped, public access disabled,
Always On false, the agent disabled, and the same five idle sessions.
No baseline session was stopped, no new session was created, and no
model call occurred. The backup session automation was cleared.

**Browser login initiation is demonstrated; G0 is still incomplete.**
Operator sign-in/callback, unapproved-user rejection, the protected
Streamlit page, web-managed-identity calls, and WebSocket expiry/reconnect
still require a separately approved user-present window. This diagnostic
did not reopen that full browser window.

### Human browser window: opened, then closed without an acceptance result

The operator approved continuing at `2026-09-16T09:05:03.468+08:00`.
A new one-time receipt preserved all earlier receipts and bounded the
attempt to at most ten minutes of public access and two new agent sessions.
Preparation had a separate admission deadline; an independent watchdog
and backup session automation guarded cleanup. Only login and read were
permitted, not start/resume/retry or real-model calls.

The corrected isolated-browser precheck passed with **302** to the
configured tenant's v2 authorization endpoint. Public opening was attempted
at `01:15:00.799918Z`; the fixed closing deadline was `01:25:00.799918Z`.
The operator browser canvas was opened, with instructions to use an
independent InPrivate browser for the unapproved account.

**No human acceptance result was obtained.** The optional checklist
terminal could not be read because it was not running. The subsequent
interactive result request returned that the user was unavailable, and no
checklist result file was created. This is missing observation, **not**
evidence that either account succeeded or failed to sign in.

The attempt was therefore closed early at `01:17:26.036732Z`, approximately
**2 minutes 25 seconds** after opening was attempted. Independent readback
verified the site stopped, public access disabled, Always On false, agent
disabled, and the same five idle sessions, with no new sessions. No baseline
session was stopped. The waiting controller was stopped only after resource
cleanup had been verified; backup automation was then cleared.

The browser precheck is now live-demonstrated through the actual window
controller, but operator sign-in/callback, unapproved-user rejection,
protected-page/managed-identity behavior, and WebSocket acceptance remain
unverified. Another window requires fresh user-present approval; this
attempt is closed and is not automatically retried or extended.

[anonymous-auth-doc]: https://learn.microsoft.com/en-us/azure/app-service/overview-authentication-authorization#unauthenticated-requests

## Local verification

After adding anonymous-response diagnostics, the full optional suite
passed **288 tests**. The dependency-free route passed **62**, with **226**
optional tests skipped. At the earlier deployment checkpoint, both actual archives
passed isolated wheel/entry checks with zero network calls; the web entry
also reported zero service calls and a blocked missing-login configuration.
These are local checks, not a completed cloud browser demonstration.
