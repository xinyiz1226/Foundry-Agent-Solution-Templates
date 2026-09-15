# G0 synthetic hosted deployment

## Scope and authorization

This is the narrow hosted feasibility path for the
[native batch module](native-batch.md), not the complete Bicep/azd workbench
deployment. It uses an existing Foundry project and dedicated Blob container.
The operator must separately approve agent creation, hosted compute charges,
runtime identity permissions, and the validation/stop procedure.

The [September 15 hosted smoke record](hosted-smoke-results.md) documents the
observed source deployment, limit/replacement-session/resume path, and final
disabled endpoint. It is bounded evidence, not a full G0 gate.

The initial probe accepts the existing Foundry endpoint authorization
boundary: **callers effectively authorized to invoke the agent in the shared
project can use its synthetic operations**. It is not a designated-operator
allowlist, a multi-tenant application, or completed workbench authentication.
Only fixed fictional fixtures are appropriate for this probe.

Do not upload customer documents, expose arbitrary resource paths, or add
real model selection to make this probe more representative. Its purpose is
to establish transport, persistence, identity, and task-lifecycle behavior
without real model calls.

## Application settings and local package check

The production entry point is `main.py`. It always uses a fixed synthetic
model and Blob persistence; it has no real-model switch or local fallback.
Required application settings are:

| Setting | Purpose |
| --- | --- |
| `EXTRACTION_BLOB_ACCOUNT_URL` | HTTPS endpoint of the approved Blob account |
| `EXTRACTION_BLOB_CONTAINER` | Existing dedicated container |
| `EXTRACTION_BLOB_PREFIX` | Fresh experiment ledger namespace |
| `EXTRACTION_JOB_ID` | The single synthetic job this deployment may operate on |
| `AGENTSERVER_TASKS_BACKEND` | Must be `hosted` in production |
| `AZURE_TOKEN_CREDENTIALS` | Must be `prod`, constraining both Blob and native task credentials to production mechanisms |

The factory additionally requires platform-injected hosting/project
configuration. Do not set those reserved values yourself. The single-job
restriction bounds extraction progress, not arbitrary request traffic,
metadata overhead, or all possible cloud charges.

From `information-extraction`, validate the local transport and package:

```powershell
& .\.venv\Scripts\python.exe -m pip install -e '.[hosted,test]'
& .\.venv\Scripts\python.exe .\scripts\invocations_smoke.py
& .\.venv\Scripts\python.exe .\scripts\package_source.py `
    --output .\.local-data\synthetic-agent.zip --check
```

The package contains only allowlisted files and excludes the real-model adapter.
The packager rejects source links/junctions, limits each source file to 1 MiB
and the total to 4 MiB, and fixes ZIP entry order, timestamps, and permissions.
`--check` builds a wheel from the staged source and imports its entry point
under isolated Python with network operations blocked. It uses installed
dependencies: this is not proof of remote dependency resolution or a clean
Azure runtime.

The in-process ASGI smoke uses the actual Core 2.1.0 and Invocations 1.1.0 SDKs,
an explicitly local task provider, and synthetic output. It does not bind an
HTTP server or contact Azure. Local replacement-host checks establish
persisted status and explicit resume with different application UUIDs;
managed-host replacement remains a separate cloud observation.

## JSON operation contract

All operations use `POST /invocations`, UTF-8 JSON, with a 16 KiB body limit.
Unknown fields, duplicate keys, invalid JSON, nonfinite numbers, and booleans
in numeric fields are rejected before mutation.

| Action | Required fields in addition to `action` | Success status |
| --- | --- | --- |
| `start` | Configured `job_id`, `request_id`, `expected_revision: 0`, `max_attempts`, `deadline` | 202 |
| `status` | `run_id` | 200 |
| `current` | None; exactly `{"action":"current"}` | 200 |
| `resume` | Previous round's `run_id`, new `request_id`, `expected_revision`, `max_attempts`, `deadline` | 202 |

`max_attempts` is an integer from 1 through 5. `deadline` is an absolute Unix
timestamp; a fresh mutation requires a future value within seven days.
Persist the original request body before sending it. A transport retry must
reuse the same identifier and deadline, not generate a fresh allowance.
Compatible saved mutations retain their original deadlines after expiration.

The current source adds read-only current-job discovery for the
[local workbench](local-workbench.md). The [guarded backend update](guarded-deployment.md)
uploaded it as version 2, with the endpoint still disabled and no live
`current` invocation. The historical version-1 smoke predates this action.
`current` returns:

```json
{
  "synthetic_only": true,
  "app_instance_id": "<application UUID>",
  "job_id": "<configured job>",
  "current": null,
  "pending_request": null
}
```

`current` is either `null` or the existing status projection for the latest
owned round. `pending_request` is either `null` or the exact original winning
start/resume request body. A pending successor can accompany a previous
terminal round until its successor is owned. Queued/running requests may
remain retryable; completed or blocked rounds do not expose a stale retry.
Neither lookup schedules work, reconnects an SDK task, writes a migration, or
renews limits.

Create-only HTTP intent indexes bind the first start per configured job and
the first resume per predecessor before creation/scheduling. They recover
request identity even if an HTTP acknowledgment or initial ownership write
was lost. Competing request IDs/limits conflict rather than receiving
additional budgets. A saved intent that expired before authorization returns
409 `saved_request_expired`; an exact retry never extends it. Existing valid
legacy rounds remain discoverable without rewriting their records.

Start/resume responses contain the frozen `authorization`. Status includes
round/execution states, revision, completed chunks, reserved/committed
attempts, registration acknowledgment, usage uncertainty, and synthetic
candidate evidence. Every dispatched response includes `synthetic_only: true`
and a nonsecret `app_instance_id` generated when that application is
constructed. The latter is a diagnostic, not an authenticated caller or an
Azure resource identifier.

Foreign jobs/rounds and conflicting mutations return 409. Input/media/size
errors return 400/415/413; unknown rounds return 404. Registration uncertainty
returns **503 `batch_registration_unknown`**, with the saved
`error.authorization` for inspection and exact retry, not a success-shaped
response. Storage/internal failures use safe error codes without raw SDK
diagnostics. There is no crash, sleep, arbitrary URL, or caller-identity
override operation.

## Source deployment instead of a container build

Foundry supports Python source ZIP deployment with platform-side dependency
resolution. It does not require local Docker or a customer-owned container
registry. The package must contain only explicitly selected application
files; never upload the repository, virtual environment, Azure configuration,
credentials, local ledgers, or raw experiment logs.

The SDK path used for this feasibility work is pinned to
`azure-ai-projects==2.4.0`. Its `create_version_from_code` method expects a
**named, seekable binary ZIP stream**. Do not copy the tuple-form upload
example from a differently versioned documentation sample.

The deployment definition has this shape:

```python
from pathlib import Path

from azure.ai.projects.models import (
    CodeConfiguration,
    HostedAgentDefinition,
    ProtocolVersionRecord,
)

# project is an authenticated AIProjectClient with allow_preview=True.
# application_settings are the validated, environment-specific Blob settings.
# source_zip is a reviewed, allowlisted archive, not a directory upload.
definition = HostedAgentDefinition(
    cpu="0.5",
    memory="1Gi",
    code_configuration=CodeConfiguration(
        runtime="python_3_13",
        entry_point=["python", "main.py"],
        dependency_resolution="remote_build",
    ),
    protocol_versions=[
        ProtocolVersionRecord(protocol="invocations", version="2.0.0"),
    ],
    environment_variables={
        **application_settings,
        "AGENTSERVER_TASKS_BACKEND": "hosted",
        "AZURE_TOKEN_CREDENTIALS": "prod",
    },
)

with Path(source_zip).open("rb") as code:
    created = project.agents.create_version_from_code(
        agent_name=approved_new_agent_name,
        definition=definition,
        code=code,
        description="Bounded synthetic-only G0 probe",
        metadata=ownership_metadata,
    )
```

This is the explicitly updated declaration accepted for version 2, not a
relabelling of the historical `1.0.0` smoke. Acceptance of the definition
does not verify protocol-2 identity forwarding or native-task behavior;
see the [guarded update evidence](guarded-deployment.md).

**Creation starts provisioning; there is no separate compute-start step.**
Choose the existing project through the client endpoint, not a new region
parameter. Do not combine `code_configuration` with a container image, add
model deployment variables, or invent legacy replica-start arguments.
Application configuration must not redeclare platform-reserved `FOUNDRY_*`
variables.

Sources: [source ZIP deployment](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/deploy-hosted-agent-code)
and the [pinned SDK upload implementation](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-projects_2.4.0/sdk/ai/azure-ai-projects/azure/ai/projects/operations/_patch_agents.py#L256-L334).

## Protect existing agents and uncertain operations

Before uploading, call `project.agents.get(agent_name=...)`. Only a genuine
`ResourceNotFoundError` establishes observed absence; permission or network
failures must stop the operation. If the name already exists, do not create
another version without separate authorization.

A GET is not an atomic name reservation. Attach an experiment ownership
identifier and reviewed archive hash as nonsecret metadata, then verify the
returned version and identity. If the create response is lost, inspect the
agent/version and metadata before deciding whether another POST is safe.
Never repeatedly upload under a new identity merely to make a timeout pass.

Poll `project.agents.get_version(agent_name=..., agent_version=...)` with a
finite deadline. Statuses include `creating`, `active`, and `failed`.
`active` is infrastructure status, not proof of Blob authorization or a
working preview task backend. A failed or timed-out operation must remain
visible and retain enough private state for safe follow-up.

## Agent identity and Blob access

Use the runtime service principal returned in
`created.instance_identity.principal_id`, or the corresponding subsequent
agent read. The identity can be absent while provisioning; wait within the
probe's deadline rather than substituting another principal.

Assign **Storage Blob Data Contributor** only at the dedicated container:

```text
/subscriptions/<subscription>/resourceGroups/<group>/providers/Microsoft.Storage/storageAccounts/<account>/blobServices/default/containers/<container>
```

Do not grant this data role to the identity's client ID, blueprint identity,
or project managed identity by mistake. The deployment operator needs
role-assignment authority at that container or an ancestor. Changes can take
time to propagate; inspect identity and scope rather than falling back to a
storage key.

Microsoft's hosted-agent Blob example uses `DefaultAzureCredential`.
Production application wiring should exclude developer/user credential
branches and preserve supported platform credential mechanisms. The actual
hosted credential path and effective Blob access must still be verified in
the target environment; do not assume a client selector from an undocumented
environment variable.

Production-only credential selection is checked both at construction and at
lifespan entry. It covers the task backend's independent asynchronous
credential as well as Blob's synchronous credential.

Core 2.1.0 does not expose a host-level task-provider ownership hook and does
not fully close its hosted provider/credential on shutdown. A narrowly scoped
`hosted_lifecycle` adapter therefore uses **pinned private SDK contracts**
for hosted mode. It fails explicitly on incompatible SDK versions/contracts,
preserves startup/shutdown dispatch, drains owned tasks before closing native
HTTP and credential resources, then permits outer Blob cleanup. It does not
globally monkeypatch SDK classes or restart an interrupted inference worker.
Changing the SDK pin requires repeating these lifecycle checks.

Sources: [runtime identity and permissions](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agent-permissions#agent-access-beyond-defaults),
[container-scoped Blob roles](https://learn.microsoft.com/en-us/azure/storage/blobs/assign-azure-role-data-access),
and [first-party Blob credential example](https://github.com/microsoft-foundry/foundry-samples/blob/1abe346cbb2428fce504970498bafecf3803f29c/samples/python/hosted-agents/agent-framework/responses/10-downstream-azure/src/agent-framework-agent-downstream-azure-responses/tools/storage.py#L15-L29).

## Gateway access and readiness

Use an Entra token for `https://ai.azure.com/.default` to call:

```text
POST <project-endpoint>/agents/<agent-name>/endpoint/protocols/invocations?api-version=v1
```

The Invocations adapter dispatches the application's validated JSON actions
through this one endpoint. Do not assume that additional custom URL paths
traverse the gateway.

Capture `x-agent-session-id` from the first response. Subsequent calls must
reuse that session through the **`agent_session_id` query parameter**:

```text
POST <project-endpoint>/agents/<agent-name>/endpoint/protocols/invocations?api-version=v1&agent_session_id=<encoded-session-id>
```

Neither a body field nor a request header selects the Invocations sandbox.
If the first response has no session header, stop rather than repeatedly
polling without affinity and potentially allocating new sessions.
After stopping the owned session, omit the selector once to create a new
session, capture its response header, then resume affinity. Reusing the old
selector instead resumes the preserved session.

Source: [Invocations session binding](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/manage-hosted-sessions#how-each-protocol-binds-an-invocation-to-a-session).

Endpoint interaction requires
`Microsoft.CognitiveServices/accounts/AIServices/endpoints/interact/action`.
Foundry Agent Consumer is the narrow built-in interaction role, but inherited
project/account/group grants still apply. Adding a narrow grant for one
operator does not exclude other already-authorized callers.

The gateway strips the incoming authorization header. Caller-controlled
body fields and `x-client-*` headers are not authentication. The SDK's
platform `user_id` is not documented as an Entra object ID, and platform
header guarantees depend on the container protocol contract. This probe
therefore makes no in-handler operator-identity claim.

The SDK readiness route only establishes its configured health response.
Successful startup cannot establish external Blob permissions or successful
resilient-task registration/recovery. The latter requires an actual bounded
start/status/resume probe and, separately, controlled lifecycle evidence.

Sources: [runtime and gateway contract](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agent-contract),
[interaction permissions](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agent-permissions#agent-interaction),
and [agent-scoped role assignments](https://learn.microsoft.com/en-us/azure/foundry/concepts/rbac-foundry#agent-scope-role-assignments).

## Stop procedure and retained resources

After the probe, disable only the newly owned agent:

```python
project.agents.disable(agent_name=approved_new_agent_name)
assert project.agents.get(agent_name=approved_new_agent_name).state == "disabled"
```

List its sessions with `project.agents.list_sessions(agent_name=..., limit=100)`,
stop the probe's sessions with `project.agents.stop_session(agent_name=...,
session_id=...)`, and inspect their resulting state. Preserve experiment
ownership checks before acting.

**Disabled endpoint state does not prove immediate runtime termination,
cancellation of durable tasks, or zero further charges.** Existing sessions
drain. The explicit stop-session operation terminates its running compute
but preserves the session and filesystem; inspect the result rather than
treating a stop request as confirmation. Sessions left running are subject
to the documented fifteen-minute automatic compute idle timeout.
Record endpoint state, session observations, and any remaining uncertainty
separately. Application deadlines remain necessary even during cleanup, and
none of these observations is an exact final billing statement.

Source versions, agent identity/role assignments, and synthetic Blob records
can remain after endpoint disablement. Deletion is a separate approval, not
part of this stop procedure. Never delete the shared project, resource group,
or existing agents. Full resource cleanup remains a G0 gate.

In the recorded probe, stopped sessions remained visible as `idle`; the live
status enum had no `stopped` member. Repeating a stop returned HTTP 409
`session_already_stopped`. Recognize that exact confirmed condition rather
than swallowing arbitrary conflicts or assuming all repeated stops return
204.

Sources: [hosted-agent lifecycle management](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/manage-hosted-agent)
and [stop-session semantics](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/manage-hosted-sessions#stop-a-session).
