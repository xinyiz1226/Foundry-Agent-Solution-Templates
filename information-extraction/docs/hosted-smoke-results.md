# Hosted synthetic smoke results

## Outcome and scope

On September 15, 2026, an explicitly approved synthetic-only probe completed
through **real Foundry hosting, its Invocations gateway, native resilient
tasks, and Azure Blob persistence**.

The first round stopped at its one-attempt allowance. After its hosted
session was stopped, a new session returned a different application instance
UUID and restored the same committed result without advancing it. Explicit
resume completed the remaining chunk. Replaying the saved start and resume
requests preserved the final state and candidates.

**No real model calls were made.** The source package contains only the fixed
synthetic extraction path. This is not extraction-quality evidence,
single-operator workbench authentication, an unexpected-crash recovery test,
or a complete G0 pass.

## Artifact and deployment

| Item | Observed configuration |
| --- | --- |
| Application source commit | `c852762` |
| Source ZIP | 14 allowlisted files, 95,047 bytes |
| ZIP SHA-256 | `7d72ffcfdb96e49e86fb1cfdab7ef2cd41170223d100847fbdd056a9e99ea483` |
| Deployment client | `azure-ai-projects` 2.4.0, named binary ZIP stream |
| Runtime | `python_3_13`, platform `remote_build`, `python main.py` |
| SDK pins | Core 2.1.0; Invocations 1.1.0 |
| Hosted resources | 0.5 CPU, 1 GiB memory; new agent version 1 |
| Protocol | Invocations 1.0.0 through the project gateway |
| Application data | One configured synthetic job in a fresh Blob namespace |

The source archive passed an isolated wheel-build/entrypoint-import check
before upload. The operator-approved existing project and Blob container
were reused. No ACR was created, no existing agent was changed, and no model
deployment was added.

The returned runtime identity received Storage Blob Data Contributor at the
dedicated container scope. Production credential policy excluded developer
branches for both Blob and the native task backend. Subsequent hosted
registration and application operations succeeded. This establishes the
configured access path for the probe, not a full effective-permissions audit.

Version status progressed from `creating` to `active`; actual gateway
operations then established application readiness beyond that control-plane
status. The [deployment guide](hosted-deployment.md) records the SDK,
credential, lifecycle, and routing contracts.

## Observed sequence

| Operation | Result |
| --- | --- |
| Authenticated start, maximum one attempt | HTTP 202 with frozen round authorization |
| Same-session status | HTTP 200, `limited`, execution `ready`, revision 1, one committed attempt |
| Unauthenticated read-only gateway request | HTTP 401 |
| Stop existing probe sessions | Stop operation acknowledged; preserved session records reported `idle` |
| New-session status, before resume | Different `app_instance_id`; same limited round, revision 1, and first candidate |
| Explicit resume at revision 1 | HTTP 202 with a new bounded round authorization |
| Same-session status | `completed`, revision 2, two completed chunks and two committed synthetic attempts |
| Replay original start and resume, then inspect | Final authorization, states, revision, counts, usage, and candidates unchanged |
| Disable agent and stop its sessions | Agent state `disabled`; all four listed sessions had stop acknowledgment and reported `idle` |

Subsequent calls reused `x-agent-session-id` through the `agent_session_id`
query parameter. The replacement-session request omitted that selector once,
then reused its new response identifier. It did not rely on a request header
or body field to choose the sandbox.

The first candidate remained exactly unchanged:

| Metric | Value | Unit | Evidence location | Review |
| --- | --- | --- | --- | --- |
| Revenue | 120 | `USD_millions` | `synthetic:line:1` | Pending |
| Operating income | 18 | `USD_millions` | `synthetic:line:3` | Pending |

Both records retained their original synthetic text evidence and
`semantic_validation_performed=False`. The synthetic implementation's zero
token counts are not measurements of a real provider.

## Stop observations and retained state

The interval from starting creation to the final stop observation was
approximately **451 seconds**. This is wall-clock experiment duration,
not a billable-compute measurement.

The live session API uses `idle` for preserved stopped records; its status
enum does not contain `stopped`. A repeated stop returned HTTP 409 with
`session_already_stopped`. Only that exact response was treated as
confirmation of an already-stopped session; unrelated conflicts were not
ignored. This differs from assuming every repeated stop returns 204.

The new agent remains registered with version status `active`, while its
endpoint state is **disabled**. Those are different lifecycle dimensions.
The four session records, agent identity/role assignment, source version,
existing storage, and synthetic ledger are intentionally retained.
Deletion was not authorized or performed.

Stop/disable observations do not establish an exact final Azure bill.
No continuing application batch was observed; the ledger is complete and
the owned sessions were stopped. The shared resource group and other agents
were not removed or reconfigured.

## What remains unproven

- Unexpected process loss during an unresolved attempt, native lease takeover,
  and provider-outcome reconciliation were not injected into this live run.
- A new application UUID establishes a replacement application instance, not
  a different physical machine or automatic recovery from an unknown crash.
- The live sequence deliberately used one attempt followed by explicit
  resume; it does not prove two successful chunks from a single uninterrupted
  cloud start. That progression has offline contract evidence.
- The gateway used the shared project's effective invoke permissions.
  Designated-operator web authorization and unauthorized signed-in-user
  rejection were not established.
- No browser/Streamlit flow, real-model-plus-hosted-Blob integration, scale,
  billed-cost cap, full Bicep/azd environment, or full resource deletion was
  validated.

Environment-specific endpoints, principal IDs, role-assignment IDs, session
identifiers, request bodies, and raw operational logs remain outside the
public contribution.

## Post-probe robustness change

A later lifecycle guard prevents an old task manager's delayed cleanup from
clearing a replacement manager's SDK singleton. Constructor-failure coverage
also verifies that owned provider and credential resources close before
lifespan entry fails.

That change passed the offline suite and isolated package check but **was
not redeployed**. Its rebuilt archive is 95,482 bytes, SHA-256
`6eb07d260c94e39bc0383d5cebad7c456b14e0ddaca208fe51e591541b43e87a`.
The live evidence above remains bound to `c852762` and the original `7d72...`
archive. The probe endpoint was not re-enabled for this follow-up.
