# D-04 Independent Protocol Contract Review (Draft)

- Review date: 2026-11-25
- Scope: Platform↔SEM HTTP/HTTPS OpenAPI and JSON Schema; Runner↔SEM WSS JSON Schema; narrative protocol consistency.
- Reviewed branch: docs/sem-d05-lifecycle-crash-consistency
- Disposition: **CHANGES REQUIRED**
- This is a documentation review, not a security certification or implementation test.

## 1. What is established in the current draft

- HTTP and HTTPS share one application contract; transport choice does not fork message semantics.
- Platform→SEM has candidate execution submission, release and reconciliation routes.
- SEM→AI-PM has a candidate at-least-once infrastructure-event callback.
- Runner→SEM WSS uses an authenticated persistent outbound session with session-generation fencing.
- The schemas separate WSS connection-scoped message_sequence from Runner durable journal event_sequence.
- SEM→AI-PM event delivery has a separate execution_event_sequence scoped to execution_id. This is not the Runner journal cursor.
- The schemas preserve AI-PM business authority and SEM infrastructure authority.
- A 202 acceptance is durable infrastructure acceptance only; it is not Runner binding, process start or business completion.

## 2. Findings

### P0-01 — HTTP service authentication and request-integrity profile is approved but not fully machine-specified

The OpenAPI initially had a placeholder signature scheme. The narrative contract now proposes asymmetric Ed25519 HTTP Message Signatures (RFC 9421) plus Content-Digest (RFC 9530), with request/response signing, method/authority/path/query/body binding, key IDs, timestamp/expiry/nonce replay defense and key rotation. The algorithm-family decision is now approved in [D-04 Cryptographic Profile Decision](./D04-CRYPTOGRAPHIC-PROFILE-DECISION.md): Ed25519 + RFC 9421 + RFC 9530. The OpenAPI does not yet fully model covered components, signed response headers, key identifiers or test vectors. This remains a blocker for both HTTP and HTTPS; HTTPS is optional in V1 and therefore cannot be the sole integrity/authentication mechanism.

Required closure: fully model the approved Ed25519 + RFC 9421 + RFC 9530 profile in OpenAPI; define exact covered components, key distribution/rotation/overlap/revocation and timestamp/nonce bounds; add positive/negative canonicalization and replay test vectors.

### P0-02 — WSS authentication transcript baseline approved; exact transcript and vectors remain open

A separate WSS handshake JSON Schema now defines challenge, proof-of-possession, session establishment, acknowledgement and supersession envelopes. The narrative proposes Ed25519 over a domain-separated RFC 8785 JCS transcript, with 32-byte server/client nonces and a single-use 30-second challenge. The algorithm/canonicalization family is approved in [D-04 Cryptographic Profile Decision](./D04-CRYPTOGRAPHIC-PROFILE-DECISION.md): Ed25519 over a domain-separated RFC 8785 JCS transcript. Exact transcript field schema, cross-language test vectors, TLS audience/authority binding, key-version overlap and full implementation semantics remain open.

Required closure: freeze the exact Ed25519/JCS transcript fields; add positive/negative cross-language signature test vectors, nonce/challenge replay tests, key-version overlap/revocation behavior and handshake error responses.

### P0-03 — WSS message payloads have strict schemas; mechanical coverage remains unverified

The Runner WSS schema now defines a dedicated strict payload schema for every post-handshake message type: heartbeat/health, resource telemetry, admission, delivery, credential bootstrap, process lifecycle, release, ACK/error, superseded session and replay request/snapshot. State-changing payloads reject undeclared fields. The session-ack frame is defined only in the pre-application handshake schema to avoid duplicate ownership.

This closes the former generic-payload design gap at the schema-authoring level. It does not yet prove that every narrative catalogue row has exactly one branch, that all direction constraints match, or that every positive/negative fixture validates.

Required closure: mechanically compare the message_type enum and conditional branches to the narrative direction catalogue; add positive/negative fixtures for every branch; validate cross-field conditions and D-05 identity requirements; record reproducible validator output.
### P0-04 — SEM→AI-PM event payloads are discriminated; producer/receiver mapping remains open

The Platform–SEM schema now defines five discriminated event payloads: binding-established, delivery-status, process-observed, release-status and infrastructure-uncertain. They carry binding_epoch, Runner identity/key version, delivery/process/release evidence references and explicit uncertainty semantics. The schema deliberately excludes AI-PM Task/Requirement/Approval status fields.

The schema definitions are not yet mapped field-by-field to the SEM durable ledger and Runner event evidence, nor to an AI-PM receiver application service.

Required closure: source-map every event field to SEM durable ledger and Runner evidence; verify event sequence/outbox producer; define AI-PM Inbox table/unique key, authorization, transaction and response cursor semantics; add cross-repository fixtures. Ensure infrastructure events cannot express TaskStatus or approval decisions.
### P0-05 — Proposed SEM callback route does not exist in current AI-PM source; bilateral Inbox contract is not implemented

Read-only source audit against AI-PM master `d0e72fa6805aebeadf1b282e430deba493072fd6` confirms the proposed `/internal/ai-pm/v1/sem-events` route is not registered in `apps/pm-api/src/routes.rs`. The existing `/api/v1/events` route is a generic project-event ingestion endpoint with a different contract; it is not a SEM infrastructure-event Inbox and must not be repurposed by assumption. AI-PM has a transactional `integration.outbox_event` producer/worker framework, but that is outbound event handling and does not establish an inbound SEM event receiver. No SEM event Inbox table, unique `event_id` constraint, per-execution cursor, or callback handler is evidenced in the inspected source. The existing MCP Run tools also remain lease-token-based; they are a separate Harness business channel and cannot substitute for this callback.

Required closure: AI-PM must separately design and implement (only after bilateral ratification and authorization) a dedicated authenticated callback route, SEM event Inbox/deduplication store and transactional application handler. Freeze single-event vs batch behavior, ACK cursor, 2xx/4xx/5xx retry classification, dead-letter/operator recovery, event ordering/gap handling and atomic Inbox+Run-observation transaction. Do not treat the existing generic `/api/v1/events` endpoint or Outbox worker as this receiver.

### P1-01 — Cross-message identity requirements are not yet uniformly represented

Some WSS branches carry launch_id/containment_id/systemd invocation evidence, but the full D-05 identity tuple is not yet consistently required across start, exit, release-applied and replay records.

Required closure: define shared schemas for execution identity, Runner session identity, Supervisor journal identity, launch/containment identity and process identity; reuse them across all applicable message payloads.

### P1-02 — Version negotiation and unknown-field policy remain prose-level

schema_version is fixed to 1 in the current JSON Schema. The handshake draft mentions supported versions, but supported-version range negotiation, downgrade prevention, additive-field policy and unknown enum behavior are not fully machine-readable.

Required closure: define protocol version and schema version semantics separately; freeze negotiation and compatibility fixtures.

### P1-03 — Operational limits and retry timing remain unbounded

Maximum HTTP body, WSS frame, prompt and bootstrap sizes; compression; heartbeat intervals; resource report TTL; request timeout; retry/backoff; stop grace period defaults; journal retention and queue limits remain open.

Required closure: D-08/D-09 choose bounded values and the schema/OpenAPI expose any negotiated or configured limits.

### P1-04 — OpenAPI/JSON Schema validation is not yet evidenced

The current branch contains YAML-serialized OpenAPI 3.1 and JSON Schema 2020-12 files, but no CI validation workflow or recorded validator output is available. The current PR commit has no reported workflow runs/status checks.

Required closure: add a reproducible offline validator and positive/negative fixture suite; CI must parse OpenAPI, validate each schema, resolve references and validate examples.

## 3. Cross-contract invariants that must remain

1. Runner WSS transport message_sequence is per direction and connection generation.
2. Runner durable event_sequence is per runner_id + journal_id and survives WSS reconnect.
3. SEM→AI-PM execution_event_sequence is monotonic per execution_id and independent of the Runner journal cursor.
4. message_id/event_id idempotency identity cannot be reused with a different canonical body.
5. binding_epoch fences SEM delivery/release; authorization_generation fences AI-PM delegated MCP business access. Never substitute one for the other.
6. WSS disconnect, heartbeat timeout, ACK, exit code 0 or missing PID do not independently prove process exit.
7. SEM infrastructure events never directly mutate AI-PM Task state.
8. HTTP/HTTPS choice does not change the wire schema or retry/idempotency semantics.

## 4. Audit disposition

**D-04 remains P0 OPEN / CHANGES REQUIRED.** The current artifacts are a useful machine-readable baseline, but they are not complete, independently validated or ready for ratification. Do not start protocol implementation or merge the documentation PR solely on the basis of these initial artifacts.

Recommended next sequence:

1. Close HTTP request authentication and replay contract (P0-01).
2. Close WSS handshake schemas and signature test vectors (P0-02).
3. Complete every WSS and SEM→AI-PM event payload schema (P0-03/P0-04).
4. Cross-review callback endpoint, Inbox and retry contract against AI-PM source (P0-05).
5. Add identity reusable schema definitions and version negotiation (P1-01/P1-02).
6. Add validator tooling and fixture suite; record CI evidence (P1-04).
7. Freeze operational bounds with D-08/D-09 before ratification.