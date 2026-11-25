# Platform–SEM and Runner–SEM Protocol Contract V1

- Contract version: **1.0**
- Status: **Normative architecture contract for implementation; wire-level schemas are specified here, but no implementation is claimed complete.**
- Owners: Platform API/event producer in luqizheng/ai-pm; SEM API/WSS gateway in luqizheng/smark-sem; Runner Supervisor client in the Runner codebase.
- Authority: Platform owns business execution authority. SEM owns Runner transport and execution-side observations.
- Related baseline: SEM-02E–02J, service-protocol-security-and-persistence.md, CROSS-REPOSITORY-CODE-OWNERSHIP.md.

## 1. Non-negotiable invariants

1. Platform is the sole writer/authority for Project, Task, Run, Lease, Generation, Scheduling Shield, Execution Barrier, HIR/Consultation, business command state and business audit.
2. SEM has its own PostgreSQL database and must not connect to Platform PostgreSQL or read Platform Outbox tables.
3. Platform Outbox → HTTPS → SEM Inbox is at-least-once. SEM must durably commit Inbox acceptance before returning a success response.
4. SEM → Platform HTTPS is the only SEM path for Claim, Lease Renewal, business command ACK, process evidence acceptance and other Platform-authoritative mutations.
5. Runner Supervisor ↔ SEM WSS is the only Runner control channel after cutover.
6. Harness ↔ Platform MCP remains the project/business channel. Harness MCP activity does not renew Lease.
7. WSS Heartbeat, resource telemetry, Harness Agent Activity, command receipt, cleanup intent and Workspace deletion are not process-exit evidence.
8. HTTP success means only that the called API operation reached its documented commit/acceptance point. It never means a process started, stopped or exited unless the response explicitly carries Platform-committed state or an E3 observation result.
9. No shared database, distributed transaction, Redis/Kafka/RabbitMQ authority, or in-memory-only delivery/command state.
10. Every mutating cross-service request is idempotent. Unknown network outcomes are reconciled using the same idempotency key, never by generating a new operation blindly.

## 2. Versioning and common envelopes

### 2.1 Version rules

- HTTP base path: /internal/v1.
- WSS subprotocol: smark.runner.v1.
- Every event/message contains schema_version: 1.
- Backward-compatible additions may add optional fields within major version 1.
- Changing field meaning, authority, ordering, requiredness, or state-transition semantics requires a new major protocol version.
- Unknown major versions are rejected. Unknown fields are ignored only for non-security metadata; unknown fields in authorization, identity, lease, generation, process identity and command-control objects are rejected.
- All timestamps are RFC 3339 UTC. IDs are opaque UUID strings unless explicitly specified otherwise.

### 2.2 Platform Outbox event envelope

Platform POSTs the following envelope to SEM:

    {
      "event_id": "uuid",
      "event_type": "run.dispatch.requested",
      "schema_version": 1,
      "occurred_at": "RFC3339 UTC",
      "aggregate": {
        "type": "task",
        "id": "uuid",
        "project_id": "uuid"
      },
      "correlation_id": "uuid",
      "payload": {}
    }

Rules:
- event_id is the globally unique delivery/idempotency identity.
- SEM persists event_id under a unique constraint before acknowledging receipt.
- Duplicate event_id with identical canonical payload returns the original accepted result.
- Duplicate event_id with different payload is a conflict and is security/audit logged.
- An event is a wake-up/hint, not a Claim grant. SEM must call Platform Claim API to obtain current eligibility and execution authority.
- SEM does not need every intermediate event to recover. It must reconcile through Platform APIs after restart/reconnect.

Initial event types:
- run.dispatch.requested — eligible work may be available; payload carries project_id/task_id as a hint where known.
- run.control.changed — command or control state may need delivery; payload carries command_id/run_id/generation.
- runner.authorization.changed — runner/device/project authorization changed; payload carries runner_id/device_id and authorization revision.
- project.execution.policy.changed — project dispatch policy changed; payload carries project_id and revision.
- execution.successor.authorized — Platform has committed a human-approved E6 successor authorization; payload carries the exact authorization_id, predecessor Run/Generation, successor Task/Run scope and risk-acceptance metadata. This event is not itself a Claim grant.

Event payloads never carry a Lease Token or a WSS Ticket.

### 2.3 Common request headers

Every service-to-service mutating request includes:
- Authorization: Bearer <short-lived service JWT>
- Content-Type: application/json
- Idempotency-Key: stable operation UUID
- X-Correlation-ID: stable correlation UUID
- X-Request-ID: unique HTTP attempt UUID

For a given operation, the body identifier is equal to Idempotency-Key: claim_request_id for Claim, request_id for Lease Renewal, observation_id for process observation, delivery_id for command delivery, and ack_id for command ACK. Event ingestion uses event_id as its idempotency identity. JWT jti is token replay identity. These identities are separate and must never be substituted for one another.

### 2.4 Common response envelope

    {
      "request_id": "uuid",
      "correlation_id": "uuid",
      "result": "accepted | applied | duplicate | rejected",
      "data": {},
      "error": null
    }

Errors use a stable machine code, safe message and retry classification. Never return credentials, Lease Tokens, internal SQL details or process environment secrets.

## 3. Service-to-service authentication

### 3.1 JWT

Use HTTPS/TLS and short-lived asymmetric-signed service JWTs. Each side has a distinct service identity. Required claims:

- iss, sub, aud
- iat, nbf, exp
- jti, kid
- scope

Maximum JWT lifetime: 5 minutes. Validate signature, key id, issuer, exact audience, time bounds, scope and replay policy. Key rotation must support an overlap window. A service token is never mapped to a human principal.

Minimum scopes:
- Platform → SEM: sem.events.write
- SEM → Platform: platform.run.claim, platform.lease.renew, platform.command.delivery, platform.command.ack, platform.process.observe, platform.execution.reconcile

Implementations may split scopes further; they must not broaden a token beyond its service's required operations.

### 3.2 Request integrity and replay

- TLS is mandatory.
- Validate JWT jti replay separately from Idempotency-Key.
- Bind every request to exact audience, method/path scope and authenticated service identity.
- Reject expired, not-yet-valid, wrong-audience, wrong-issuer, unknown-kid and insufficient-scope tokens.
- Do not log Authorization headers or token bodies.
- Clock skew allowance is bounded and documented in deployment configuration.

## 4. Platform HTTPS API contract

The following endpoints are owned and implemented by Platform in ai-pm. SEM calls them; SEM does not implement their business transactions locally.

### 4.1 Runner WSS ticket issuance

POST /api/v1/runner/tickets

Caller: authenticated Runner device credential over TLS (device-authenticated endpoint; not SEM service JWT).

Request:

    {
      "request_id": "uuid",
      "device_id": "uuid",
      "credential_proof": "opaque proof",
      "requested_protocol": "smark.runner.v1"
    }

Response:

    {
      "ticket": "opaque one-time secret",
      "ticket_id": "uuid",
      "expires_at": "RFC3339 UTC",
      "wss_url": "wss://sem.example/runner/v1/connect",
      "protocol": "smark.runner.v1"
    }

Rules:
- Platform validates device registration/status, project binding and credential.
- Ticket lifetime is at most 60 seconds and it is single-use.
- Ticket binds audience=SEM, device_id, runner_id, scopes, jti, kid, iat and exp.
- Ticket is delivered only to the authenticated device and is never logged.
- Existing cpk_ credential acceptance remains limited to its current MCP path; do not broaden ordinary business API authentication to accept it.
- SEM atomically consumes ticket jti and creates connection_id plus monotonically increasing connection_epoch. Reuse is rejected.

### 4.2 Claim

POST /internal/v1/runs/claim

Caller: SEM service identity with platform.run.claim.

Request:

    {
      "claim_request_id": "uuid",
      "runner_id": "uuid",
      "device_id": "uuid",
      "task_id": "uuid or null",
      "dispatch_operation_id": "uuid",
      "runner_capabilities": ["codex", "claude-code"],
      "resource_reservation_id": "uuid"
    }

Response on success:

    {
      "claim_request_id": "uuid",
      "claim_status": "claimed",
      "run": {
        "run_id": "uuid",
        "task_id": "uuid",
        "project_id": "uuid",
        "generation": 1,
        "lease_token": "opaque secret",
        "lease_expires_at": "RFC3339 UTC",
        "deadline_at": "RFC3339 UTC or null",
        "execution_profile": {},
        "workspace_spec": {},
        "harness_spec": {}
      }
    }

Response when no eligible work:

    {
      "claim_request_id": "uuid",
      "claim_status": "no_work"
    }

Rules:
- SEM chooses the target Runner before requesting Claim. runner_capabilities are scheduling hints only; Platform intersects them with the registered device capabilities and chooses/validates eligible work as the final authorization authority.
- Platform atomically checks device identity/status, project binding, Runner qualification, Task/Project gates, Scheduling Shield, Execution Barrier, concurrency policy and all relevant Run/Task state.
- Platform alone increments Generation, signs/returns Lease Token and commits Claim/audit/events.
- Claim result and idempotency record are committed in the same Platform transaction. A retry with the same claim_request_id and same canonical body returns the same grant; same key with a different body is rejected.
- Because the response contains a Lease Token, Platform retains the result encrypted under Platform-controlled encryption for a bounded recovery window. SEM may hold the token only in memory while dispatching/renewing; it must not persist or log it.
- If the Claim outcome is unknown, SEM retains the same dispatch operation and retries/queries with the same claim_request_id. It must not silently select another Runner or create another Claim key.
- A successful Claim binds the Run to the target Runner. WSS delivery failure does not unclaim or silently transfer it. Handoff requires an explicit Platform-authorized path and a new Generation.

### 4.3 Lease renewal

POST /internal/v1/runs/{run_id}/lease/renew

Caller: SEM service identity with platform.lease.renew.

Request:

    {
      "request_id": "uuid",
      "runner_id": "uuid",
      "device_id": "uuid",
      "generation": 1,
      "lease_token": "opaque secret",
      "process_identity": {},
      "supervisor_session_id": "uuid",
      "renewal_requested_at": "RFC3339 UTC"
    }

Response:

    {
      "run_id": "uuid",
      "generation": 1,
      "renewal_status": "renewed | duplicate | rejected",
      "lease_expires_at": "RFC3339 UTC or null",
      "rejection_code": "stable-code or null"
    }

Rules:
- Only Runner Supervisor initiates renewal, and only while supervising the exact active Harness process.
- SEM authenticates the WSS connection and forwards the request. SEM does not decide whether renewal is valid.
- Platform atomically checks Runner/device binding, lease_client_id, Run, Generation, token verifier, process/supervisor identity, renewable Run state, Scheduling Shield, deadline and policy.
- Same request_id + same body returns the previous result; same request_id + different body is rejected.
- Network timeout is unknown outcome; retry the same request_id.
- WSS heartbeat and Harness Agent Activity never renew Lease.
- A stale Generation, owner mismatch, expired Lease, active Scheduling Shield or authorization denial ends renewal attempts for that Generation.

### 4.4 Process observations

POST /internal/v1/runs/{run_id}/process-observations

Caller: SEM service identity with platform.process.observe.

Request:

    {
      "observation_id": "uuid",
      "runner_id": "uuid",
      "device_id": "uuid",
      "generation": 1,
      "observation_type": "process.started | process.exited | process.uncertain | process.reconciled",
      "process_identity": {
        "host_boot_id": "string",
        "pid": 1234,
        "process_start_identity": "OS-specific stable start identity",
        "process_group_or_job_id": "string or null"
      },
      "observed_at": "RFC3339 UTC",
      "exit_code": 0,
      "evidence_class": "E1 | E2 | E3 | E4 | E5",
      "evidence_digest": "sha256 or null",
      "evidence_metadata": {}
    }

Response:

    {
      "observation_id": "uuid",
      "acceptance": "accepted | duplicate | rejected",
      "platform_disposition": "recorded | barrier_required | hir_required | terminal_transitioned | no_state_change"
    }

Rules:
- SEM durably stores local process observations before attempting delivery to Platform.
- Platform validates Run/Generation/Runner binding and decides all business-state, Barrier and HIR effects.
- Old-generation process-exit evidence may be accepted as evidence even when it cannot authorize a current-generation mutation.
- E3 requires OS-level confirmation that the exact process identity exited (wait/handle/process identity verification). Command ACK, timeout, heartbeat loss, PID absence without identity proof, workspace deletion and cleanup completion are not E3.
- E4/E5 must not be translated into automatic requeue. Platform applies the required Barrier/HIR policy.
- Observation IDs are idempotent. Duplicate IDs with different bodies are rejected.

### 4.5 Command delivery and acknowledgement

POST /internal/v1/commands/{command_id}/delivery

Caller: SEM service identity with platform.command.delivery.

Request:

    {
      "delivery_id": "uuid",
      "runner_id": "uuid",
      "run_id": "uuid",
      "generation": 1,
      "delivery_status": "sent | received | failed",
      "observed_at": "RFC3339 UTC",
      "failure_code": "string or null"
    }

This endpoint records transport delivery facts only. It must not mark the business command as acknowledged or completed.

POST /internal/v1/commands/{command_id}/ack

Caller: SEM service identity with platform.command.ack.

Request:

    {
      "ack_id": "uuid",
      "runner_id": "uuid",
      "run_id": "uuid",
      "generation": 1,
      "command_type": "string",
      "command_result": "accepted | completed | failed",
      "process_observation_id": "uuid or null",
      "response_digest": "sha256 or null",
      "observed_at": "RFC3339 UTC"
    }

Rules:
- Platform validates command ownership, command state, Run/Generation, authorization and required evidence, then performs the business ACK transition.
- A terminate command's ACK is not E3 unless it references an accepted E3 process observation.
- Continue/Interaction/Continuation state transitions remain entirely in Platform.
- SEM command_delivery rows are transport ledger only; Platform worker_command remains business authority.

### 4.6 Reconciliation/read APIs

Platform exposes read APIs for SEM to reconcile after restart, reconnect, timeout or missed events. Exact query resources are:
- current dispatch eligibility for a Runner/project scope;
- active Run grant summary for a Runner;
- pending commands for an authorized Run/Generation;
- current device/project authorization revision;
- current execution disposition and outstanding Barrier/HIR constraints.

These reads must return only the caller's authorized scope and must not expose Lease Tokens except through the idempotent Claim recovery operation. Exact pagination/filter query parameters are implementation detail, but consistency and authorization semantics are not.


### 4.7 Human Intervention, Barrier and E6 successor authorization

There is no SEM API that creates, decides, closes or overrides HIR, Execution Barrier, generic Human Consultation or E6 authorization.

- HIR creation/decision and Execution Barrier lifecycle remain Platform-owned.
- A generic Consultation decision is not an E6 authorization and cannot release a Barrier.
- E6 requires a human-authorized, uniquely bound successor authorization record in Platform, with explicit predecessor Run/Generation and one successor scope. The Platform record is the sole authority.
- SEM may receive execution.successor.authorized as an Outbox hint and reconcile the exact authorization through Platform APIs. SEM cannot infer approval from a notification, interaction response, command ACK or stale event.
- E6 accepts residual risk; it does not prove the predecessor process exited and does not release the predecessor Barrier. The successor must use a separate Workspace, new Platform Claim and new Generation. Platform keeps the predecessor marked risk_accepted_unconfirmed.
- Without a valid E6 authorization, E4/E5 must not be automatically reassigned. SEM may not manufacture a successor grant.

## 5. Runner–SEM WSS contract

### 5.1 Connection

- Endpoint: wss://<sem-host>/runner/v1/connect
- Subprotocol: smark.runner.v1
- Authentication: one-time Platform-issued Ticket in the Authorization header, never URL query parameters.
- SEM validates ticket audience, signature, kid, exp, nbf, scope and jti; consumes jti atomically.
- Connection identity comes from the validated ticket, not payload runner_id/device_id.
- SEM assigns connection_id and increasing connection_epoch.
- A reconnect creates a new epoch. Messages from an older epoch cannot mutate current connection state.
- SEM revalidates device/project authorization at least every 30 seconds using Platform API/event freshness. If it cannot establish fresh authorization before the configured deadline, it fails closed for new dispatch/control operations and closes or quarantines the connection according to the active-run safety procedure.

### 5.2 Common WSS envelope

    {
      "message_id": "uuid",
      "message_type": "runner.heartbeat",
      "schema_version": 1,
      "connection_id": "uuid",
      "connection_epoch": 12,
      "sent_at": "RFC3339 UTC",
      "correlation_id": "uuid or null",
      "payload": {}
    }

Server-to-Runner and Runner-to-Server messages use the same envelope. Direction and message_type are validated. A message_id is idempotent within its defined message type and connection/operation scope.

### 5.3 Runner → SEM messages

| message_type | Required payload | Meaning |
|---|---|---|
| runner.heartbeat | supervisor_session_id, monotonic_sequence | Supervisor liveness only; never Lease renewal or process evidence |
| runner.resources.report | sample_id, sampled_at, cpu, memory, workspace_volumes[] | Resource snapshot; never process evidence |
| lease.renew | request_id, run_id, generation, lease_token, supervisor_session_id, process_identity | Dedicated Lease Renewal request |
| runner.process.started | observation_id, run_id, generation, process_identity, started_at | Local process start observation |
| runner.process.exited | observation_id, run_id, generation, process_identity, exited_at, exit_code, evidence_class=E3, evidence_digest | Exact process exit evidence; SEM persists before forwarding |
| runner.process.uncertain | observation_id, run_id, generation, process_identity, observed_at, reason, evidence_class=E4/E5 | Uncertain/lost process; must not auto-requeue |
| runner.command.received | delivery_id, command_id, run_id, generation, received_at | Transport receipt only |
| runner.command.ack | ack_id, command_id, run_id, generation, command_type, command_result, process_observation_id? | Business ACK candidate; SEM forwards to Platform for decision |
| runner.session.sync | supervisor_session_id, active_processes[], last_seen_sequences | Reconnect reconciliation request; no authority to reacquire |

### 5.4 SEM → Runner messages

| message_type | Required payload | Meaning |
|---|---|---|
| dispatch.start | dispatch_operation_id, run_id, task_id, project_id, generation, lease_token, lease_expires_at, deadline_at, execution_profile, workspace_spec, harness_spec | Start grant; sent only after Platform Claim success |
| command.deliver | delivery_id, command_id, run_id, generation, command_type, command_payload, expires_at | Deliver Platform-authorized command |
| lease.renew.result | request_id, run_id, generation, renewal_status, lease_expires_at?, rejection_code? | Relay Platform result |
| dispatch.cancel | dispatch_operation_id, run_id, generation, reason | Stop before spawn or follow Platform-authorized cancellation semantics; does not prove process stopped |
| runner.session.sync.result | sync_id, accepted_active_processes[], rejected_active_processes[], required_actions[] | Reconciliation result; stale-generation processes are never silently adopted |
| runner.authorization.revoked | authorization_revision, effective_at, reason | Stop new dispatch and apply active-run safety policy; not itself process-exit evidence |

### 5.5 Resource report

runner.resources.report payload:
- sample_id: UUID
- sampled_at: RFC3339 UTC
- cpu: total logical cores and current utilization
- memory: total_bytes, available_bytes, used_percent
- workspace_volumes: one item per actual workspace volume, containing stable volume_id, total_bytes, available_bytes, used_percent

Recommended sampling interval: 10–15 seconds. Resource freshness threshold: 45 seconds (tunable by deployment after load testing). Unknown/stale resource data blocks new dispatch to that Runner; it does not terminate current Runs or release reservations. Resource reservations are atomic in SEM and are released only after a known failed Claim or Platform terminal state plus safe process disposition. Unknown Claim outcomes retain reservations until same-key reconciliation.

### 5.6 Ordering, ACK and reconnect

- WSS is an ordered transport per live connection, not an exactly-once business protocol.
- Every command delivery has stable delivery_id and command_id. Retries reuse delivery_id for the same logical delivery.
- Runner persists process evidence locally before sending. Reconnect replays unacknowledged evidence with the same observation_id.
- SEM persists inbound message/evidence before ACKing receipt to Runner.
- SEM persists outbound delivery intent before sending and records transport receipt separately from Platform business ACK.
- Connection epoch fences stale sockets. Run Generation fences stale execution authority. Both are required.
- A reconnect never authorizes automatic process adoption or Lease reacquisition. SEM must query Platform and reconcile exact OS process identities.
- If WSS is lost, active processes may continue only within the last confirmed Lease/safety policy; WSS loss alone is E4/E5 uncertainty, not E3.

## 6. SEM persistence mapping

SEM V1 has seven logical tables:

| Table | Required responsibility |
|---|---|
| inbox_event | Platform event_id dedupe, payload digest, receive/process state, retry schedule |
| runner_connection | Current connection_id/epoch, runner identity, supervision mode, heartbeat, latest resource snapshot |
| runner_ticket_use | Consumed ticket jti, runner, consumed_at, connection binding; unique jti |
| dispatch_operation | Stable dispatch operation/claim_request_id, target Runner, state, resource profile/reservation, unknown-outcome recovery |
| command_delivery | WSS delivery attempts, delivery_id, command_id, connection epoch, transport receipt; not business ACK authority |
| platform_delivery | Stable outbound Platform API operation keys, request digest, retry/unknown outcome and result metadata |
| process_observation | Durable local process identity/evidence spool and delivery state |

No Platform Run/Lease/Generation/HIR mirror table is permitted. Resource snapshots and reservations stay in runner_connection and dispatch_operation.

## 7. Error model

Stable error codes include:
- authentication_failed
- authorization_denied
- invalid_audience
- expired_ticket
- ticket_replayed
- unsupported_protocol_version
- schema_validation_failed
- idempotency_conflict
- stale_connection_epoch
- stale_generation
- lease_owner_mismatch
- lease_expired
- scheduling_shield_active
- execution_barrier_active
- no_eligible_work
- resource_capacity_insufficient
- resource_snapshot_stale
- platform_outcome_unknown
- process_identity_mismatch
- evidence_insufficient

Errors must classify retry behavior:
- permanent: authentication/authorization, invalid schema, stale generation, owner mismatch, ticket replay;
- same-key retry/reconcile: timeout, connection reset, 5xx with unknown commit outcome;
- backoff/re-evaluate: no eligible work, resource insufficient/stale, active Barrier/Shield;
- safety escalation: process identity mismatch, insufficient E3 evidence, E4/E5 uncertainty.

## 8. Security and observability

- Never log Lease Token, WSS Ticket, service JWT, device private key, credential proof or sensitive Harness environment values.
- Redact secret-bearing JSON fields before structured logging and tracing.
- Store only digests/references for sensitive evidence where practical.
- Every cross-service operation carries correlation_id and durable idempotency identity.
- Audit authorization failures, ticket replay, generation mismatch, evidence rejection and E6/successor operations.
- Health endpoints disclose readiness, not credentials, database URLs or internal topology.

## 9. Compatibility and acceptance tests

Both repositories must run shared contract fixtures. Required tests:
1. JWT wrong issuer/audience/scope/expiry/kid and replay rejection.
2. Runner ticket single-use, expiry, wrong audience and concurrent replay.
3. Duplicate Outbox event same body is idempotent; same event_id different body conflicts.
4. Claim request timeout after Platform commit; same claim_request_id returns same Run/Generation/grant.
5. Claim success followed by WSS failure remains bound to original Runner; no silent Runner switch.
6. Lease renewal timeout retries same request_id; Heartbeat and Agent Activity do not renew.
7. Old-generation process exit observation is recorded but cannot mutate current generation incorrectly.
8. Terminate command ACK without E3 cannot close process uncertainty.
9. Duplicate/reordered command delivery and reconnect preserve delivery_id/command_id semantics.
10. Old connection_epoch cannot mutate new connection state.
11. Resource snapshot staleness blocks new dispatch but does not kill active work or release reservations.
12. E4/E5 creates/retains Barrier/HIR policy and never automatically requeues.
13. WSS loss, Runner reboot and process identity mismatch exercise E1–E6 recovery.
14. SEM database inspection proves no Platform authority tables or Platform credentials.
15. Negative tests prove Runner MCP Claim/reacquire/command poll/ACK paths are unavailable after cutover.

## 10. Implementation ownership

- Platform API endpoints, event producers and Platform transaction changes: luqizheng/ai-pm.
- SEM HTTPS API, Inbox, WSS gateway, session/dispatch/process modules and SEM database: luqizheng/smark-sem.
- Runner ticket acquisition, WSS client, process supervisor and evidence spool: Runner client code (currently located in ai-pm until a deliberate extraction decision).
- Shared fixtures can live under smark-sem/docs/protocol/fixtures and be consumed by Platform CI; no third protocol repository is required for V1.

This contract is the cross-repository implementation baseline. It does not close SEM-02J's Platform transaction audit, approve a lock order, or authorize Phase 0. Platform must complete those prerequisites before implementing state-mutating endpoints.
