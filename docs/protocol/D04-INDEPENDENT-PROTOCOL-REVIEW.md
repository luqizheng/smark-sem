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

### P0-03 — WSS schema does not yet define every message payload

Heartbeat, resource report, delivery receipt, Harness start/exit, delivery and release have partial schema branches. Health probe/report, admission change, release-applied, replay request/snapshot, protocol ACK/error and credential bootstrap remain incomplete or generic.

Required closure: every catalogue message must map to exactly one complete schema branch, including required payload fields, identity tuple, duplicate semantics and legal sender direction. No untyped opaque payload is allowed for state-changing messages except explicitly opaque business material.

### P0-04 — SEM→AI-PM event payloads remain generic

The event schema defines the envelope and event type enum, but payload is only a generic object. Binding-established, delivery-status, process-observed, release-status and infrastructure-uncertain payloads need exact versioned schemas and required fields.

Required closure: add per-event payload schemas, source/evidence provenance, binding_epoch, runner identity, process evidence reference and explicit unknown/null semantics. Ensure infrastructure events cannot express TaskStatus or approval decisions.

### P0-05 — Endpoint ownership and callback delivery handshake are candidates, not cross-repository facts

The callback path and server ownership are proposed in OpenAPI but have not been verified against AI-PM route conventions or an actual receiver implementation. The callback acknowledgement currently returns event_id/disposition only; retry policy, durable inbox transaction boundary, ordering cursor response and backpressure are not frozen.

Required closure: review the exact route and authentication middleware in ai-pm; define event batch/single-event behavior, ACK cursor, 2xx/4xx/5xx retry classification, dead-letter/operator recovery and transactional inbox/outcome semantics.

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