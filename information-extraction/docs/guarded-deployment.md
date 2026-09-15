# Guarded backend update and web package

**Observed:** September 15, 2026. The existing synthetic backend now has
version **2**, with the current-job discovery and lifecycle fixes. Foundry
reports that version as `active`, but the agent endpoint remains
**disabled**. The web application is **not deployed**. Its existing Linux
App Service remains stopped with public access disabled. **G0 is incomplete.**

This slice did not enable either endpoint, invoke a hosted session, call a
real model, change directory configuration, or add storage resources or
role assignments. The retained B1 plan continues billing.

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

## Web deployment blocker and next boundary

The existing App Service has public access disabled. Do not enable public
SCM access simply to push a ZIP. Microsoft documents remotely hosted
package pull through ARM OneDeploy / `az webapp deploy --src-url` for
network-secured applications. Python source deployment also needs an
approved remote-build configuration, including
`SCM_DO_BUILD_DURING_DEPLOYMENT=true`, and a Streamlit startup command for
`cloud_workbench.py`, not the local launcher or hosted entry point.

The proposed staging location is a **separate private deployment container
in the existing storage account**. The synthetic agent can write its ledger
container, so that container is not a trusted location for web code.
Do not grant the agent or web runtime deployment-artifact write access.
Use only approved deployment-operator permissions and a short-lived,
read-only, single-blob user-delegation SAS for the pull. Keep its URI in
memory; never print or commit it.

Approval was requested for the separate container and any necessary
container-scoped operator upload grant, but no answer was received. No
container, grant, SAS, package upload, OneDeploy request, remote-build
setting, or startup change was made. Inspect existing user-delegation-key
permissions before requesting any additional role; do not add an
account/subscription-wide data role for convenience.

After that infrastructure approval, deployment still must preserve the
login secret and Easy Auth settings, explicitly control restart behavior,
and verify remote build and startup. Public access/start and agent
enablement require the finite synthetic probe boundary, including a real
unapproved non-administrator test identity, direct/alternate-route access
checks, WebSocket expiry/reconnect, and owned-session stop conditions.
No real-model invocation is authorized by this slice.

Sources: [network-secured ZIP deployment](https://learn.microsoft.com/en-us/azure/app-service/deploy-zip#deploy-to-network-secured-apps),
[Python build automation](https://learn.microsoft.com/en-us/azure/app-service/configure-language-python#customize-build-automation),
and [user-delegation SAS permissions](https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blob-user-delegation-sas-create-cli).

## Local verification

The full optional suite passed **282 tests**. The dependency-free route
passed **56**, with **226** optional tests skipped. Both actual archives
passed isolated wheel/entry checks with zero network calls; the web entry
also reported zero service calls and a blocked missing-login configuration.
These are local checks, not a completed cloud browser demonstration.
