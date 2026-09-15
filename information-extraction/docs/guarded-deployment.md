# Guarded backend update and web package

**Observed:** September 15, 2026. The existing synthetic backend now has
version **2**, with the current-job discovery and lifecycle fixes. Foundry
reports that version as `active`, but the agent endpoint remains
**disabled**. After a subsequent explicit approval, the web ZIP completed
remote Oryx build and deployment. Its existing Linux App Service remains
**stopped with public access disabled**. A later bounded private probe
confirmed platform startup, not Streamlit/browser or backend integration
acceptance. **G0 is incomplete.**

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
requested for negative access tests, but was not supplied. That remains a
live integration gate; do not replace it with an administrator test,
invent a test identity, or infer isolation from the stopped/private site.

Sources: [Always On platform requests](https://learn.microsoft.com/en-us/azure/app-service/configure-common#configure-general-settings)
and [ARM container logs](https://learn.microsoft.com/en-us/rest/api/appservice/web-apps/get-web-site-container-logs?view=rest-appservice-2024-11-01).

## Local verification

The full optional suite passed **282 tests**. The dependency-free route
passed **56**, with **226** optional tests skipped. Both actual archives
passed isolated wheel/entry checks with zero network calls; the web entry
also reported zero service calls and a blocked missing-login configuration.
These are local checks, not a completed cloud browser demonstration.
