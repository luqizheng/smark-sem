# D-04 Cryptographic Profile Decision

- Decision ID: D04-SEC-01
- Decision date: 2026-11-25
- Status: **APPROVED BASELINE — normative algorithm-family decision; wire-level closure still pending**
- Scope: V1 Platform↔SEM HTTP/HTTPS service authentication and Runner↔SEM WSS enrollment/session proof.
- Authority: user-approved architecture decision. This document does not authorize implementation or PR merge.

## 1. Decision

V1 uses Ed25519 public-key cryptography for service and Runner identity proofs. Keys are independent by principal, direction, environment and purpose. No long-lived shared HMAC secret is introduced between AI-PM and SEM.

| Principal / direction | Key owner | Purpose |
|---|---|---|
| AI-PM Platform → SEM | AI-PM | Sign Platform-originated HTTP requests |
| SEM → AI-PM Platform | SEM | Sign SEM callbacks and HTTP responses |
| Runner → SEM | Individual Runner | Prove possession of the enrolled Runner identity key during WSS authentication |
| TLS endpoint | Each service endpoint | TLS server authentication; separate from application signing identity |

The Platform and SEM service keys MUST NOT be reused as Runner identity keys. Runner private keys are generated and retained on their own hosts. Public keys are registered/distributed through an authenticated administrative process. Key IDs are explicit and keys are environment-scoped.

## 2. Platform ↔ SEM HTTP/HTTPS

- Signature format: RFC 9421 HTTP Message Signatures.
- Body integrity: RFC 9530 Content-Digest.
- Algorithm: Ed25519.
- Both requests and responses are signed by the sending service.
- Request signatures bind the HTTP method, authority, path, query, Content-Digest (RFC 9421 `sf` component parameter), content type and applicable message/idempotency headers.
- Response signatures bind response `@status`, response `content-digest;sf`, response content type and the response correlation identifier. Request-target context is bound with RFC 9421 request-derived components (`@method;req`, `@authority;req`, `@path;req`, and `content-digest;req;sf`); a bare response-derived `@authority` is not used. Exact operation-specific coverage remains in the signed-response addendum.
- Signature parameters include created, expires, nonce, keyid and alg.
- Receivers verify signature and digest before parsing or persisting the message, then atomically enforce nonce replay prevention and message/idempotency deduplication.
- Invalid, unknown, expired or revoked keys, stale signatures, replayed nonces, digest mismatch and unsigned requests fail closed.
- HTTP remains restricted to the company private network and provides no confidentiality. HTTPS is optional in V1 and MUST validate enterprise CA or explicitly pinned self-signed trust; certificate verification bypass is forbidden.

RFC references:
- [RFC 9421 — HTTP Message Signatures](https://www.rfc-editor.org/rfc/rfc9421)
- [RFC 9530 — Digest Fields](https://www.rfc-editor.org/rfc/rfc9530)

## 3. Runner ↔ SEM WSS authentication

- Runner identity proof: Ed25519.
- Transcript canonicalization: RFC 8785 JSON Canonicalization Scheme (JCS).
- Signed bytes: the UTF-8 domain-separation prefix `SEM-RUNNER-WSS-AUTH-V1\n` followed by the JCS serialization of the versioned transcript object.
- The transcript binds protocol audience, endpoint authority, runner_id, key_version, challenge_id, server_nonce, client_nonce and selected protocol version.
- Challenge is single-use. Candidate V1 nonce size is 32 cryptographically random bytes per side, encoded base64url without padding; candidate challenge TTL is 30 seconds.
- TLS server authentication is independently mandatory. A valid Runner signature MUST NOT override a failed TLS trust/hostname check.
- Post-handshake WSS application messages are authenticated by the established TLS/WSS session and fenced by connection_id/session_generation. This decision does not require per-message Ed25519 signatures on every WSS frame.

Reference:
- [RFC 8785 — JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785)

## 4. Key separation and lifecycle

1. Use separate keypairs for AI-PM service signing, SEM service signing and each Runner identity.
2. Do not reuse TLS certificate private keys as application signing keys.
3. Do not reuse Harness delegated MCP credentials as any service or Runner key.
4. Key IDs are unique within an environment and identify one immutable public-key version.
5. Rotation supports an explicit overlap window; new signatures use the active key while verifiers accept only configured active/overlap keys.
6. Revocation is explicit and fail-closed. Unknown or revoked key IDs are rejected.
7. Private-key storage, provisioning, rotation cadence, overlap duration, revocation distribution and recovery are D-09 operational decisions.

## 5. Parameters not yet frozen

This decision approves the cryptographic primitives and protocol families, not every wire-level parameter. The following remain open and MUST be completed before D-04 ratification:

- Exact RFC 9421 covered-component lists and canonicalization/test vectors for every HTTP operation and response class.
- Exact HTTP header names and OpenAPI security/header definitions.
- Timestamp skew, signature lifetime, nonce entropy and nonce retention bounds.
- Exact WSS transcript JSON field names/types, domain-separation test vectors and challenge expiry behavior.
- Key provisioning, storage, rotation overlap and revocation propagation.
- Expanded cross-language vectors for RFC 8785 edge cases (malformed/non-canonical inputs, UTF-16 key ordering, number serialization, wrong audience and replay); the fixed ASCII/integer transcript is already verified by Python and Node.
- AI-PM callback route and Inbox transaction/retry contract alignment.

The earlier candidate values (HTTP created tolerance 30 seconds future / 60 seconds old, expiry no later than created + 60 seconds, nonce >=128 bits retained >=10 minutes; WSS 32-byte nonces and 30-second challenge) remain **provisional test starting points**, not normative values.

## 6. Deterministic test-vector baseline (Draft)

A deterministic, TEST-ONLY vector set is maintained at [crypto-vectors-v1.json](../../tests/protocol/fixtures/crypto-vectors-v1.json), with verifier [validate_sem_crypto_vectors.py](../../scripts/validate_sem_crypto_vectors.py). It contains:

- Platform→SEM HTTP request body, RFC 9530 SHA-256 Content-Digest, RFC 9421 signature base and Ed25519 signature.
- Runner→SEM WSS transcript, RFC 8785 JCS bytes, domain-separation prefix and Ed25519 proof.
- Negative mutations for HTTP method, authority, path, content type, idempotency key and digest; WSS runner identity, audience, authority, challenge, protocol version and missing domain prefix.
- The official RFC 9421 Appendix B.2.6 Ed25519 vector is verified by both Python and Node; the fixed WSS JCS transcript/signature is independently serialized, verified and reproduced by Python and Node. The Node verifier now additionally exercises RFC 8785 UTF-16 property ordering (including a supplementary-plane key), recursive object sorting/array-order preservation, Unicode/control escaping, representative Appendix B IEEE-754 number encodings, negative zero, exponent-format boundaries, malformed JSON, lone-surrogate rejection and non-finite-number rejection. The Python verifier still independently checks only the fixed ASCII/integer transcript; the expanded edge vectors are not yet cross-verified by a second language. Duplicate JSON object member detection before object materialization also remains an explicit gap.
- Deterministic TEST-ONLY private seeds to permit exact reproduction. These seeds MUST NOT be used in any deployed environment.

These vectors prove the selected algorithm primitives and the specific Draft serialization examples. They do not ratify the final HTTP covered-component profile, time bounds, nonce retention, full JCS edge-case behavior, key rotation policy or production implementation. Those remain open until broader cross-language edge-case fixtures and the full RFC 9421 verifier behavior are independently tested.

## 7. Acceptance requirements

- A known-good Ed25519 HTTP request and response verify in both AI-PM and SEM implementations.
- Any mutation to a covered component or body fails verification.
- Digest mismatch, missing signature, unknown/revoked key, stale/future signature and replayed nonce fail closed.
- WSS transcript vectors verify identically across at least two independent implementations.
- Wrong runner_id, key_version, audience, endpoint authority, challenge, nonce or protocol version fails authentication.
- Reusing a consumed challenge fails without creating a session.
- TLS trust failure fails before application proof is considered.
- Rotation overlap and revocation tests prove old-key acceptance is bounded and revoked keys fail immediately after the defined propagation contract.

**Implementation gate:** D-04 remains open until all remaining P0 findings are closed, machine-readable contracts and fixtures validate, and the user separately authorizes implementation.
