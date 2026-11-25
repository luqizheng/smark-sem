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

The OpenAPI initially had a placeholder signature scheme. The narrative contract now proposes asymmetric Ed25519 HTTP Message Signatures (RFC 9421) plus Content-Digest (RFC 9530), with request/response signing, method/authority/path/query/body binding, key IDs, timestamp/expiry/nonce replay defense and key rotation. The algorithm-family decision is now approved in [D-04 Cryptographic Profile Decision](./D04-CRYPTOGRAPHIC-PROFILE-DECISION.md): Ed25519 + RFC 9421 + RFC 9530. The OpenAPI does not yet fully model covered components, signed response headers or key identifiers. This remains a blocker for both HTTP and HTTPS; HTTPS is optional in V1 and therefore cannot be the sole integrity/authentication mechanism.

A deterministic HTTP Ed25519/RFC 9421/RFC 9530 request vector and negative covered-component mutation checks now exist in [crypto-vectors-v1.json](../../tests/protocol/fixtures/crypto-vectors-v1.json). The verifier reproduces the signature from a TEST-ONLY seed. The official RFC 9421 Appendix B.2.6 Ed25519 vector is also verified by independent Python and Node implementations. These vectors do not constitute a complete RFC 9421 implementation or ratify an operation-wide covered-component profile.

Required closure: fully model signed responses and every HTTP operation in OpenAPI; freeze exact covered components and key distribution/rotation/overlap/revocation and timestamp/nonce bounds; add independent implementation vectors and replay-store tests.

### P0-02 — WSS authentication transcript baseline approved; exact transcript and vectors remain open

A separate WSS handshake JSON Schema now defines challenge, proof-of-possession, session establishment, acknowledgement and supersession envelopes. The narrative proposes Ed25519 over a domain-separated RFC 8785 JCS transcript, with 32-byte server/client nonces and a single-use 30-second challenge. The algorithm/canonicalization family is approved in [D-04 Cryptographic Profile Decision](./D04-CRYPTOGRAPHIC-PROFILE-DECISION.md): Ed25519 over a domain-separated RFC 8785 JCS transcript. Exact transcript field schema, cross-language test vectors, TLS audience/authority binding, key-version overlap and full implementation semantics remain open.

A deterministic Ed25519/JCS WSS transcript vector now exists with exact transcript bytes, domain separation and negative mutations of runner_id, audience, authority, challenge_id, protocol version and missing prefix. Python and Node independently serialize, verify and reproduce the fixed transcript signature. This proves cross-language agreement for the fixture's ASCII/integer subset only; it does not prove all RFC 8785 edge cases or production challenge lifecycle.

Required closure: freeze the exact Ed25519/JCS transcript fields; expand cross-language JCS tests to RFC 8785 string/number/UTF-16 ordering edge cases; add nonce/challenge replay tests, key-version overlap/revocation behavior and handshake error responses.

### P0-03 — WSS strict payload schemas and positive/negative branch fixtures are validated

The Runner WSS schema now defines a dedicated strict payload schema for every post-handshake message type: heartbeat/health, resource telemetry, admission, delivery, credential bootstrap, process lifecycle, release, ACK/error, superseded session and replay request/snapshot. State-changing payloads reject undeclared fields. The session-ack frame is defined only in the pre-application handshake schema to avoid duplicate ownership.

The GitHub Actions workflow validates OpenAPI 3.1/external references and all JSON Schema Draft 2020-12 meta-schemas. Its discriminator checker confirms all 19 application message enum values map to conditional payload branches. A fixture suite validates one positive sample for each of the 19 Runner message types, 2 Platform request types and 5 SEM event types; for every sample it rejects an unknown top-level field, an unknown payload field and an empty payload. The full current workflow, including these fixtures and cross-language crypto checks, passed in run #48 on commit `067a40e55ecbc0a25fa92ff0d04e32ea63d1642e`.

Schema-shape and basic strict-field fixture closure: **CLOSED**. Remaining: independently verify message direction against the narrative catalogue, add cross-field and D-05 identity invariants, and validate lifecycle evidence semantics rather than only JSON shape.
### P0-04 — SEM→AI-PM event payloads are discriminated; producer/receiver mapping remains open

The Platform–SEM schema now defines five discriminated event payloads: binding-established, delivery-status, process-observed, release-status and infrastructure-uncertain. They carry binding_epoch, Runner identity/key version, delivery/process/release evidence references and explicit uncertainty semantics. The schema deliberately excludes AI-PM Task/Requirement/Approval status fields.

The five event payloads now have valid positive fixtures and reject unknown/missing payload fields in CI run #48. However, the schema definitions are not yet mapped field-by-field to the SEM durable ledger and Runner event evidence, nor to an AI-PM receiver application service.

Required closure: source-map every event field to SEM durable ledger and Runner evidence; verify event sequence/outbox producer; define AI-PM Inbox table/unique key, authorization, transaction and response cursor semantics; add cross-repository fixtures. Ensure infrastructure events cannot express TaskStatus or approval decisions.
### P0-05 — Proposed SEM callback route does not exist in current AI-PM source; bilateral Inbox contract is not implemented

See the detailed [AI-PM Cross-Repository Protocol Review](./D04-AI-PM-CROSS-REPOSITORY-REVIEW.md). Read-only source audit against AI-PM master `d0e72fa6805aebeadf1b282e430deba493072fd6` confirms the proposed `/internal/ai-pm/v1/sem-events` route is not registered in `apps/pm-api/src/routes.rs`. The existing `/api/v1/events` route is a generic project-event ingestion endpoint and must not be repurposed. AI-PM does have a generic `integration.inbound_event` shared Inbox, but the current `submit_event()` operation always creates an `integration.job(job_type='ai_analysis')`, requires project/actor IDs and has no SEM execution cursor; it cannot be called unchanged. No SEM-specific callback handler, event-ID/body conflict contract or per-execution contiguous cursor exists in the pinned source. Existing MCP Run tools are a separate lease-token-based Harness business channel and cannot substitute for the infrastructure callback.

Required closure: complete bilateral review of the [AI-PM callback/Inbox design proposal](https://github.com/luqizheng/ai-pm/blob/docs/sem-02e-architecture-convergence/docs/architecture/server-execution-management/ai-pm-sem-callback-inbox-design-draft.md), ratify the recommended shared-Inbox application port or dedicated Inbox fallback, and freeze service authentication, event_id/body deduplication, per-execution cursor, transactional Run-observation and retry/ACK contract. Implementation still requires separate user authorization.

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

The workflow later completed successfully on PR #3 HEAD `068d44f3742b1381d059f9435f26c34137c0cebb` (run #77). That run validates OpenAPI 3.1/external references, JSON Schema meta-schemas and branch coverage, deterministic crypto vectors, positive/negative payload fixtures and the independent Node JCS/Ed25519 check. The current bilateral acceptance matrix contains 104 scenarios, but run #77 does **not** execute those end-to-end scenarios, a live RFC 9421 verifier/replay store, full RFC 8785 edge cases, PostgreSQL callback transactions, the AI-PM callback receiver, or Runner process lifecycle behavior. Do not describe fixture/validator CI as end-to-end protocol conformance.

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

## 5.1 Follow-up: signed response and conditional GET hardening — 2026-11-25

A focused addendum was added after reviewing the OpenAPI response surface:

- [D-04 HTTP Signed Response and Conditional GET Addendum](./D04-HTTP-SIGNED-RESPONSE-AND-CONDITIONAL-GET-ADDENDUM.md) now defines a proposed response coverage matrix for all four HTTP operations and explicitly requires signed success, error and callback-ACK responses.
- The OpenAPI GET 304 response now declares required ETag, Content-Digest, Signature-Input, Signature and X-SEM-Request-Id headers; it states no message content and the empty-content digest rule.
- D04-H52..H62 were added to the acceptance matrix for signed success/errors, correlation mismatch, missing signatures, digest mismatch, 304 ETag/no-body behavior, response replay and revoked keys.

This is a Draft-level completeness improvement only. The exact RFC 9421 component identifiers/canonical signature bases, response nonce replay scope, freshness bounds, key lifecycle, proxy/HTTP-version behavior, error correlation policy, independent response vectors and live verifier/replay-store tests remain open. Therefore **P0-01 remains OPEN / CHANGES REQUIRED**. The new acceptance cases are specifications, not executed tests.


## 5.2 Follow-up: full JCS source-level conformance review — 2026-11-25

Review of `scripts/validate_sem_crypto_vectors.py` confirms the current Python WSS serializer uses `json.dumps(sort_keys=True, separators=(",", ":"))`. The checked-in fixture is intentionally ASCII-only with integer values; for that restricted fixture the bytes match, but Python code-point key ordering is not RFC 8785 UTF-16 code-unit ordering. Therefore this validator is a fixed-fixture smoke test, not a general JCS implementation. The Node CI check likewise only proves the fixed fixture subset in the current evidence.

Added [D-04 RFC 8785 Full JCS Conformance Addendum](./D04-RFC8785-FULL-JCS-CONFORMANCE-ADDENDUM.md) and D04-W52..W63 cases covering UTF-16 ordering, escaping, number formatting, negative zero, non-finite values, duplicate object members, invalid surrogates, nested structures, challenge/proof binding, replay, expiry and downgrade rejection.

This is a review/specification correction. No validator implementation was changed and these new cases have not been executed. P0-02 remains **OPEN / CHANGES REQUIRED** until independent RFC 8785 implementations produce matching reference bytes and handshake lifecycle tests prove no session is created on rejection.


## 5.3 Follow-up: cross-protocol process-exit and uncertainty invariants — 2026-11-25

A further source-to-schema comparison found two contract gaps:

1. Runner WSS `harness.process_exited.payload.exit_status` originally represented only `code` and `unknown`, while the Platform event schema already represented exactly one of `exit_code` or `exit_signal`. Signal-terminated processes therefore had no lossless Runner wire representation. The Runner schema now adds a tagged `signal` variant. The protocol catalogue defines lossless mapping: code → `exit_code`; signal → `exit_signal`; unknown → neither numeric field. Unknown with a numeric value is rejected.
2. `InfrastructureUncertainPayload` declared `reservation_retained: true` as a const property but did not require the property, so omission passed JSON Schema. It is now required. The lifecycle meaning is that the durable capacity reservation remains held while the execution/process state is uncertain.

The Platform process observation schema now rejects numeric exit fields when `observation=exit_status_unknown`. Fixtures add a signal-terminated Runner message, an exited Platform event with `exit_signal`, and an unknown-status event with exact containment-empty evidence but no numeric status. The validator adds negative checks for contradictory unknown status and missing reservation retention. Acceptance IDs D04-H63..H67 record these requirements.

This is a Draft contract/fixture hardening change. The latest commit at the time of this review update has not yet produced a CI run. It does not prove the production Runner Supervisor emits signal termination correctly, SEM maps it losslessly, or AI-PM persists the observation. P0-04 remains OPEN until producer/receiver semantic mapping and bilateral runtime tests are complete.


## 5.4 Follow-up: handshake/application frame ownership overlap — 2026-11-25

A schema-level ownership defect was found: `runner.session.superseded` was declared both in the pre-application handshake schema and the post-handshake Runner application schema. The protocol narrative says the old authenticated connection receives this frame after a newer session wins, so it is a post-handshake application frame. The duplicate ownership made the frame phase ambiguous and contradicted the validator's stated goal of keeping handshake and application frames separate.

Corrected the Draft:
- Removed `SessionSuperseded` from the handshake schema.
- Kept `runner.session.superseded` only in the post-handshake application schema.
- Strengthened contract validation to require the handshake and application message-type sets to be disjoint, while requiring `runner.session.ack` handshake-only and `runner.session.superseded` application-only.
- Added D04-W64 to the acceptance matrix and clarified the phase in the WSS protocol catalogue.

This is a schema/validator correction. The latest commit has not yet been validated by CI at the time of this note. P0/P1 disposition is not changed until CI passes and the live WSS session-supersession behavior is tested.


## 5.5 Follow-up: RFC 9421 response-derived component correction — 2026-11-25

A standards-level review of the signed-response addendum found that its proposed response signature base listed bare `@authority`. RFC 9421 §2.2 defines `@authority` as the authority of a request target; when signing a response, request-derived components must use the `req` parameter (RFC 9421 §2.4). A bare response-derived `@authority` cannot be resolved as proposed and would make the profile invalid/non-interoperable.

Corrected the Draft response profile:
- Response-derived components: `@status`, response `content-digest`, and the response correlation header.
- Request-derived components: `@method;req`, `@authority;req`, `@path;req`, and `content-digest;req`.
- Conditional GET additionally covers request `if-none-match;req` and response `etag`.
- Updated D04-SEC-01 wording to use the same distinction.

Reference: [RFC 9421 §§2.2 and 2.4](https://www.rfc-editor.org/rfc/rfc9421.html).

This corrects a concrete standards mismatch in the proposed profile. Exact serialized Signature-Input examples, verifier request-context association, canonical vectors, and runtime interoperability remain open. P0-01 remains **OPEN / CHANGES REQUIRED**.


### CI evidence update for §5.4 — 2026-11-25

The schema/validator correction described in §5.4 was validated by SEM Protocol Contract Validation run #127 on commit `0ac34a194779260ea241e7e7c5d6960f8c3d3d45`: **success**. The run completed OpenAPI validation, JSON Schema meta-schema/message coverage, cryptographic vectors, positive/negative payload fixtures, and independent Node JCS/Ed25519 checks. A subsequent documentation-only fixture-count refresh does not alter those executable files. This remains contract/fixture CI, not live WSS session-supersession interoperability.


## 5.6 Follow-up: authenticated and pre-authentication error response boundary — 2026-11-25

The Draft previously distinguished authenticated GET 404 from pre-authentication failures but did not define the response-signature requirement for every error class. This left an ambiguity that could produce unsigned application errors or cause an API to echo untrusted request/event identifiers.

The candidate contract now defines:
- Verify raw-body digest and RFC 9421 request signature before JSON parsing.
- After successful authentication, sign every application response, including 400/404/409/412/422/429/500, and correlate only to the authenticated Idempotency-Key header (\`X-SEM-Request-Id\` or \`X-SEM-Event-Id\` by direction).
- Reject a callback whose authenticated Idempotency-Key does not equal its envelope event_id; a signed error correlates only to the authenticated header and does not echo the body value.
- Before authentication succeeds (invalid signature/key, stale or replayed nonce, early body-size rejection), return only a generic unsigned response without signature/correlation headers or request/event identifiers in its body.
- Application-level 429 is authenticated and signed with Retry-After. Edge/WAF rejection before authentication is outside the protocol and must not reflect identifiers.
- If an authenticated response cannot be signed, fail closed by terminating the response/connection; never downgrade to an unsigned correlated response.

OpenAPI now separates direction-specific signed errors, signed rate-limit errors and the restricted pre-authentication error envelope. D04-H78..H85 record the new cases. The AI-PM PR #9 bilateral addendum and Inbox design have been updated to the same callback rule.

This closes the Draft-level ambiguity only. It does not close P0-01: deterministic signed-error vectors, OpenAPI validator CI on the updated branch, actual HTTP middleware ordering, nonce replay storage, reverse-proxy behavior and bilateral runtime interoperability remain unproven. Disposition remains **CHANGES REQUIRED**.


## 5.7 Follow-up: signed 404 and pre-authentication error fixtures — 2026-11-25

The Draft error boundary now has deterministic fixtures for both 404 response directions:
- Platform→SEM authenticated GET unknown-execution 404, with signed `X-SEM-Request-Id`.
- SEM→AI-PM authenticated callback unknown/wrong-scope 404, with signed `X-SEM-Event-Id`.

The Python and Node validators independently recompute exact request/response Content-Digest values, reconstruct RFC 9421 response signature bases and verify Ed25519 signatures. Both validators also exercise request-context mutations (method, authority, path, request digest) and direction-specific correlation mutation.

Unsigned pre-authentication 401 and early-413 fixtures were added. Python/Node assert no signature/correlation headers and a minimal body structurally excluding message_id, in_reply_to, request_id and event_id. Acceptance cases D04-H86..H88 record this coverage.

This is deterministic fixture evidence only. It does not prove live authentication-before-JSON-parse ordering, callback database non-enumeration behavior, edge body-limit handling, nonce replay persistence or real HTTP server/client association. Signed 400/412/422/429/500 vectors remain open. P0-01 remains **OPEN / CHANGES REQUIRED**.


### CI evidence update for §5.7 — 2026-11-25

The signed Platform GET 404, signed SEM callback 404 and unsigned pre-authentication 401/early-413 fixture changes passed SEM Protocol Contract Validation run #413 on commit `dfe00314c65b3899c65da495e8f866678d2b2739`. All ten steps succeeded, including OpenAPI/external references, JSON Schema, cryptographic vectors, payload fixtures and independent Node JCS/Ed25519 verification. This remains deterministic contract CI; live HTTP middleware and replay behavior remain open.


## 5.8 Follow-up: durable Runner ACK cursor must be mandatory — 2026-11-25

A focused cross-check of the D-04 WSS narrative against the application JSON Schema found that the schema required acknowledged_journal_id and acknowledged_event_sequence to appear together only when either field was present. It still accepted a protocol.ack with disposition=durably_recorded and neither cursor field. That contradicted the WSS contract: a durable ACK is the exact retention/cleanup gate for one Runner journal position and MUST echo both cursor fields.

Corrected on the D-05 follow-up branch:
- The ProtocolAck schema now requires both cursor fields whenever disposition=durably_recorded.
- The payload-fixture validator now rejects a durable ACK with both cursor fields absent, while retaining acceptance of a non-durable accepted ACK without a journal cursor.
- Existing negative cases continue to reject either half of an incomplete cursor pair.

This closes the identified schema/fixture gap only. It does not prove SEM persists the complete event envelope before ACK, that Runner gates evidence cleanup on the exact cursor, or that replay/deduplication works under a live WSS session. Those remain integration obligations under D-05 and the Linux systemd failure-injection plan.

### Remaining D-04 cross-audit items confirmed

- **Direction catalogue consistency is now mechanically checked:** `validate_sem_contracts.py` parses the normative WSS direction table and requires an exact, duplicate-free mapping for every application message type. The shared bidirectional JSON Schema still cannot reject a wrong-peer sender by itself; SEM/Runner receive-path enforcement and live wrong-direction rejection tests remain open.
- **Cross-message identity remains incomplete:** execution/binding/launch/containment/boot/Supervisor identity is not uniformly required across every lifecycle, release and replay branch; retain P1-01.
- **Version negotiation and operational bounds remain prose-level:** retain P1-02/P1-03.
- **Platform↔SEM HTTP authentication/replay and AI-PM callback Inbox remain P0 blockers:** schema/fixture CI does not close live middleware, nonce replay, durable Inbox, producer/receiver mapping or bilateral runtime behavior.
- **No process lifecycle P0 is closed by this ACK correction:** P0-02/P0-03/P0-04 still require executable Linux systemd >=250 failure-injection evidence.

### CI evidence update for §5.8 — 2026-11-25

SEM Protocol Contract Validation run #502 (`45618307319`) passed all 10 steps on PR #5 head `65051e8d75a4fa0833d4755a48a32209195aca97`, including the new durable-ACK cursor rule, negative fixtures and WSS direction-catalogue coverage. This is contract/schema/fixture CI only; it does not prove live WSS sender enforcement, HTTP middleware/replay, AI-PM Inbox transactions or Linux process lifecycle behavior.


## 5.9 Follow-up: release-applied disposition must agree with exit evidence — 2026-11-25

A D-05/WSS cross-check found that ReleaseApplied accepted process_stopped or already_exited without process_exit_evidence_id, and also allowed stop_fenced/stale_rejected/local_uncertain to carry a positive exit-evidence reference. This was weaker than the D-05 positive-exit proof contract and could let a wire-valid release disposition be misinterpreted as process termination.

Corrected on PR #5:
- The Runner WSS schema now requires process_exit_evidence_id for process_stopped and already_exited.
- The schema rejects process_exit_evidence_id for stop_fenced, stale_rejected and local_uncertain.
- The WSS narrative now defines each disposition and requires SEM to cross-check the referenced harness.process_exited evidence against the exact execution/binding/launch/containment/boot identity.
- Added D04-W46/W47 and positive/negative fixture assertions.

This is schema and Draft semantic alignment only. The schema cannot prove that the referenced event exists or that the identity tuple matches; SEM receiver logic and live event-order/replay tests must enforce that. D-05 P0-02/P0-03/P0-04 remain open pending executable Linux systemd >=250 failure-injection evidence.
