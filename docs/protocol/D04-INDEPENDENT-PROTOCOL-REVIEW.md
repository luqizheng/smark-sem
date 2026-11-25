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

A deterministic HTTP Ed25519/RFC 9421/RFC 9530 request vector and negative covered-component mutation checks now exist in [crypto-vectors-v1.json](../../tests/protocol/fixtures/crypto-vectors-v1.json). The vector verifier reproduces the signature from a TEST-ONLY seed. This is a fixed Draft example, not a complete RFC 9421 implementation or a ratified operation-wide covered-component profile.

Required closure: fully model signed responses and every HTTP operation in OpenAPI; freeze exact covered components and key distribution/rotation/overlap/revocation and timestamp/nonce bounds; add independent implementation vectors and replay-store tests.

### P0-02 — WSS authentication transcript baseline approved; exact transcript and vectors remain open

A separate WSS handshake JSON Schema now defines challenge, proof-of-possession, session establishment, acknowledgement and supersession envelopes. The narrative proposes Ed25519 over a domain-separated RFC 8785 JCS transcript, with 32-byte server/client nonces and a single-use 30-second challenge. The algorithm/canonicalization family is approved in [D-04 Cryptographic Profile Decision](./D04-CRYPTOGRAPHIC-PROFILE-DECISION.md): Ed25519 over a domain-separated RFC 8785 JCS transcript. Exact transcript field schema, cross-language test vectors, TLS audience/authority binding, key-version overlap and full implementation semantics remain open.

A deterministic Ed25519/JCS WSS transcript vector now exists with exact transcript bytes, domain separation and negative mutations of runner_id, audience, authority, challenge_id, protocol version and missing prefix. This is still one Draft transcript example; it does not prove independent cross-language JCS implementations or production challenge lifecycle.

Required closure: freeze the exact Ed25519/JCS transcript fields; add at least two independent language implementations, nonce/challenge replay tests, key-version overlap/revocation behavior and handshake error responses.

### P0-03 — WSS strict payload schemas and positive/negative branch fixtures are validated

The Runner WSS schema now defines a dedicated strict payload schema for every post-handshake message type: heartbeat/health, resource telemetry, admission, delivery, credential bootstrap, process lifecycle, release, ACK/error, superseded session and replay request/snapshot. State-changing payloads reject undeclared fields. The session-ack frame is defined only in the pre-application handshake schema to avoid duplicate ownership.

The GitHub Actions workflow validates OpenAPI 3.1/external references and all JSON Schema Draft 2020-12 meta-schemas. Its discriminator checker confirms all 19 application message enum values map to conditional payload branches. A fixture suite then validates one positive sample for each of the 19 Runner message types, 2 Platform request types and 5 SEM event types; for every sample it rejects an unknown top-level field, an unknown payload field and an empty payload. Run #26 passed all these checks on commit `df0c527d89db099901ed6cd9e9a215c2f4fd31c7`.

Schema-shape and basic strict-field fixture closure: **CLOSED**. Remaining: independently verify message direction against the narrative catalogue, add cross-field and D-05 identity invariants, and validate lifecycle evidence semantics rather than only JSON shape.
### P0-04 — SEM→AI-PM event payloads are discriminated; producer/receiver mapping remains open

The Platform–SEM schema now defines five discriminated event payloads: binding-established, delivery-status, process-observed, release-status and infrastructure-uncertain. They carry binding_epoch, Runner identity/key version, delivery/process/release evidence references and explicit uncertainty semantics. The schema deliberately excludes AI-PM Task/Requirement/Approval status fields.

The five event payloads now have valid positive fixtures and reject unknown/missing payload fields in CI run #26. However, the schema definitions are not yet mapped field-by-field to the SEM durable ledger and Runner event evidence, nor to an AI-PM receiver application service.

Required closure: source-map every event field to SEM durable ledger and Runner evidence; verify event sequence/outbox producer; define AI-PM Inbox table/unique key, authorization, transaction and response cursor semantics; add cross-repository fixtures. Ensure infrastructure events cannot express TaskStatus or approval decisions.
### P0-05 — Proposed SEM callback route does not exist in current AI-PM source; bilateral Inbox contract is not implemented

See the detailed [AI-PM Cross-Repository Protocol Review](./D04-AI-PM-CROSS-REPOSITORY-REVIEW.md). Read-only source audit against AI-PM master `d0e72fa6805aebeadf1b282e430deba493072fd6` confirms the proposed `/internal/ai-pm/v1/sem-events` route is not registered in `apps/pm-api/src/routes.rs`. The existing `/api/v1/events` route is a generic project-event ingestion endpoint with a different contract; it must not be repurposed by assumption. AI-PM does have a generic `integration.inbound_event` shared Inbox, but its current ingestion service enqueues `ai_analysis` and lacks SEM-specific execution cursor semantics; it cannot be called unchanged. AI-PM also has a transactional `integration.outbox_event` producer/worker framework, but that is outbound event handling and does not establish an inbound SEM event receiver. AI-PM has a generic `integration.inbound_event` table, but its current `submit_event()` application operation always creates an `integration.job(job_type='ai_analysis')` for each new event, requires project and actor IDs, and has no SEM execution sequence cursor. It is therefore not a SEM receiver as-is. No SEM-specific callback handler, event-ID/body conflict contract, or per-execution contiguous cursor is evidenced. The existing MCP Run tools also remain lease-token-based; they are a separate Harness business channel and cannot substitute for this callback.

Required closure: AI-PM must separately design and implement (only after bilateral ratification and authorization) a dedicated authenticated callback route and a dedicated application operation. Decide whether to extend the generic `integration.inbound_event` safely without creating an `ai_analysis` job or introduce a SEM-specific Inbox/cursor store; either option must provide event_id/body deduplication and per-execution sequence fencing. Freeze single-event vs batch behavior, ACK cursor, 2xx/4xx/5xx retry classification, dead-letter/operator recovery, event ordering/gap handling and atomic Inbox+Run-observation transaction. Do not treat the existing generic `/api/v1/events` endpoint or Outbox worker as this receiver.

### P1-01 — Cross-message identity requirements are not yet uniformly represented

Some WSS branches carry launch_id/containment_id/systemd invocation evidence, but the full D-05 identity tuple is not yet consistently required across start, exit, release-applied and replay records.

Required closure: define shared schemas for execution identity, Runner session identity, Supervisor journal identity, launch/containment identity and process identity; reuse them across all applicable message payloads.

### P1-02 — Version negotiation and unknown-field policy remain prose-level

schema_version is fixed to 1 in the current JSON Schema. The handshake draft mentions supported versions, but supported-version range negotiation, downgrade prevention, additive-field policy and unknown enum behavior are not fully machine-readable.

Required closure: define protocol version and schema version semantics separately; freeze negotiation and compatibility fixtures.

### P1-03 — Operational limits and retry timing remain unbounded

Maximum HTTP body, WSS frame, prompt and bootstrap sizes; compression; heartbeat intervals; resource report TTL; request timeout; retry/backoff; stop grace period defaults; journal retention and queue limits remain open.

Required closure: D-08/D-09 choose bounded values and the schema/OpenAPI expose any negotiated or configured limits.

### P1-04 — Reproducible schema-validation and cryptographic-vector CI is now present; full protocol fixtures remain incomplete

A dedicated GitHub Actions workflow now validates the OpenAPI 3.1 document and external references with Redocly, checks each JSON Schema against the Draft 2020-12 meta-schema, mechanically verifies all 19 post-handshake Runner message types and five SEM event branches, executes deterministic HTTP/WSS Ed25519 vectors and negative mutations, and validates positive plus three classes of negative payload fixtures for all 26 message/event/request examples.

The workflow completed successfully on commit `df0c527d89db099901ed6cd9e9a215c2f4fd31c7` (run #26). This is schema/meta-schema and discriminator-coverage evidence only. It does not execute the 92 acceptance scenarios, validate positive/negative payload fixtures, verify cryptographic test vectors, or test the AI-PM callback receiver.

Required closure: test full RFC 9421 parsing/covered-component canonicalization, signed responses and replay storage; test full RFC 8785 edge cases and independent cross-language WSS verification; add cross-repository receiver contract tests.
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