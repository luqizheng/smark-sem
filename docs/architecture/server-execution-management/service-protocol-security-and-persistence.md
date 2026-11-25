# SEM-02C — Service Protocol, Security and Persistence Baseline

- Status: **User-ratified architecture baseline (ADR-SEM-21–25); not implemented**
- Scope: Platform ↔ SEM service authentication, Runner ↔ SEM WSS authentication/revocation, Lease Renewal, SEM-owned persistence, idempotency and cross-service recovery.
- Authority: Platform remains the only authority for Run, Lease, Generation, command business state, HIR and business audit. SEM owns transport and execution-side private state only.
- Constraints: independent databases; no shared SQL; no Redis/Kafka/RabbitMQ; no Workspace backup; one Git origin; Runner default is unattended.

## 1. Lease Renewal — ratified single path

### 1.1 Ratified decision (ADR-SEM-21)

Use exactly one Lease Renewal path:

**Runner Supervisor → authenticated WSS → SEM → versioned Platform HTTPS API → Platform PostgreSQL transaction.**

The Runner Supervisor initiates renewal only while it is supervising the exact active Harness process. SEM authenticates the WSS connection and forwards the request. Platform validates and commits the renewal. Neither SEM nor Runner may directly change the lease expiry.

This is a dedicated `lease.renew` control message, not a side effect of Heartbeat or Agent Activity.

### 1.2 Three independent signals

| Signal | Producer / path | What it proves | Renews Lease? |
|---|---|---|---|
| Runner Supervisor Heartbeat | Runner → SEM WSS | Supervisor loop and connection are alive | **No** |
| Lease Renewal | Runner Supervisor → SEM WSS → Platform HTTPS | Authenticated supervisor requests renewal for one exact active Run/process/generation | **Yes, only after Platform accepts it** |
| Harness Agent Activity | Harness → Platform MCP | Agent reported business/execution progress | **No** |

A quiet or thinking Harness may still be supervised by a live Runner; lack of Agent Activity must not expire a healthy execution lease. Conversely, a live WSS connection alone must not keep a Run leased when the Runner is no longer supervising its target process.

### 1.3 Renewal request contract

Required fields:
- `request_id` (stable idempotency key for this renewal attempt)
- `runner_id` / authenticated device identity (derived from WSS identity, not trusted from payload)
- `run_id`
- `lease_generation`
- `lease_token` (opaque bearer proof; never logged or persisted by SEM)
- `process_identity` (the exact OS process identity supervised)
- `supervisor_session_id`
- `sent_at`
- `protocol_version`

Platform must atomically verify:
1. service identity is the registered SEM service and has the `lease.renew` scope;
2. target Runner/device is registered, active, authorized for the Project and still bound to the lease;
3. `lease_client_id`, Run ID and Generation match the current lease;
4. token proof matches the current verifier;
5. Run is in a renewable state and not under Scheduling Shield;
6. process identity / supervisor session is consistent with the active execution record;
7. task/run deadline and maximum execution policy have not been exceeded;
8. `request_id` has not already been applied with a conflicting payload.

Only Platform updates lease expiry and writes the audit event. A duplicate request with the same idempotency key and same body returns the prior result. Same key with a different body is rejected.

### 1.4 Renewal failure behavior

- `stale_generation`, `lease_owner_mismatch`, `lease_expired`, `scheduling_shield_active` and `authorization_denied` are terminal for that generation; Runner must stop attempting renewal and follow cancellation/isolation instructions.
- Network timeout is an unknown outcome. Retry with the same `request_id`; do not assume failure or success.
- Platform outage: Runner may continue only within the last confirmed lease validity and local safety policy. Once lease validity can no longer be established, stop issuing new side effects; process termination/uncertainty follows E1–E5 and HIR rules.
- A missed Heartbeat does not prove process death. It may cause connection status to become offline and eventually E4, never automatic re-claim.
- A process exit ends renewal. Runner sends E3 only after OS wait/handle confirms the exact process exited.

### 1.5 Token handling

- Platform stores only the normal token verifier/hash for authorization.
- Claim response is idempotent. To recover from a lost SEM response after a successful Claim, Platform retains the claim response in an encrypted, short-lived idempotency record under Platform-controlled encryption. The same authenticated SEM request with the same `claim_request_id` can retrieve the same grant until the retention window expires.
- SEM may hold the lease token only in process memory long enough to dispatch it over the authenticated WSS connection and relay renewal. It must not persist the token, place it in delivery ledgers, or emit it in logs/traces/errors.
- Runner receives the token only for the exact Run and Generation. A generation change invalidates it.

## 2. Platform ↔ SEM service authentication (ADR-SEM-22)

### 2.1 Identity model

Use separate service identities in both directions:
- Platform authenticates to SEM when delivering Outbox events.
- SEM authenticates to Platform when requesting Claim, Lease Renewal, command status, execution result or evidence operations.

Service identities are not human principals and must not pass through the ordinary human-principal resolution path.

### 2.2 HTTPS request authentication

Ratified V1 mechanism:
- TLS for every connection.
- Short-lived asymmetric-signed service JWTs; no shared static bearer secret.
- Each service has a registered `service_id`, public verification key(s), allowed audience(s), and explicit scopes.
- JWT claims: `iss`, `sub`, `aud`, `iat`, `nbf`, `exp`, `jti`, `kid`, `scope`; maximum lifetime 5 minutes.
- Platform and SEM each validate issuer, audience, signature, time window, key status and endpoint scope.
- `kid` supports overlapping key rotation. Revoking a service identity or key immediately rejects new requests; short JWT lifetime bounds exposure of already-issued tokens.
- mTLS may be enabled as an additional transport control where deployment infrastructure supports it, but JWT service identity remains the application authorization contract.

### 2.3 Scope separation

SEM receives only the minimum scopes needed, for example:
- `run.claim.for_runner`
- `lease.renew`
- `command.read`
- `command.ack`
- `execution.report`
- `termination.evidence.submit`
- `runner.authorization.read`

Platform event delivery to SEM is restricted to:
- `sem.inbox.write`

These are conceptual scope names; exact route names and DTOs are finalized in the API contract. SEM must not receive general Project administration, user impersonation, arbitrary MCP access or database access.

### 2.4 Request integrity and idempotency

Every mutating service request carries:
- `request_id` / idempotency key;
- correlation ID and causation/event ID where applicable;
- protocol/schema version;
- exact Run/Generation/Runner scope where applicable.

Retries use the same idempotency key and identical semantic payload. Platform stores the idempotency outcome in its own DB transaction with the business mutation. Duplicate requests return the stored outcome; conflicting reuse is rejected. JWT `jti` replay protection is separate from business idempotency.

### 2.5 Key rotation and outage

- Maintain current and next public keys during rotation.
- Rotate private signing keys without invalidating requests already in flight; remove old key only after maximum token lifetime plus clock-skew allowance.
- Service identity disablement and key revocation are audited.
- If service authentication or key status cannot be established, fail closed for Claim, renewal, command mutation and termination evidence. Do not fall back to shared DB or unauthenticated internal network trust.

## 3. Runner ↔ SEM WSS authentication and revocation (ADR-SEM-23)

### 3.1 Connection establishment

1. Runner authenticates to Platform using its existing registered Client/Device credential through a dedicated Platform connect-ticket endpoint. This does not make the credential a SEM service credential.
2. Platform verifies device registration, status, tenant/project binding, credential validity and authorization.
3. Platform issues a short-lived, single-use WSS ticket scoped to the SEM audience and the exact Runner/device identity. The ticket includes `jti`, `kid`, `iat`, `exp`, allowed scopes and the credential/device binding. Ticket lifetime is at most 60 seconds.
4. Runner opens WSS to SEM and presents the ticket. SEM validates the Platform signature, audience, expiry, scope and device identity, then atomically consumes `jti` in SEM DB. A replayed ticket is rejected.
5. SEM creates a new `connection_id` and monotonically increasing `connection_epoch`. The authenticated identity is derived from the validated ticket; payload `runner_id` is never trusted as identity.

The connect-ticket endpoint is a Platform device-authenticated endpoint, not a relaxation of ordinary human-principal authentication and not an extension of the current MCP-only credential path to all business APIs.

### 3.2 Continuous authorization and revocation

A WSS handshake is not perpetual authorization.

- Platform emits revocation/authorization-change Outbox events for device credential revocation, device disablement, project unbinding, tenant suspension and relevant policy changes.
- SEM consumes these events through its durable Inbox and closes affected WSS connections before further command delivery.
- SEM also performs periodic authorization revalidation against Platform API to detect missed events. Recommended default maximum authorization freshness window: 30 seconds, configurable but bounded.
- If revalidation cannot complete before the freshness window expires, SEM marks the connection unauthorized/stale, stops dispatch and closes WSS. It must not continue indefinitely on cached authorization.
- On revocation, pending commands are not delivered. Already-running processes are not assumed dead; they enter the normal stop/termination-evidence path. If termination cannot be proven, E4/E5 shield and HIR apply.
- Reconnection always requires a fresh ticket. A prior WSS session or ticket cannot be resumed as proof of current authorization.

### 3.3 Message protection

- WSS over TLS; validate Origin/host policy where relevant, message size limits and rate limits.
- Each message carries `message_id`, `schema_version`, `connection_epoch`, `sent_at`, and correlation ID; execution messages additionally carry Run ID, Generation and command ID as applicable.
- SEM rejects stale connection epochs, stale generations, duplicate non-idempotent operations and messages outside the authenticated device scope.
- Heartbeat, command receipt ACK, process termination ACK and Lease Renewal are distinct message types.
- A connection close does not prove Runner process termination.

## 4. SEM database — minimum ownership model (ADR-SEM-24)

SEM DB is a private execution/transport database. It must not mirror Platform business state.

| Table | Minimum purpose / fields | Explicit exclusions |
|---|---|---|
| `sem.inbox_event` | `event_id` PK, event type, schema version, minimal payload/reference, received time, status, attempt count, next retry, processed time, error code | No copied Run/Task status authority |
| `sem.runner_connection` | connection ID, Runner/device ID, credential reference, connection epoch, connected/last-seen/auth-valid-until/revoked/disconnected timestamps, status/reason | No independent device registration or project authorization authority |
| `sem.runner_ticket_use` | ticket `jti` PK, Runner ID, consumed time, expiry | No reusable credential or ticket plaintext |
| `sem.dispatch_operation` | operation ID, source event ID, Run ID reference, target Runner ID, claim request idempotency key, stage, Platform result reference, Generation after claim, timestamps/error | No lease token plaintext; no authoritative Run state |
| `sem.command_delivery` | delivery ID, Platform command ID, Run ID, Generation, target Runner, message ID, delivery status, attempts, sent/received/terminal ACK timestamps, expiry, last error | No independent command business payload/status authority |
| `sem.platform_delivery` | outbound delivery ID, event/evidence reference, idempotency key, target Platform API operation, retry state, attempts, next retry, last response/error | No duplicate business audit authority |
| `sem.process_observation` | Runner ID, Run ID, Generation, process identity, observed state/time, evidence class, evidence digest/reference | No authority to set Run status, release Shield or grant a Lease |

All tables use UTC timestamps, bounded retention, indexed retry/lookup keys and explicit tenant/project scoping where needed. Secrets and raw lease tokens are excluded. SEM DB credentials are least-privilege and cannot access Platform DB.

### 4.1 Inbox transaction

SEM accepts an event only after inserting `inbox_event` with a unique `event_id` and committing the transaction. Only then does it return an accepted response to Platform Outbox. Event processing happens asynchronously and is retryable. Duplicate `event_id` returns the already-recorded receipt.

Inbox event payloads are wake-up/reference data. Before dispatch, SEM obtains current eligibility and business details from Platform API; it never treats an old Outbox payload as proof that a Run remains claimable.

### 4.2 Dispatch crash recovery

- SEM persists `dispatch_operation` before requesting Claim.
- `claim_request_id` is stable across retries.
- Platform Claim and its idempotency result commit atomically.
- If SEM loses the HTTP response, it retries/queries using the same idempotency key; it must not create a second Claim.
- If Claim succeeded but SEM crashed before WSS delivery, recovery obtains the same grant result and dispatches only to the same authorized target Runner, subject to current Platform lease validity.
- If the target Runner is no longer authorized/connected or the lease is no longer valid, SEM requests guarded cancellation/recovery from Platform; it must not silently redirect an already-claimed lease to another Runner.
- A new target Runner requires the normal guarded handoff and a new Platform Claim/Generation.

### 4.3 Command delivery

Platform `worker_command` remains the business command authority. SEM reads authorized command intent from Platform API, writes/updates `command_delivery`, then sends over WSS. Delivery status is transport evidence only. Receipt ACK updates the SEM delivery ledger and is forwarded to Platform API. Termination ACK/E3 is separately validated and persisted by Platform as authoritative evidence.

## 5. Cross-service failure matrix

| Failure | Required behavior |
|---|---|
| Platform Outbox delivers duplicate event | SEM Inbox unique `event_id`; acknowledge duplicate without duplicate dispatch |
| SEM DB unavailable | Do not ACK event; Platform Outbox retries |
| SEM crashes after Inbox commit, before processing | Resume pending Inbox event after restart |
| Platform API unavailable before Claim | Keep dispatch pending; no Runner starts |
| Claim commits but HTTP response is lost | Retry same `claim_request_id`; return same idempotent result |
| Claim succeeds but WSS delivery fails | Keep same Run/Generation bound to same target; retry only while Platform confirms lease; otherwise guarded cancel/shield/HIR, never blind reassign |
| WSS disconnect during active Run | Mark Runner offline; do not infer process death; E4/E5 as evidence dictates |
| Runner sends duplicate command ACK | Idempotent by command ID + Run + Generation + message ID |
| SEM outbound evidence delivery fails | Persist `platform_delivery`; retry same idempotency key |
| Platform revokes device while WSS is open | Revocation event closes connection; periodic revalidation bounds missed-event exposure |
| Platform unavailable during revocation revalidation | Stop new dispatch and close stale connection at auth freshness deadline |
| SEM DB lost | No Workspace backup or inference of process death; reconcile with Platform and process evidence; uncertain active Runs shielded/HIR |
| Lease renewal request times out | Retry same request ID; never create a parallel renewal path |

## 6. API operation inventory (logical, versioned)

The exact route strings, DTOs, status codes, retryability classes and error envelopes are SEM-02D design deliverables and must be frozen before Phase 1 implementation. The logical operations and authority are fixed:

| Direction | Operation | Authority / idempotency |
|---|---|---|
| Platform → SEM | `inbox.accept_event` | SEM Inbox; unique `event_id` |
| SEM → Platform | `dispatch.claim_for_runner` | Platform Claim transaction; stable `claim_request_id` |
| SEM → Platform | `lease.renew` | Platform Lease transaction; stable `request_id` |
| SEM → Platform | `command.get_pending` | Platform command authority; read-only |
| SEM → Platform | `command.ack_receipt` | Platform command state; command/Run/Generation scoped |
| SEM → Platform | `execution.report` | Platform Run/event services; idempotent |
| SEM → Platform | `termination.submit_e3` | Platform validates process/Run/Generation evidence |
| SEM → Platform | `runner.authorization_check` | Platform device/Project authorization |
| Runner → SEM WSS | `runner.heartbeat` | SEM connection liveness only |
| Runner → SEM WSS | `lease.renew` | Forwarded to Platform; no SEM lease authority |
| Runner → SEM WSS | `command.received` | SEM delivery ledger, then Platform command ACK |
| Runner → SEM WSS | `process.terminated` | SEM forwards E3 evidence; Platform remains authoritative |
| Runner → SEM WSS | `runner.reconnect_sync` | SEM connection state; Platform reconciliation required |

## 7. Design rules (ADR-SEM-21–25)

1. Platform is the only authority for Run, Lease, Generation, command business state, HIR and business audit.
2. SEM is the only Runner dispatch/handoff coordinator, not an execution-right authority.
3. Runner control plane uses WSS; Harness business plane retains Platform MCP.
4. Lease Renewal has exactly one path: Runner Supervisor → WSS → SEM → Platform HTTPS. Heartbeat and Agent Activity do not renew.
5. Platform–SEM and Runner–SEM identities are separate; neither service identity nor device identity may impersonate a human.
6. SEM persists transport/execution-private facts only; no shared DB and no business-state mirror.
7. Every cross-service mutation is authenticated, scoped, idempotent, auditable and retryable.
8. Any ambiguous process/lease outcome fails closed: shield/HIR, never blind re-dispatch.
