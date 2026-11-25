# Runner–SEM WebSocket Protocol and Dispatch Contract Draft

- Version: Draft 0.2
- Status: Architecture review; not normative and not implementation-authorizing.
- Owner: SEM (Runner transport, identity, admission and infrastructure delivery).
- Companion: [Platform–SEM Execution Message Protocol Draft](../../protocol/PLATFORM-SEM-EXECUTION-MESSAGE-PROTOCOL-DRAFT.md).
- Scope: Runner registration follow-up, authenticated WSS session, liveness, dispatch, delivery ACK, telemetry, reconnect and replay.
- Machine-readable schema: [Runner–SEM WSS v1 JSON Schema](./json-schema/runner-sem-v1.schema.yaml).
- Explicit non-goals: AI-PM business authorization, Task state, Harness MCP grant semantics, business retry policy, process-exit inference from connection state.

## 1. Protocol invariants

1. Runner initiates an outbound TLS-protected WSS connection to SEM. SEM does not initiate inbound connections to Runner. Internal enterprise CA and explicitly pinned self-signed server certificates are supported; certificate verification is mandatory.
2. One authenticated WSS session is the normal bidirectional channel for heartbeats, health probes, resource telemetry, execution delivery, delivery receipts, process observations and release commands.
3. Registration credentials are bootstrap-only. Every WSS session authenticates with the registered Runner key using proof of possession.
4. WSS transport connectivity, application liveness, Supervisor health, admission state and capacity are separate facts.
5. An open socket or successful ping/pong alone never makes a Runner dispatch-eligible.
6. SEM durably reserves capacity and commits the binding fence before sending a delivery.
7. Runner durably records a delivery before acknowledging it. Duplicate delivery IDs must not launch duplicate Harness processes.
8. Lost connection or missing ACK creates an uncertain delivery requiring reconciliation, not automatic reassignment.
9. A new connection generation fences the previous session. Late messages from an old session cannot mutate current Runner state.
10. Heartbeat timeout, WSS close, Runner reboot or resource telemetry loss is not positive process-exit evidence.
11. SEM payload handling remains infrastructure-only. Prompt and delegated bootstrap material are opaque.
12. At-least-once delivery is expected; idempotency and durable reconciliation provide correctness.

## 2. Connection establishment and cryptographic authentication

### 2.1 Registration prerequisite

The Runner must already have an SEM-issued immutable `runner_id`, registered public key and active key version. The one-time registration token is not accepted by the WSS authentication endpoint.

### 2.2 Handshake

Candidate handshake:

1. Runner opens `wss://<sem-host>/runner/v1/connect` over TLS.
2. SEM sends a fresh random challenge containing `challenge_id`, `server_nonce`, `issued_at`, `expires_at` and supported protocol versions.
3. Runner signs a canonical challenge transcript using its registered private key. The transcript binds at least protocol audience, `runner_id`, key version, challenge ID, both nonces, requested protocol version and TLS endpoint identity.
4. Runner sends `runner.auth.proof` with `runner_id`, `key_version`, `challenge_id`, `client_nonce`, selected protocol version and signature.
5. SEM verifies challenge freshness/single-use, key status, signature, audience and version. SEM rejects revoked, expired, unknown or superseded key versions according to the key-rotation overlap policy.
6. SEM sends `runner.session.established` with a new random `connection_id`, server-issued `session_generation`, negotiated protocol version and heartbeat policy.
7. Runner acknowledges the session and begins application heartbeats.

The exact canonical byte encoding, signature algorithm parameters, TLS policy, challenge TTL and key-rotation overlap must be frozen in D-01/D-09 before implementation. TLS trust configuration must support an enterprise CA bundle or an explicitly pinned self-signed certificate/public key; hostname/identity validation remains mandatory and verification bypass is forbidden. Ed25519 is the current D-01 candidate, not a ratified cryptographic profile.

### 2.3 Session fencing

- SEM permits one current active session generation per `runner_id`, unless a later explicit multi-session design is approved.
- A successful new authentication atomically supersedes the previous connection generation.
- Every post-handshake Runner message carries `connection_id` and `session_generation`.
- SEM rejects messages from a superseded connection, including delayed messages arriving after reconnect.
- If two sessions authenticate concurrently, the durable session-generation compare-and-swap winner is current; the loser receives `runner.session.superseded` and closes.
- A session generation is a connection fence, not a process-exit or business authorization fence.

## 3. Common WSS envelope

All application messages use a common envelope. Fields shown are required unless marked optional.

```json
{
  "protocol": "sem.runner.v1",
  "schema_version": 1,
  "message_id": "uuid",
  "message_type": "runner.heartbeat",
  "runner_id": "uuid",
  "connection_id": "uuid",
  "session_generation": 17,
  "message_sequence": 42,
  "occurred_at": "RFC3339 UTC",
  "payload": {}
}
```

Rules:

- `message_id` is globally unique per sender message and is used for deduplication.
- `message_sequence` is a transport sequence, monotonically increasing for each direction within one connection generation. It starts a new sequence space after reconnect and is used for connection-level gap detection only.
- Durable Runner observations additionally carry `journal_id` and `event_sequence`. `event_sequence` is monotonically increasing within the durable stream keyed by `runner_id + journal_id`, survives WSS reconnects, and is never reset merely because `connection_id` or `session_generation` changes.
- SEM validates both sequence domains independently. A transport sequence gap triggers connection replay/reconciliation; a durable event sequence gap triggers journal replay/reconciliation. Neither sequence may be substituted for the other.
- `occurred_at` is the sender's observation time. SEM also records server-side `received_at`; server receipt time is authoritative for freshness decisions.
- `runner_id`, `connection_id` and `session_generation` must match the authenticated session.
- Unknown optional fields are ignored only when schema compatibility policy allows it. Unknown message types are rejected with a structured unsupported-message error.
- A duplicate `message_id` with byte-equivalent canonical content returns the original disposition. Same ID with different content is a protocol conflict and closes/quarantines the offending session pending policy.
- JSON is the initial candidate encoding. Canonical serialization for signatures and payload hashes must be separately specified; ordinary JSON textual equivalence is not sufficient.
- Maximum frame size, compression policy, binary-frame policy and prompt size are D-09 configuration/security decisions. Oversized frames are rejected before durable processing.

## 4. Message catalogue and direction

| Direction | Message | Purpose |
|---|---|---|
| SEM → Runner | `runner.challenge` | Fresh authentication challenge |
| Runner → SEM | `runner.auth.proof` | Proof of private-key possession |
| SEM → Runner | `runner.session.established` | Bind connection generation and negotiated policy |
| Runner → SEM | `runner.heartbeat` | Application liveness and Supervisor status |
| SEM → Runner | `runner.health_probe` | Optional correlated health check |
| Runner → SEM | `runner.health_report` | Probe response |
| Runner → SEM | `runner.resources.report` | CPU, memory, disk/workspace-volume and capacity report |
| Runner → SEM | `runner.admission.changed` | Accepting/draining/disabled transition |
| SEM → Runner | `execution.deliver` | Opaque execution delivery |
| Runner → SEM | `execution.delivery_received` | Durable Supervisor receipt |
| Runner → SEM | `harness.starting` / `harness.started` / `harness.start_failed` | Process launch observations |
| Runner → SEM | `harness.process_exited` | Exact process exit observation |
| SEM → Runner | `execution.release` | Fenced stop/release instruction |
| Runner → SEM | `execution.release_applied` | Release handling and process facts |
| Either direction | `protocol.ack` | Acknowledge durable processing where required |
| Either direction | `protocol.error` | Structured protocol failure |
| SEM → Runner | `runner.session.superseded` | Close stale connection |
| Runner → SEM | `runner.replay.request` | Request reconciliation after reconnect |

Application heartbeat is not replaced by WebSocket ping/pong. Ping/pong is a transport keepalive and fast dead-peer hint only.

## 5. Heartbeat and health semantics

### 5.1 Runner heartbeat

Candidate payload:

```json
{
  "boot_id": "uuid",
  "supervisor_state": "healthy",
  "accepting_work": true,
  "draining": false,
  "active_execution_count": 2,
  "process_registry_state": "consistent",
  "resource_report_id": "uuid",
  "runner_monotonic_uptime_ms": 1234567
}
```

- `boot_id` changes on every OS/Runner host boot boundary detectable by the Supervisor.
- `runner_monotonic_uptime_ms` is diagnostic only; it is not compared across boots.
- Heartbeat reports Supervisor health and admission, but does not replace detailed resource telemetry.
- SEM freshness uses server `received_at`, not an untrusted Runner wall clock.
- Heartbeat interval and suspect/stale thresholds are configurable deployment parameters, not hardcoded protocol constants. D-09 must select initial defaults and bounds.
- A missed heartbeat moves liveness through `healthy → suspect → stale`; transport closure moves transport to disconnected. Exact timers are operational policy.
- SEM may send a health probe on the existing WSS connection as heartbeat freshness approaches its threshold. A health report must echo the probe ID and current boot/session identifiers.

### 5.2 Independent state dimensions

| Dimension | Values | Derived from |
|---|---|---|
| Transport | connected / disconnected | Current authenticated WSS session |
| Liveness | healthy / suspect / stale | Application heartbeat and health probe freshness |
| Supervisor | healthy / degraded / failed / unknown | Runner-reported Supervisor state plus reconciliation |
| Admission | accepting / draining / disabled / quarantined | Explicit Runner state and SEM policy |
| Capacity | available / constrained / unknown | Fresh resource report minus durable reservations |
| Dispatch eligibility | eligible / ineligible | SEM-derived conjunction of all required dimensions |

A user-facing “Online” summary may mean authenticated transport connected and liveness healthy. It must not imply admission or capacity.

## 6. Resource telemetry contract

A resource report is bound to `runner_id`, `boot_id`, `connection_id`, `session_generation`, `resource_report_id` and sequence. Candidate payload:

```json
{
  "boot_id": "uuid",
  "resource_report_id": "uuid",
  "observed_at": "RFC3339 UTC",
  "cpu": {
    "logical_cores": 16,
    "utilization_ratio": 0.42,
    "available_millicores": 8000
  },
  "memory": {
    "total_bytes": 34359738368,
    "available_bytes": 17179869184
  },
  "workspace_volume": {
    "volume_id": "workspace",
    "total_bytes": 500000000000,
    "available_bytes": 300000000000,
    "reserved_bytes": 10000000000
  },
  "execution_capacity": {
    "max_concurrent": 4,
    "active": 2,
    "accepting": true
  }
}
```

- Values must have documented units and semantics; ratio fields are bounded to [0,1].
- Resource reports are observations, not guarantees. SEM applies safety margins and durable reservations.
- Reports from a prior `boot_id`, prior connection generation or stale timestamp are not used for admission.
- Missing dimensions are unknown, not zero and not unlimited.
- Runner must not self-assign a reservation. SEM is the sole reservation authority.
- Resource report cadence, freshness TTL, capacity weights, overcommit and disk safety margins belong to D-08/D-09.
- SEM records report receipt time and derives capacity from the latest valid report plus outstanding reservations.

## 7. Dispatch and delivery handshake

1. AI-PM submits an idempotent execution request over the versioned internal HTTP contract.
2. SEM queues it and selects only a Runner whose authenticated session, liveness, Supervisor, admission and capacity satisfy the dispatch predicate.
3. In one SEM database transaction, SEM creates/updates the binding, increments `binding_epoch`, creates a capacity reservation and persists a delivery record with stable `delivery_id`.
4. Only after commit does SEM send `execution.deliver` over the current WSS connection.
5. Runner Supervisor validates the delivery against current session and binding, then durably writes its local delivery/process registry before sending `execution.delivery_received`.
6. SEM records the receipt. This ACK means “durably accepted by Supervisor”, not “Harness started”.
7. Runner emits `harness.starting`, then `harness.started` only after OS process creation and exact process identity capture. If launch fails before process identity exists, emit `harness.start_failed`.
8. SEM emits the corresponding infrastructure event to AI-PM through its durable event outbox.

Delivery receipt candidate:

```json
{
  "execution_id": "uuid",
  "delivery_id": "uuid",
  "binding_epoch": 3,
  "receipt": "durably_accepted",
  "local_record_id": "uuid"
}
```

- Duplicate delivery with the same `delivery_id` returns the same durable receipt and never creates another logical process.
- Same `execution_id` + `binding_epoch` with a different `delivery_id` is rejected unless the explicit recovery protocol authorizes it.
- Runner rejects stale `binding_epoch`, stale session generation, unknown execution or revoked Runner identity.
- A receipt must be correlated to the exact `delivery_id`, `execution_id`, `binding_epoch` and Runner boot/session.
- Runner local durable registry must survive Supervisor process restart. Workspace backup is not required; execution identity and process evidence are durable operational state.

## 8. Disconnect, reconnect and replay

### 8.1 On disconnect

- SEM marks transport disconnected and liveness stale/unknown according to policy.
- SEM stops new dispatch to that Runner immediately.
- SEM does not infer whether the last delivery was received, whether Harness started, or whether a process exited.
- Active reservations and bindings remain held or move to an explicit uncertain/quarantined state; they are not silently released.
- No competing Runner may start the same execution until the previous binding is fenced and process safety is established under the D-03 rules.

### 8.2 On reconnect

1. Runner reconnects and repeats the full cryptographic challenge-response handshake.
2. SEM creates a new `connection_id` and `session_generation`; prior connection messages are fenced.
3. Runner sends `runner.replay.request` with its `boot_id`, last durable local event sequence, known active execution IDs and local registry digest/version.
4. SEM returns a reconciliation snapshot of its outstanding deliveries, bindings, releases and last acknowledged event sequence for that Runner.
5. Runner replays durable unacknowledged observations with their original event IDs and sequence numbers, marked as replayed in transport metadata (original event identity is preserved).
6. SEM deduplicates by event/message ID and validates execution/binding/boot identity. Conflicts are quarantined for operator review.
7. SEM and Runner reconcile every in-flight execution before the Runner becomes eligible for new work. Eligibility may be restored for unrelated new work only if reconciliation proves Supervisor/process registry consistency and capacity is trustworthy.

Runner must not invent missing process-exit events after reboot. If the prior boot's process cannot be positively observed as exited or independently fenced, the execution remains uncertain under D-03.

## 9. Sequence, ACK and backpressure

- Message sequence is per direction and connection generation. A gap is detected and triggers replay/reconciliation; it is not silently interpreted as message loss being harmless.
- Durable business-independent events (delivery receipt, process start/exit, release applied, admission change) must be persisted in Runner's local event journal before send and retained until SEM acknowledges them.
- Heartbeats and replaceable resource snapshots may be coalesced; their latest state supersedes older snapshots, but sequence gaps still signal that reconciliation may be needed.
- `protocol.ack` includes the acknowledged message/event ID and durable disposition. ACK of receipt is not ACK of process start or exit.
- SEM applies bounded per-Runner outbound queues. Prompt deliveries and release commands are durable; health probes may be dropped/coalesced; telemetry snapshots may be coalesced.
- When a Runner cannot keep up, it sends an explicit degraded/backpressure admission change. SEM stops new work while preserving existing execution supervision.
- Queue limits, maximum in-flight deliveries, frame size, event-journal retention and backpressure thresholds are D-08/D-09 parameters.

## 10. Error model

Candidate error envelope:

```json
{
  "protocol": "sem.runner.v1",
  "schema_version": 1,
  "message_id": "uuid",
  "message_type": "protocol.error",
  "in_reply_to": "uuid",
  "error": {
    "code": "STALE_BINDING_EPOCH",
    "class": "permanent",
    "retryable": false,
    "retry_after_ms": null,
    "detail": "Delivery binding is no longer current"
  }
}
```

Initial error classes:

| Code | Class | Retryable | Required behavior |
|---|---|---:|---|
| AUTH_CHALLENGE_EXPIRED | auth | no | Start a new handshake |
| AUTH_KEY_REVOKED | auth | no | Close session; operator/admin recovery |
| SESSION_SUPERSEDED | conflict | no | Close old session |
| UNSUPPORTED_PROTOCOL | compatibility | no | Negotiate supported version or upgrade |
| INVALID_ENVELOPE | protocol | no | Reject; repeated abuse may close session |
| MESSAGE_ID_CONFLICT | security/protocol | no | Quarantine session and audit |
| SEQUENCE_GAP | reconciliation | yes | Replay/reconcile; do not apply out of order |
| STALE_BINDING_EPOCH | conflict | no | Reject stale delivery/release |
| CAPACITY_UNAVAILABLE | admission | yes | Keep queued or reschedule |
| SUPERVISOR_NOT_READY | admission | yes | Mark ineligible until healthy |
| DELIVERY_OUTCOME_UNKNOWN | uncertain | reconcile | Do not blindly reassign |
| RESOURCE_REPORT_STALE | admission | yes | Request fresh telemetry |
| INTERNAL_TRANSIENT | transient | yes | Bounded retry with backoff |

Error detail must not contain secrets, prompt body, MCP token, private key material or sensitive filesystem paths.

## 11. Ordering and idempotency matrix

| Operation | Idempotency key | Duplicate behavior |
|---|---|---|
| Authentication proof | challenge_id | Single use; second redemption rejected |
| Heartbeat | message_id + session generation | Duplicate ignored; freshness not extended by replay |
| Resource report | resource_report_id | Duplicate ignored; old report cannot replace newer report |
| Delivery | delivery_id | Same durable receipt; no second process |
| Process observation | event_id | Same durable event disposition |
| Release command | release_id + binding_epoch | Same result; stale epoch rejected |
| Admission change | message_id + sequence | Duplicate ignored; out-of-order requires reconciliation |

No sender may reuse an idempotency key with a different canonical body.

## 12. Dispatch eligibility predicate

A Runner is eligible only if all are true:

- identity is active and current key is not revoked;
- authenticated WSS session is current;
- transport is connected;
- application heartbeat and Supervisor health are fresh;
- boot ID and latest resource report agree;
- Supervisor process registry is consistent;
- admission is accepting and not draining/disabled/quarantined;
- resource report is fresh and required capacity remains after reservations and safety margins;
- no unresolved conflicting binding or reservation exists;
- protocol version is compatible with the queued delivery.

Eligibility is re-evaluated immediately before reservation and delivery. Reservation is atomic and durable. A health or capacity change after reservation does not erase the reservation; it may stop subsequent dispatch and trigger reconciliation.

## 13. Acceptance test matrix

1. Unknown/revoked Runner key cannot authenticate.
2. Expired or replayed challenge cannot authenticate.
3. Private key never appears in registration or WSS payloads.
4. A second authenticated session fences the first; late old-session messages are rejected.
5. Open socket plus stale application heartbeat is ineligible.
6. Ping/pong without application heartbeat is ineligible.
7. Fresh heartbeat but degraded Supervisor is ineligible.
8. Draining/disabled/quarantined Runner receives no new delivery.
9. Resource report from prior boot or stale connection is ignored.
10. Concurrent schedulers cannot over-reserve reported capacity.
11. Delivery is not sent before reservation and binding fence are durable.
12. Duplicate delivery ID never starts a second Harness.
13. WSS loss before receipt ACK causes uncertain state and reconciliation, not blind reassignment.
14. WSS loss after receipt ACK but before process-start event remains uncertain until replay/reconciliation.
15. Reconnect uses a new connection generation and rejects old-generation events.
16. Runner replay is idempotent and preserves original event identity.
17. Sequence gap prevents unsafe state advancement and triggers reconciliation.
18. Resource snapshots may coalesce; process/delivery/release events may not be silently dropped.
19. Heartbeat timeout never creates process-exited evidence.
20. Runner reboot with unknown prior process state remains quarantined under D-03.
21. Release command with stale binding epoch cannot stop a newer process.
22. Backpressure changes admission and prevents additional dispatch without corrupting active executions.
23. Unknown required protocol version fails closed; compatible optional fields are handled per schema policy.
24. Prompt body and delegated bootstrap bytes remain opaque to SEM and are absent from logs/errors.

## 14. Machine-readable contract and decisions still open before this contract can be frozen

- Exact Ed25519 transcript encoding, signature domain separation and challenge TTL (D-01).
- Whether the initial protocol is JSON text frames only; frame-size and compression policy (D-09).
- Heartbeat interval, suspect/stale thresholds, health-probe timing and resource-report TTL (D-08/D-09).
- Exact resource units, admission weights, safety margins, reservation expiry and fairness (D-08).
- Local Runner event journal implementation, fsync guarantees, retention and disk-full behavior (D-10).
- Whether a Runner may maintain more than one WSS session or endpoint for HA (default: one current session).
- Exact event replay snapshot schema and retention window (D-05/D-10).
- TLS termination topology, enterprise/self-signed certificate trust provisioning, pinning, hostname validation, renewal/rotation/revocation, rate limits and ingress protection (D-09).
- Whether SEM sends an explicit server-side delivery cancellation before release or only the fenced release instruction (D-05).

The JSON Schema is a validation baseline, not a ratified wire contract. It intentionally leaves the handshake transcript, complete payload refinements for every message, timer values, frame limits and replay snapshot semantics open.

Until these are resolved and accepted, this document remains Draft / Review. It is not an implementation authorization.
