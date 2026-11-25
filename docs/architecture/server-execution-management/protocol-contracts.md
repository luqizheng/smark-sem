# SEM V1 Protocol Contracts

Status: normative design target. Exact route/function names must be reconciled with code before implementation.

## 1. Trust boundaries

- Platform and SEM are independent services and own separate databases.
- Platform PostgreSQL is authoritative for Project/Task/Run/Lease/Generation, business status, authorization and audit. SEM must not connect to or issue SQL against Platform PostgreSQL.
- SEM owns only execution-side private persistence: durable command-delivery records, connection/session metadata and local execution coordination. These records must not become a second Run/Lease authority.
- Platform ↔ SEM communication uses versioned HTTPS service APIs. Platform Transactional Outbox reliably triggers dispatch; SEM processes requests idempotently and reconciles through Platform APIs.
- Runner ↔ SEM communication uses authenticated WSS. Runner supervises its local Harness process through OS process APIs.
- No shared database and no message broker in V1.

## 2. Platform–SEM service API

### 2.1 Direction and responsibilities

- Platform → SEM: dispatch notification, cancellation request, policy/configuration changes, and authorized control requests.
- SEM → Platform: target-Runner claim request, lease renewal, execution lifecycle updates, result/error reports, termination evidence and Runner/connection telemetry.
- SEM is the sole Runner dispatch/handoff coordinator. Runner does not poll Platform MCP for Claim, command delivery, ACK or recovery control.
- Platform remains the only authority that grants a Run lease or changes authoritative Run/Generation state. SEM cannot self-assign a Run; it requests a claim for a specifically authenticated target Runner.

### 2.2 Dispatch and recovery

1. Platform commits the business change and an Outbox event in the same database transaction.
2. Outbox delivery calls the versioned SEM HTTPS API. Delivery is at-least-once; each event has a stable event_id/idempotency key.
3. SEM durably records receipt before acknowledging acceptance; duplicate event delivery returns the prior outcome.
4. SEM selects an eligible Runner (or obtains explicit user selection for `supervised`) and requests Claim through Platform API with the authenticated target Runner/device identity. Platform independently validates device registration, tenant/project binding, authorization, supervision policy, Scheduling Shield and concurrency, then performs generation increment, lease issuance and audit in one authoritative transaction.
5. SEM sends the execution command and Platform-issued lease material to that exact Runner over its authenticated WSS connection only after successful Claim. Runner never calls Claim directly.
6. SEM reports state and evidence through Platform APIs. On timeout/restart, SEM retries idempotently and periodically reconciles outstanding operations with Platform.
7. Outbox notification is a wake-up/trigger, not the task payload authority. API query/reconciliation is the recovery path for missed or delayed notifications.

### 2.3 API contract requirements

- Version prefix (for example `/internal/sem/v1/`); exact routes, DTOs, status codes and error envelopes must be frozen in SEM-02D before Phase 1 implementation.
- Service-to-service authentication, TLS, least-privilege scopes, request correlation ID, idempotency key, timeout and bounded retry policy.
- Mutating calls carry Run ID and expected generation where applicable; stale generation and mismatched ownership fail closed.
- No distributed transaction across Platform and SEM databases. Use outbox/inbox, idempotency, explicit operation state and reconciliation/compensation.
- API acceptance is not proof of process start or process termination; process evidence has separate semantics.

## 3. Common execution envelope

Every execution-control message must be scoped to tenant/project/task as applicable, task_run_id, lease_generation, client/Runner identity, command/event ID, timestamp and idempotency key.

Stale generation, mismatched client identity or missing required scope is rejected. Duplicate delivery is idempotent.

## 4. Claim

A successful claim is requested by SEM through the Platform HTTPS API and executed atomically inside Platform:
1. verifies tenant/project/device authorization and candidate eligibility;
2. excludes Runs under Scheduling Shield;
3. serializes ownership using the existing claim transaction pattern;
4. increments generation;
5. issues a fresh lease token and stores only its verifier/hash;
6. binds the lease to the exact client identity;
7. records an audit event.

User selection of a Runner is not a claim and grants no execution ownership. The Runner may start only after a successful claim response.

## 5. Runner liveness, Lease Renewal and Agent Activity

These are three distinct signals and must never be conflated:

1. **Runner Supervisor Heartbeat**: Runner sends over WSS to SEM. It proves only that the Runner supervisor loop is alive and maintains connection liveness. It does not itself prove Harness activity or human presence, and does not automatically renew a Lease.
2. **Lease Renewal（ADR-SEM-21 唯一正式路径）**: Runner Supervisor 通过专用 WSS `lease.renew` 消息发起，SEM 转发到 Platform HTTPS API。Platform 独立校验并提交续租。该路径已由用户确认并由 ADR-SEM-21 冻结。
3. **Agent Activity**: Harness/Agent reports progress through Platform MCP business tools。它只记录业务/执行活动，不续租。

Renewal constraints:
- renew only for exact current owner, token proof and generation;
- never clear Scheduling Shield;
- stale heartbeat/renewal cannot resurrect an old generation;
- WSS liveness alone never renews a Lease;
- only the dedicated Runner Supervisor WSS renewal request forwarded by SEM may renew; WSS liveness and Agent Activity never renew.

## 6. Cancellation and E3

Carry cancellation commands and ACKs over the authenticated Runner↔SEM WSS channel. Runner does not poll Platform MCP for commands or ACKs. Platform retains `worker_command` business state; SEM stores only transport delivery facts. Do not use Platform database polling or add a separate MCP tool solely for cancellation.

A cancel command carries command ID, Run ID, generation and target process identity.
- Command receipt acknowledgement is separate from termination confirmation.
- E3 is sent only after the Runner supervisor observes OS-level process exit through wait/handle result.
- E3 binds command ID, Run ID, generation, process identity, exit observation and timestamp.
- Duplicate E3 is idempotent.
- Mismatched generation/process identity is rejected.
- Timeout, offline Runner, malformed ACK or missing exit observation is not E3; keep E4/E5 shield.

HTTP 2xx, successful polling, command receipt or request acceptance is never proof of process termination.

## 7. Result and error contract

Results are accepted by Platform only after checking current lease verifier, generation and client identity. SEM forwards evidence through the authenticated service API; it does not write Run state directly. Runner never writes Platform PostgreSQL or calls Platform database endpoints directly. Stale results may be retained as diagnostic evidence but cannot mutate authoritative task state. Secrets are redacted before persistence.

Distinct error categories include stale_generation, lease_owner_mismatch, lease_expired, scheduling_shield_active, run_not_claimable, process_identity_mismatch, termination_not_observed and authorization_denied. Map them to existing API conventions rather than inventing a parallel error system.

## 8. Versioning

Persist protocol version in command/event payloads. Unknown mandatory versions fail closed for destructive actions. Exact wire fields and status codes are implementation tasks requiring code-level reconciliation.


## 9. Runner control-channel ownership (ADR-SEM-20)

| Operation | Sole path | Authority |
|---|---|---|
| Runner selection / supervised user confirmation | SEM scheduler + SEM user-notification flow | User intent and SEM coordination; no execution right |
| Claim | SEM HTTPS → Platform Claim API, then WSS dispatch | Platform transaction grants Lease/Generation |
| Runner Supervisor Heartbeat | Runner → SEM WSS | SEM connection/liveness record only |
| Lease Renewal | Runner Supervisor → SEM WSS → SEM HTTPS → Platform | Platform validates and commits renewal; this is the ratified single path under ADR-SEM-21 |
| Command delivery / command ACK / cancel / E3 | Platform command intent → SEM WSS → Runner; ACK returns WSS → SEM → Platform API | Platform command business state; SEM transport ledger; Runner OS process observation for E3 |
| Run/Task context, Agent Activity, Interaction, delivery/result | Harness → Platform MCP | Platform business application services |
| Recovery / handoff coordination | SEM scheduler + Platform API Claim/recovery operations + WSS | Platform owns lease/generation; HIR and business audit remain Platform |

After migration, remove Runner MCP polling/write paths for Claim, Lease Renewal, command polling/ACK and recovery. Do not retain duplicate control paths. Keep MCP tools needed by Harness for business operations.


## 10. Service authentication, WSS ticket and SEM persistence baseline

The ratified detailed baseline under ADR-SEM-21–25 is maintained in `service-protocol-security-and-persistence.md`:

- Platform↔SEM: independent service identities, TLS, short-lived asymmetric-signed JWT, exact audience/scope/key ID, key rotation and idempotent request IDs. Service tokens never enter human-principal resolution.
- Runner↔SEM: Runner first obtains a short-lived, single-use SEM-audience connect ticket from Platform using its registered device credential; SEM validates signature and consumes ticket `jti`. WSS authorization is continuously refreshed by revocation Outbox events and bounded Platform API revalidation.
- SEM persistence: `inbox_event`, `runner_connection`, `runner_ticket_use`, `dispatch_operation`, `command_delivery`, `platform_delivery`, `process_observation`. These are SEM transport/execution facts, not business state.
- Claim crash recovery: persist dispatch intent before Claim; use stable `claim_request_id`; Platform atomically persists the idempotency outcome; SEM retries the same request and never blindly creates a second Claim.

These are ratified target design constraints, not current implementation facts.

## 11. Idempotency and recovery contract (ADR-SEM-25)

- SEM persists a dispatch operation before requesting Claim and reuses the same `claim_request_id` for every retry.
- Platform commits the Claim business mutation and its idempotency outcome in one transaction. Repeated identical requests return the same result; conflicting reuse is rejected.
- A lost Claim response must never cause a second Claim or a new target Runner assignment. Recovery is bound to the original target Runner and current Platform lease validity.
- SEM may hold the opaque Lease Token only in bounded process memory for dispatch/renewal relay; it must never persist it in DB, delivery ledger, logs, traces or error payloads.
- Inbox acceptance is acknowledged only after the SEM Inbox transaction commits; duplicate event IDs are acknowledged idempotently.


## 12. Resource-aware Runner reporting (ADR-SEM-26 — approved)

Runner Supervisor may send `runner.resource.report` over the authenticated WSS control channel. The report contains `boot_id`, monotonic `sample_seq`, `observed_at`, CPU logical count and normalized utilization windows, memory total/available/pressure, and free/total bytes for the configured Workspace volume. Runner identity is derived from the authenticated connection, not trusted from payload. Resource reports are separate from Heartbeat and never renew Lease. Stale, out-of-order, invalid, or unavailable samples make the Runner resource state `unknown` and block new dispatch; they do not prove process termination. SEM persists the latest snapshot in `runner_connection` and associates resource-profile/reservation metadata with `dispatch_operation`. Exact sampling intervals and admission thresholds are deployment-tuned and must be validated under Windows load tests; no unsupported fixed CPU/memory/disk threshold is assumed.


## 10. Resource telemetry and admission (ADR-SEM-26)

Runner Supervisor reports resource facts over the authenticated Runner–SEM WSS connection using `runner.resource.report`. The report includes `boot_id`, monotonically increasing `sample_seq`, UTC `observed_at`, CPU logical capacity and utilization windows, memory total/available/pressure, and total/free capacity of the actual Workspace volume. Runner identity is taken from the authenticated connection, never from a self-asserted payload field.

SEM stores the latest accepted snapshot in `runner_connection`; `dispatch_operation` stores the task Resource Profile and atomic CPU/memory/Workspace-volume reservation. This does not add an eighth mandatory SEM table. Samples that are stale, duplicated, out of order, invalid, or from an old boot must not overwrite the latest snapshot. Unknown/stale resources block new dispatch only; they do not stop active Runs or release reservations.

Resource reports are distinct from Runner Heartbeat, Lease Renewal and Harness Agent Activity. They never renew a Lease and never prove process start/exit or E1/E2/E3. A resource reservation is released only after definitive Platform Claim rejection (no Lease created) or after the relevant Run reaches a safe terminal/termination disposition. Unknown Claim outcomes retain the reservation and reuse the same `claim_request_id`.


## 11. Process-exit evidence and reconnect sync (Review Pending)

WSS V1 adds:
- `runner.process.exit`: natural exit or observed termination. Required fields: `message_id`, `connection_epoch`, `run_id`, `generation`, `boot_id`, `process_identity`, `exit_outcome`, `observed_at`, `source`, `evidence_digest`; `command_id` is optional for unsolicited/natural exits.
- `runner.process.reconciled`: after Runner restart, report each prior process as alive / absent-with-proof / unknown. Unknown is never converted to exit evidence.
- `runner.reconnect_sync`: current boot identity, active process inventory and pending local evidence spool references.

The Runner writes evidence to a local durable spool before WSS transmission and deletes/marks it delivered only after SEM has durably acknowledged it. Spool lives in Runner state storage, not a reclaimable per-Run Workspace. Lease expiry and stale Generation do not block reporting historical process facts; Platform accepts them only as evidence for the exact Run+Generation and does not allow them to mutate a newer generation.

E3 requires OS-observed exit for the exact process identity. Command receipt ACK and command result are separate. Natural exit, command termination, lease-loss cleanup, startup orphan cleanup, shutdown and boot-transition reconciliation must all report. If OS boot identity or process identity cannot be verified, classify E5.

## 12. Interaction command execution contract (Review Pending)

Interaction terminate/continue commands must have exactly one execution adapter for the Run's execution placement:
- Remote Runner: Platform business command → SEM durable `command_delivery` → Runner WSS → Runner Supervisor.
- SEM-local CodexExecutor: Platform business command → SEM local Execution Control Port → CodexExecutor/Harness adapter.

Both adapters implement terminate, continue-with-response, process-exit reporting and continuation-consumption reporting. A command must not be marked delivered/acked merely because no consumer exists. Continue injects checkpoint + response and by default starts a Fresh Harness Session; it is not Native Session Resume. `supports_resume=false` remains the default until tested.

Platform `worker_command` remains business command state; SEM `command_delivery` is remote transport state. For local execution, the same command result/evidence semantics apply without pretending a WSS delivery occurred. Command receipt, command result, E3 and continuation consumption are independent acknowledgements.

## 13. Notification and dispatchability requirements (Review Pending)

- `interaction.created` and HIR creation append notification Outbox events in the same transaction as their business records.
- Notification recipient resolution and per-recipient delivery status are explicit; project-level unassigned inbox is the fail-visible fallback.
- 120-second Interaction deadline is not notification delay.
- All Platform Claim/recovery/requeue paths use the same dispatchability predicate and check both Interaction shield and Execution Barrier, including queued Runs and B06-D3.

See [corrective design](./sem-02d-review-findings-corrective-design.md).


## 14. E6 Human Risk Acceptance protocol (Review Pending)

E6 is a Platform-authorized human risk decision, not a Runner process observation. It is recorded through the Platform HIR disposition API, with authenticated human principal, high-risk permission, explicit second confirmation, reason, displayed residual risks, mitigation record and a single bound successor Run/Generation. SEM may dispatch only the exact successor authorized by Platform after Claim succeeds. E6 must never be serialized as `process.terminated`, E3, command ACK or successful OS exit. The old Execution Barrier remains `risk_accepted_unconfirmed` until E1/E2/E3 independently proves termination. Duplicate or broader successor requests are rejected.
