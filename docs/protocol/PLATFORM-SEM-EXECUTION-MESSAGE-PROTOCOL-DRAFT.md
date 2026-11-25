# Platform–SEM–Runner Execution Message Protocol Draft

- Version: Draft 0.1
- Status: Architecture review only; not normative and not implementation-authorizing.
- Replaces: the superseded Platform–SEM–Runner Protocol V1.
- Authority baseline: [SEM Authority Boundary and Execution Message Model](../architecture/SEM-AUTHORITY-BOUNDARY-AND-EXECUTION-MESSAGE-MODEL.md).

## 1. Contract invariants

1. AI-PM owns all business semantics and business state. SEM is an execution-message transport and infrastructure coordination service.
2. SEM treats the prompt body as opaque. It never parses prompt instructions to infer Task identity, business intent, status, approval, retry eligibility or completion.
3. Harness obtains Task context and performs business operations directly through independently authenticated AI-PM MCP.
4. Runner Supervisor owns local Harness process launch/attach/stop, OS process identity and exact process-exit observation. SEM transports commands and stores/reports Runner observations; it does not own the remote OS process.
5. AI-PM decides business completion/cancellation and sends SEM an explicit release/stop instruction.
6. Task lifecycle and SEM Execution lifecycle are independent.
7. No shared database, distributed transaction, SEM access to Platform PostgreSQL, or business-state mirror.
8. Every message is authenticated, versioned, idempotent and correlated. Stale release messages must not stop a newer execution.

## 2. Identifiers

| Identifier | Owner | Purpose |
|---|---|---|
| message_id | Sender | Unique message identity / deduplication |
| request_id | AI-PM | Idempotency identity for one execution request |
| execution_id | AI-PM | Opaque identity for one requested execution attempt; not a Task ID |
| execution_epoch | SEM | Fencing token for the current Runner binding |
| delivery_id | SEM | One durable SEM→Runner delivery operation |
| runner_id | SEM / registered identity | Infrastructure endpoint identity |
| correlation_id | AI-PM | Trace correlation only; never authorization |
| process_identity | Runner | Exact local OS process identity, including boot/start identity |

A new business execution attempt should receive a new execution_id from AI-PM. SEM may retry delivery of the same execution_id idempotently. SEM increments execution_epoch when it establishes or replaces a valid Runner binding. SEM reports the current binding through an execution.binding_established infrastructure event. AI-PM stores that opaque epoch with its execution mapping and includes it in a release request. An old epoch cannot stop a newer binding. If AI-PM has not received the latest binding event, it must query/reconcile the execution by execution_id before issuing a fenced release.

## 3. Platform → SEM: execution request

Suggested endpoint: POST /internal/sem/v1/executions

~~~json
{
  "message_id": "uuid",
  "message_type": "execution.requested",
  "schema_version": 1,
  "occurred_at": "RFC3339 UTC",
  "request_id": "uuid",
  "correlation_id": "uuid",
  "payload": {
    "execution_id": "uuid",
    "prompt": {
      "content_type": "text/plain; charset=utf-8",
      "body": "请获取任务 A，并且执行。"
    },
    "harness_profile": "codex",
    "runner_requirements": {
      "capabilities": ["codex"],
      "supervision_mode": "unattended"
    }
  }
}
~~~

Rules:
- No Task ID, Task status, acceptance criteria, requirements body, business Run state or business authorization decision is required by SEM.
- Business context is obtained by Harness through AI-PM MCP according to the instructions in the prompt.
- runner_requirements contains infrastructure capability constraints only. It does not express business priority or Task eligibility.
- The prompt body is opaque to SEM. SEM may validate content type/size and encrypt/persist it, but must not interpret it.
- The request must not contain a reusable Platform service credential or a human credential in plaintext.
- If the body is too large, a short-lived authenticated content reference may replace the inline body. Its retrieval and expiry policy remain open contract items.

## 4. SEM → Platform: acceptance response

~~~json
{
  "message_id": "uuid",
  "request_id": "uuid",
  "execution_id": "uuid",
  "acceptance": "accepted",
  "sem_execution_epoch": 1,
  "accepted_at": "RFC3339 UTC"
}
~~~

Possible acceptance values: accepted, duplicate, rejected.

Acceptance means only that SEM durably accepted the infrastructure execution request. It does not mean a Runner was selected, the prompt was delivered, Harness started, or business work began. The current execution_epoch is assigned only when a Runner binding is established and is reported separately.

Duplicate request_id with the same canonical payload returns the original acceptance result. The same request ID with a different payload is a conflict.

## 5. SEM → Runner: opaque prompt delivery

~~~json
{
  "message_id": "uuid",
  "message_type": "execution.deliver",
  "schema_version": 1,
  "execution_id": "uuid",
  "execution_epoch": 1,
  "delivery_id": "uuid",
  "harness_profile": "codex",
  "prompt": {
    "content_type": "text/plain; charset=utf-8",
    "body": "请获取任务 A，并且执行。"
  }
}
~~~

Runner behavior:
1. Validate the SEM connection and message identity.
2. Deduplicate delivery_id/execution_id/epoch so duplicate WSS delivery cannot launch a second Harness for the same attempt.
3. Check whether the configured Harness is installed and available; start/attach according to Runner policy.
4. Inject the prompt into the Harness.
5. Report transport receipt and Harness launch outcome separately.
6. Harness uses AI-PM MCP directly for Task context and business operations.

Runner must not fetch Task context from SEM or ask SEM to mutate Task state.

## 6. Runner → SEM: infrastructure observations

Use distinct message types for distinct facts:
- execution.binding_established: SEM has bound the execution to a specific Runner and assigned the current execution_epoch.
- execution.delivery_received: Runner durably accepted the delivery message.
- harness.starting: launch is in progress.
- harness.started: exact Harness process identity has been established.
- harness.start_failed: launch failed before a process was established.
- harness.process_exited: exact local process identity exited, with exit code and OS evidence metadata.
- runner.resources.report: CPU, memory and workspace-volume telemetry.
- execution.release_applied: Runner processed the release instruction and reports cleanup/process facts.

Heartbeat, resource telemetry, agent activity, timeout, workspace deletion and a command receipt are not process-exit evidence.

## 7. AI-PM → SEM: release/stop instruction

Suggested endpoint: POST /internal/sem/v1/executions/{execution_id}/release

~~~json
{
  "message_id": "uuid",
  "message_type": "execution.release_requested",
  "schema_version": 1,
  "request_id": "uuid",
  "correlation_id": "uuid",
  "payload": {
    "execution_id": "uuid",
    "expected_execution_epoch": 1,
    "stop_policy": {
      "mode": "graceful_then_force",
      "grace_period_seconds": 30
    }
  }
}
~~~

Rules:
- AI-PM sends this only after its own business decision (Task completed, cancelled, or otherwise no longer requiring this execution).
- SEM validates the exact execution_id and expected_execution_epoch, deduplicates request_id, and forwards the stop request to the bound Runner.
- Runner Supervisor owns the actual local graceful/forced process termination.
- Repeated release requests are idempotent.
- A stale epoch is rejected and must never terminate a newer execution.
- Release is not a Task transition and must not update business state.

## 8. SEM → AI-PM: infrastructure result

Distinct infrastructure event types:
- execution.delivery_status
- harness.process_observed
- execution.release_status
- execution.infrastructure_uncertain

~~~json
{
  "message_id": "uuid",
  "message_type": "execution.release_status",
  "schema_version": 1,
  "occurred_at": "RFC3339 UTC",
  "correlation_id": "uuid",
  "payload": {
    "execution_id": "uuid",
    "execution_epoch": 1,
    "release_status": "released",
    "process_exit_observation_id": "uuid",
    "runner_id": "uuid"
  }
}
~~~

Infrastructure status values should describe facts such as accepted, delivering, running, releasing, released, failed and uncertain. Do not reuse AI-PM Task statuses such as completed, blocked or in_progress.

AI-PM may use infrastructure facts as inputs to its own business policy, but SEM cannot choose the business consequence.

## 9. Harness MCP authentication

Installing AI-PM MCP is necessary but not sufficient. Before implementation, define:
- How the Runner/Harness receives a project-scoped MCP identity.
- Whether the identity represents a human principal, service principal or delegated execution principal.
- How AI-PM binds the identity to the intended project and permissions.
- Token lifetime, renewal, revocation and audit behavior.
- How MCP credentials are injected without exposing them to SEM logs or unrelated Harness processes.
- Negative tests proving cross-project and unauthorized Task mutations are denied.

SEM service JWTs and Runner WSS credentials must never be reused as Harness MCP business identities.



## 9.1 AI-PM MCP business transition requirements

Harness business status changes must use AI-PM-owned, guarded MCP operations. Do not add an unrestricted arbitrary Task status setter. AI-PM validates every requested transition against its Task state machine and records the business audit.

The existing ai-pm source baseline has specialized transitions coupled to the old Runner Claim/Lease path: pm_report_progress currently combines business progress/stage with Lease renewal and advances Task to running on the first started stage; pm_submit_result advances Task to submitted; pm_get_run_context returns the fuller execution contract but requires the old claim token; pm_get_task_context is currently a narrower snapshot. The replacement Harness MCP contract must expose complete authorized Task/execution context without requiring Runner Claim, preserve typed business progress/result transitions, and separate all process heartbeat/resource liveness from MCP business operations.

## 9.2 Delegated Harness identity and two fencing domains

The current ai-pm MCP identity implementation is human-key based: a user API Key resolves to a human principal; the current cpk_ device credential resolves to the device owner's human principal; the MCP caller context requires HumanActor; service JWTs are rejected from business endpoints. The existing identity governance decision explicitly says V1 does not issue independent Agent credentials. This cannot, without redesign, prove that one Harness process is authorized for exactly one Task/Run attempt.

The replacement must define a Delegated Execution Identity / grant. This is a proposed concept, not a frozen schema. It must be issued/authorized by AI-PM, scoped to one tenant/project/task/attempt and an allow-list of MCP business operations, short-lived and revocable. It must not impersonate the initiating human and must not authorize approval, formal acceptance, project administration, unrelated Task access or arbitrary Task status mutation. Audit must preserve the delegating human/Platform actor separately from the Harness executor and Runner/device identity.

Do not put a reusable human API Key in the prompt or reuse SEM service JWT / Runner WSS credentials as MCP credentials. Prefer a one-time Runner-bound bootstrap exchange with AI-PM; if a bootstrap ticket traverses SEM, cryptographically bind it to the intended Runner so SEM and other Runners cannot redeem it. A local Runner credential broker may inject the short-lived MCP token into Harness requests. The exact exchange, token format, key binding and revocation design remain open.

Two independent fencing domains are mandatory:
- AI-PM authorization_generation fences every delegated Harness MCP operation for the business attempt.
- SEM execution_epoch/binding_epoch fences delivery/release operations for the current Runner binding.

Neither value substitutes for the other. A new business retry invalidates the prior AI-PM grant. A Runner rebind must fence the old Harness business grant before another Harness can mutate the Task. Revoking MCP access alone does not prove an old process cannot mutate Git remotes or external systems.

If a Runner disconnects and process exit cannot be positively established, keep the execution infrastructure_uncertain, quarantine the old binding and do not launch a competing Harness for the same attempt. Reassignment requires positive process-exit evidence or a separately designed isolation/fencing procedure.

## 9.3 Business submission is not Task completion

The current AI-PM Task lifecycle distinguishes Running→Submitted (delivery manifest required), Submitted→Reviewing, and Reviewing→Completed (acceptance evidence required). The special Ready→Completed path is for manual tasks and requires a human principal and reason. Harness may submit delivery and report progress through typed MCP operations; it must not self-accept or use a generic arbitrary status setter. AI-PM decides final completion under its existing guarded review/acceptance rules.

When an AI-PM business decision makes the execution no longer necessary, the business transition and Platform Outbox release intent should be committed atomically. SEM release remains an infrastructure lifecycle, independent of Task completion.

## 10. Failure and recovery semantics

- SEM accepts request but cannot find a Runner: remain queued/rejected according to infrastructure policy; no business state is changed.
- Runner accepts delivery but Harness fails to start: report infrastructure failure; AI-PM decides the business consequence.
- Harness exits before Task completion: report exact process exit; AI-PM decides whether the Task is retryable or requires intervention.
- Task completes before Harness exits: AI-PM sends release; Task remains completed even if cleanup is still pending.
- Runner disconnects: mark infrastructure uncertain; do not infer process death from heartbeat loss.
- SEM restarts: recover durable inbox/delivery/release records and reconcile Runner binding. Never reconstruct Task state from SEM persistence.
- Unknown message outcome: retry with the same message/request/delivery identity; do not generate a new execution attempt blindly.

## 11. Open review questions

1. Inline prompt body vs short-lived content reference: size limits, confidentiality, retention and replay.
2. Runner authorization: which AI-PM-issued scope/allow-list proves a Runner may receive a given execution request without exposing Task semantics to SEM?
3. Harness MCP principal and credential provisioning model.
4. Runner selection policy when multiple Runners satisfy infrastructure constraints.
5. Execution epoch allocation and persistence across SEM restart/reconnect.
6. Graceful stop deadline, forced termination policy and handling of a Runner that never reconnects.
7. Whether infrastructure reporting is pushed to an AI-PM endpoint, returned synchronously, or both.
8. Retention policy for prompt bodies, process observations and infrastructure logs.

No implementation or migration is authorized until these questions are reviewed and the bilateral contract is approved.
