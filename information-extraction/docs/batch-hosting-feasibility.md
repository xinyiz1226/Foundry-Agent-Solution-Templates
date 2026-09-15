# G0 batch hosting feasibility

## Decision and evidence boundary

On September 15, 2026, the operator selected **Foundry native resilient tasks
(Preview)** for the next model-free G0 feasibility slice. Keep the intended
Foundry-hosted extraction path; do not introduce an independent Durable
Functions coordinator unless this path fails its compatibility or lifecycle
checks.

The [native batch implementation](native-batch.md) now has model-free local
SDK evidence, not a deployed result. This decision does not authorize new
Azure resources, real model calls, or production use. The
existing live model and Blob probes do not establish resilient-task behavior
in the target Foundry environment.

The public validation surface is **start, inspect, and explicit resume**.
The intended result is a single accepted start that advances a bounded batch
without a browser-driven loop. Domain checkpoints and authorization limits
must survive reentry into the task handler.

## What the native contract documents

Foundry distinguishes ordinary background execution from resilient execution.
Background mode can outlive the client connection; resilient execution
additionally supports reentry after a worker/process failure. An arbitrary
thread, an HTTP timeout increase, or `/invocations` by itself does not provide
the same contract.

The hosted runtime's `/invocations` surface is application-defined JSON
pass-through. Start/status/resume semantics are therefore the application's
responsibility, not operations that the gateway automatically supplies.

Sources:

- [Long-running agent resilience](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/long-running-agent-resilience).
- [Hosted-agent runtime contract](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agent-contract#long-running-and-resilient-execution-preview).

The versioned Python AgentServer Core **2.1.0**
[task guide](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-agentserver-core_2.1.0/sdk/agentserver/azure-ai-agentserver-core/docs/tasks-guide.md)
documents the following constraints:

| Contract | Consequence for this template |
| --- | --- |
| Resilient tasks require explicit opt-in before host startup. | Do not silently run a supposedly durable task on an ordinary local task implementation. |
| Starting a task persists its input before handler execution and returns a handle without waiting for completion. | Persist application authorization before registration; pass durable references rather than full source documents. |
| Recovery restarts the handler from its beginning with saved input. | Read Blob checkpoints and persisted limits on every entry; local variables are not recovered state. |
| Handler output is not persisted and one-shot terminal task records are deleted. | Inspect application-owned durable results, not a task handle or task output. |
| Exception retry defaults off, but crash recovery does not consume that retry budget. | Framework retry settings cannot enforce the batch's model-attempt allowance. |
| Timeout cancellation is cooperative; the guide describes a one-day default and seven-day maximum. | Set a bounded task timeout and independently enforce an absolute application scheduling deadline. Neither proves provider-side cancellation. |
| The guide describes a 30-day sliding task TTL and approximately 10 MiB input limit. | Task registration is not indefinite archival storage; keep task inputs small and review retention separately. |

Use explicit resilience enablement as documented in the guide and the
[Core reference](https://learn.microsoft.com/en-us/python/api/overview/azure/ai-agentserver-core-readme?view=azure-python).
Some guide examples contain inconsistent opt-in comments; do not rely on
those comments to assume enablement.

These sources document a Preview capability without a production SLA. They
do not prove availability, runtime configuration, restart timing, or identity
setup in a particular Foundry project.

### Source-verified SDK integration details

The pinned Core 2.1.0 source exposes `task`, `TaskContext`,
`set_resilient_tasks_enabled`, and `RetryPolicy` from
`azure.ai.agentserver.core.tasks`. A stable named async handler is registered
with `@task(name=..., retry=None)` and started with
`await handler.start(task_id=..., input=...)`. Explicit task IDs and small
JSON-compatible inputs are necessary to retry registration without generating
new application identities. These names were checked against source, and the
implemented adapter was subsequently exercised against the installed 2.1.0
package's local task manager and public `AgentServerHost` lifespan with an
explicit local provider. Managed backend support and deployed startup remain
unverified.

Two non-obvious behaviors directly affect the public interface:

- A completed one-shot task's provider record is deleted. Starting that task
  ID again can create fresh task execution. Task IDs are therefore **not**
  permanent completed-request deduplication; the handler must check the
  application's immutable authorization and committed work.
- `get_active_run()` may reclaim an expired lease and reenter a handler.
  It is **not a read-only status operation**. An absent handle is not evidence
  that inference can safely be retried. Public inspection must use durable
  application state without invoking this method.

Sources: [task exports](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-agentserver-core_2.1.0/sdk/agentserver/azure-ai-agentserver-core/azure/ai/agentserver/core/tasks/__init__.py),
[task decorator/start implementation](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-agentserver-core_2.1.0/sdk/agentserver/azure-ai-agentserver-core/azure/ai/agentserver/core/tasks/_decorator.py),
and [task manager](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-agentserver-core_2.1.0/sdk/agentserver/azure-ai-agentserver-core/azure/ai/agentserver/core/tasks/_manager.py).

The source's non-hosted task provider is JSON-file-backed, not SQLite or an
in-memory durable substitute. `AGENTSERVER_TASKS_BACKEND=local` and
`AGENTSERVER_STATE_ROOT` select its local configuration. Local provider state
is distinct from this template's SQLite or Blob **extraction** ledger.
An explicit local SDK harness can establish task registration and lifecycle
compatibility, but not managed backend recovery.

The pinned task manager can log and return from a failed stale-task listing.
Consequently, a successful host startup alone is not a hosted-resilience
readiness check. The live probe must actually register and recover work in
the selected managed backend. Never silently substitute the local provider
when hosted support is missing.

Sources: [local provider](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-agentserver-core_2.1.0/sdk/agentserver/azure-ai-agentserver-core/azure/ai/agentserver/core/tasks/_local_provider.py)
and [host task-manager initialization](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-agentserver-core_2.1.0/sdk/agentserver/azure-ai-agentserver-core/azure/ai/agentserver/core/_base.py).

## Required application invariants

The existing [execution contract](../README.md) and
[Blob ledger](blob-store.md) remain authoritative for extraction attempts.
The scheduling layer must not replace their immutable claims with leases or
automatically take over an unresolved model attempt.

- Persist the authorization round, frozen execution identity, finite attempt
  allowance, and absolute deadline before scheduling work.
- Repeated start or resume requests retain the same authorization; a transport
  retry or recovered task cannot create a fresh budget.
- Each attempted revision has a stable request identifier. A committed
  request replays its result; an unresolved claim cannot authorize inference.
- Pause after a declared failure or a processing limit. Only an explicit,
  compatible resume opens a new authorized round.
- A recovered older round must not advance work belonging to a newer round.
- Inspect is read-only. Neither browser refresh nor a status request can
  trigger another extraction attempt.
- Preserve known token usage and expose unknown usage. An attempt limit,
  output cap, or scheduling deadline is not an exact billing guarantee.
- Surface failed or ambiguous task registration. Do not report scheduled
  success merely because the application start intent was persisted.

The original attempt may finish remotely after a timeout or interruption.
No reviewed source establishes exactly-once model inference. Blocking an
ambiguous attempt is an intentional safe outcome, not an implementation
failure to hide through automatic retry.

## Feasibility sequence

Start with synthetic model output and the real installed SDK interfaces.
Exercise duplicate starts, handled failure/resume, deadline and attempt-limit
preservation, registration uncertainty, and task-handler reentry. Local
provider or simulated reentry evidence must be labeled as local; it cannot
prove the managed Foundry recovery loop.

Before a live hosted probe, separately confirm the deployment mechanism,
supported SDK/runtime versions, region, operator authorization, managed
identity roles, resource changes, retention, and costs. Then check:

1. Start returns without waiting for the whole batch; disconnect the client
   and observe continued backend progression.
2. Replace the execution process and inspect the same application identity.
   Safely continue only when its prior outcome is known.
3. Lose a registration or commit acknowledgment and retry the same request.
   No additional authorization or repeated committed inference is allowed.
4. Exercise limit/failure pauses and explicit resume from persisted state.
5. Verify designated-operator access and downstream managed identity, then
   record retained resources and separately authorized cleanup.

The [G0 matrix](g0-validation-plan.md) remains the exit gate. Implementing a
task handler or passing local tests does not pass G0-08 through G0-11.

## Fallbacks, not selected deployments

**Durable Functions** provides asynchronous start, persisted orchestration,
and deterministic replay, but activities execute at least once. If adopted
as a coordinator, each activity should invoke one exact guarded extraction
revision, not perform unguarded model work. Redelivery must preserve the
existing committed-replay or unresolved-blocking behavior. Functions can
coordinate a Foundry-hosted extractor; moving extraction into Functions is a
separate architecture decision.

Sources: [instance management](https://learn.microsoft.com/en-us/azure/durable-task/common/durable-task-instance-management),
[activity execution](https://learn.microsoft.com/en-us/azure/durable-task/common/programming-model-overview#activities),
and [managed identity configuration](https://learn.microsoft.com/en-us/azure/durable-task/durable-functions/durable-functions-configure-managed-identity).

**Container Apps Jobs** provides bounded container executions with configurable
timeouts/retries and manual, scheduled, or event triggers. It does not supply
application checkpoint/resume semantics, and jobs have no ingress; another
authenticated entry point would be needed for the workbench.
Source: [Container Apps Jobs](https://learn.microsoft.com/en-us/azure/container-apps/jobs).

The **Agent Framework Durable Extension** is another documented durable
execution path backed by Durable Task infrastructure. It is not evidence
that an ordinary hosted invocation automatically gains durable scheduling,
and it would require an explicit integration and deployment decision.
Source: [Agent Framework Durable Extension](https://learn.microsoft.com/en-us/agent-framework/hosting/azure-functions).
