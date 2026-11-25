# D-04 HTTP Signed Response and Conditional GET Contract Addendum

- Date: 2026-11-25
- Status: **DRAFT / REVIEW ONLY / NOT RATIFIED**
- Parent decision: D-04 Cryptographic Profile Decision
- Parent contract: Platform–SEM OpenAPI
- Disposition: This addendum makes response-signing gaps explicit and proposes a consistent response model. It does not close P0-01 or authorize implementation.

## 1. Finding

The cryptographic primitive decision approves Ed25519 + RFC 9421 + RFC 9530. It does not yet freeze the operation-wide response signature profile. The current OpenAPI security declaration describes request authentication but does not define response authentication by itself. A prose statement that responses are signed is insufficient for independent implementations.

All response classes must be authenticated, including successful responses, conditional responses, and structured error responses. HTTPS cannot replace this requirement because restricted private-network HTTP is an allowed V1 transport.

## 2. Proposed response profile (not ratified)

For every HTTP response sent by SEM or AI-PM:

1. Signature-Input and Signature carry an RFC 9421 Ed25519 signature.
2. Content-Digest is an RFC 9530 digest over the exact response message content bytes. For a response with no content (including 304), compute the digest over the empty byte sequence.
3. The signature base binds @status, @authority, content-digest, and the operation-specific correlation component below. content-type is covered only when present; a verifier must not synthesize it when absent.
4. created, expires, nonce, keyid, and alg are mandatory signature parameters. Exact freshness bounds, nonce retention, and key rotation/overlap remain open D-04/D-09 decisions.
5. Correlation is mandatory and direction-specific:
   - Platform→SEM request receives a SEM response echoing X-SEM-Request-Id equal to the authenticated request's message_id.
   - SEM→AI-PM callback receives an AI-PM response echoing X-SEM-Event-Id equal to the authenticated callback's event_id.
6. The receiver verifies signature, digest, key status, freshness, correlation and replay protection before trusting any status/body. Error responses are signed too.
7. An absent/invalid signature, digest, correlation, or trust decision is an authentication failure, never a typed business/protocol outcome.

This proposed baseline is deliberately explicit about the empty-content digest and correlation, but still requires independent RFC 9421 implementation vectors and replay-store tests before ratification.

## 3. Operation/response coverage matrix

| Operation | Response classes | Correlation header | Additional response semantics |
|---|---|---|---|
| submitExecutionRequest | 202, 400, 401, 409, 413, 422, 429, 500 | X-SEM-Request-Id | Every response signed; 202 body binds message_id/request_id/execution_id and accepted/duplicate disposition |
| getExecutionInfrastructureState | 200, 304, 401, 404, 500 | X-SEM-Request-Id | 200 carries ETag and signed snapshot; 304 has no content, echoes ETag, carries empty-content digest and signature; 404/error body signed |
| requestExecutionRelease | 202, 400, 401, 404, 409, 412, 422, 500 | X-SEM-Request-Id | Every response signed; 412 is an authenticated fencing conflict, not a retryable transport failure |
| receiveSemInfrastructureEvent | 200, 400, 401, 409, 422, 500 | X-SEM-Event-Id | Every response signed; 200 ACK only after Inbox + Run observation + cursor commit; ACK echoes event_id and execution_event_sequence |

The OpenAPI currently contains the operation names/statuses shown above. This matrix does not assert that the callback receiver or transaction exists in AI-PM source.

## 4. Conditional GET 304 contract

The OpenAPI draft now proposes the following behavior for getExecutionInfrastructureState:

- A 304 response MUST have no message content.
- ETag is required and MUST echo the current validator for the selected representation.
- Content-Digest is required and is calculated over zero response-content bytes.
- Signature-Input and Signature are required and use the same signed-response profile as 200.
- X-SEM-Request-Id is required and echoes the authenticated request identity.
- The client must verify the response before returning NotModified; an unsigned or mismatched 304 is an authentication error, not a cache hit.
- A 304 must not carry an execution snapshot body. A body-present 304 is rejected as a protocol violation.
- The ETag is an opaque validator; it is not an authorization token or execution identity.

This resolves the missing OpenAPI header/no-body statement at the Draft-contract level only. The exact RFC 9421 signature base and cross-language vectors remain to be ratified.

## 5. Required acceptance cases

Add these cases to the D-04 executable suite:

| ID | Scenario | Expected result |
|---|---|---|
| D04-H52 | Valid signed 202 response with matching X-SEM-Request-Id | Client trusts acceptance only after signature/digest/correlation verification |
| D04-H53 | Signed structured 4xx/5xx response | Client accepts typed error only after response verification |
| D04-H54 | Missing response Signature or Signature-Input | Client fails closed; no typed result |
| D04-H55 | Response Content-Digest mismatch | Client rejects before decoding/trusting body |
| D04-H56 | Response correlation header does not match request message_id/event_id | Client rejects as response-confusion/replay |
| D04-H57 | Valid 304 with ETag echo, empty-content digest and valid signature | Client returns NotModified only after all checks |
| D04-H58 | 304 missing ETag, signature, digest or correlation header | Client rejects; must not treat as cache hit |
| D04-H59 | 304 contains a response body | Client rejects as protocol violation |
| D04-H60 | 304 ETag differs from requested/current validator | Client rejects or performs unconditional reconciliation; never silently accepts |
| D04-H61 | Replay a previously accepted signed response nonce | Client rejects replay according to the ratified response replay scope |
| D04-H62 | Signed response uses unknown/revoked keyid | Client fails closed |

## 6. Open decisions blocking ratification

- Exact operation-specific RFC 9421 covered-component list and canonical signature-base examples.
- Whether response nonce replay state is scoped by peer key, local verifier, operation, and/or request identity; retention and concurrency semantics.
- Exact freshness/skew bounds and how clients handle clock disagreement.
- Key discovery/trust configuration, key version overlap, revocation propagation and emergency rotation.
- Exact behavior for redirects, proxies, authority normalization, HTTP/2/HTTP/1.1, duplicate headers and intermediary transformations.
- Error response correlation when the request cannot be authenticated or parsed; define a safe authenticated error policy without leaking attacker-controlled identity.
- Independent Python/Node/Rust vectors for every response class, including empty-content 304 and signed errors.
- Runtime replay-store and request/response integration tests in both repositories.

## 7. Review conclusion

The OpenAPI 304 response now has explicit Draft headers and no-content semantics. That is a documentation improvement, not a P0 closure. D-04 P0-01 remains **OPEN / CHANGES REQUIRED** until all response classes are fully specified, independently interoperable, and tested with replay protection. D-04 ratification and implementation authorization remain separate decisions.