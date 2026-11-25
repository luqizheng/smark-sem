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
3. The signature base binds response-derived `@status`, `content-digest`, and the operation-specific response correlation header. It also binds the originating request context using RFC 9421 request-targeted component identifiers `@method;req`, `@authority;req`, `@path;req`, and `content-digest;req;sf`. A bare `@authority` is NOT valid as a response-derived component: RFC 9421 defines `@authority` for a request target, and a response signature must use the `req` parameter to obtain it from the associated request. `content-type` is covered only when present on the response; a verifier must not synthesize it when absent.
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
- The response signature covers the request's `If-None-Match` using `if-none-match;req`, and the response's `ETag` as a response field, in addition to the common response/request component set above.
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

- Exact operation-specific RFC 9421 covered-component list and canonical signature-base examples, including `;req` component identifiers and the associated-request context available to the verifier.
- Whether response nonce replay state is scoped by peer key, local verifier, operation, and/or request identity; retention and concurrency semantics.
- Exact freshness/skew bounds and how clients handle clock disagreement.
- Key discovery/trust configuration, key version overlap, revocation propagation and emergency rotation.
- Exact behavior for redirects, proxies, authority normalization, HTTP/2/HTTP/1.1, duplicate headers and intermediary transformations.
- Error response correlation when the request cannot be authenticated or parsed; define a safe authenticated error policy without leaking attacker-controlled identity.
- Independent Python/Node/Rust vectors for every response class, including empty-content 304 and signed errors.
- Runtime replay-store and request/response integration tests in both repositories.

## 7. Review conclusion

The OpenAPI 304 response now has explicit Draft headers and no-content semantics. That is a documentation improvement, not a P0 closure. D-04 P0-01 remains **OPEN / CHANGES REQUIRED** until all response classes are fully specified, independently interoperable, and tested with replay protection. D-04 ratification and implementation authorization remain separate decisions.

## 8. Frozen candidate serialization profile (RFC 9421; still not ratified)

This section removes ambiguity from the *candidate* response profile. It is normative within this draft only. It does not claim that either repository has an interoperable runtime implementation.

### 8.1 Algorithm and label

- The only permitted algorithm identifier in this profile is `ed25519`, as registered by RFC 9421 §3.3.6. The HTTP Signature Algorithms registry identifies this value as EdDSA over edwards25519.
- The only signature label is `sig1`. A message with a missing, duplicate, or additional signature label is rejected in V1; multi-signature negotiation is out of scope.
- The signature metadata parameter order is fixed as: `created`, `expires`, `nonce`, `keyid`, `alg`. The component order below is fixed and MUST NOT be reordered.
- `created` and `expires` are integer Unix seconds. `nonce` is a fresh cryptographically random value for each response signature. `keyid` identifies one immutable Ed25519 public-key version. `alg` is exactly `"ed25519"`.

### 8.2 Body-bearing response Signature-Input

For all non-304 responses, including structured errors and empty-body statuses, the candidate covered-component order is:

1. `"@status"`
2. `"content-digest";sf`
3. Exactly one response correlation field: `"x-sem-request-id"` for Platform→SEM responses, or `"x-sem-event-id"` for SEM→AI-PM callback responses.
4. `"@method";req`
5. `"@authority";req`
6. `"@path";req`
7. `"content-digest";req;sf`

The Structured Fields serialization template is therefore exactly one of:

```http
Signature-Input: sig1=("@status" "content-digest";sf "x-sem-request-id" "@method";req "@authority";req "@path";req "content-digest";sf;req);created=<unix-seconds>;expires=<unix-seconds>;nonce="<base64url-random>";keyid="<immutable-key-id>";alg="ed25519"
```

or:

```http
Signature-Input: sig1=("@status" "content-digest";sf "x-sem-event-id" "@method";req "@authority";req "@path";req "content-digest";sf;req);created=<unix-seconds>;expires=<unix-seconds>;nonce="<base64url-random>";keyid="<immutable-key-id>";alg="ed25519"
```

These are Structured Fields serialization templates, not literal valid header values until placeholders are replaced. There is no whitespace around separators. Component identifiers and signature parameters are serialized using RFC 9421 / RFC 8941 rules; implementations MUST NOT hand-roll ad-hoc quoting or parse the field with comma/semicolon splitting.

For a response with a representation body, `content-type` is additionally required by the operation contract and MUST be placed immediately after the direction-specific correlation field (the fourth component), before the request-derived components. It is not optional within a given operation response class. For a response class whose contract has no content type, it is omitted. This eliminates the prior ambiguous instruction to sign `content-type` only when present.

### 8.3 Conditional 304 Signature-Input

A 304 has no message content and uses this exact component order:

1. `"@status"`
2. `"content-digest";sf`
3. `"x-sem-request-id"`
4. `"etag"`
5. `"@method";req`
6. `"@authority";req`
7. `"@path";req`
8. `"content-digest";req;sf`
9. `"if-none-match";req`

Template:

```http
Signature-Input: sig1=("@status" "content-digest";sf "x-sem-request-id" "etag" "@method";req "@authority";req "@path";req "content-digest";sf;req "if-none-match";req);created=<unix-seconds>;expires=<unix-seconds>;nonce="<base64url-random>";keyid="<immutable-key-id>";alg="ed25519"
```

The response `Content-Digest` for a 304 MUST be SHA-256 over zero content octets:
`sha-256=:47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=:`.
The request-side `content-digest;req;sf` is the digest of the actual request content bytes (zero octets for this GET profile). The client MUST verify that the 304 is valid for the associated request's `If-None-Match` condition using HTTP conditional request comparison semantics (including weak comparison for `If-None-Match`). The signed response ETag identifies the selected current representation validator; the protocol MUST NOT replace HTTP's list, wildcard, or weak-comparison semantics with raw string equality.

### 8.4 Signature base construction and request-context association

The signature base is generated by the RFC 9421 algorithm, not by concatenating raw HTTP headers. In particular:

- The response signer MUST sign using the exact request object that caused the response. The request method, authority, path, request Content-Digest, and (for 304) If-None-Match values MUST be obtained from that request object before it is discarded.
- The response verifier MUST retain the exact outbound request context until the corresponding response is verified. It MUST NOT reconstruct request context from response headers, reverse-proxy headers, an untrusted correlation value, or a later retry.
- Each in-flight request has a locally generated, unpredictable request-context identifier. The HTTP client binds the response to the transport request instance and then checks the signed correlation field against the expected message_id/event_id associated with that instance. Correlation alone is not a substitute for transport-level request association.
- Redirects are disabled for these authenticated endpoints. A redirect is rejected before accepting any response signature. A retry is a new HTTP request instance and receives a new request-context identifier; it must not inherit the prior response nonce or request association.
- The server-side signer must not trust externally supplied forwarding headers to derive `@authority` or `@path`. The canonical request target used by the HTTP server/router and the request context passed to the signer must agree. Deployments with a reverse proxy must define and test one trusted normalization boundary; otherwise that topology is unsupported.
- The verifier validates `@status`, response fields and request-derived components against the associated response/request pair. A valid signature over a different request is rejected even if the body and correlation identifier happen to match.

This association is a runtime API contract: implementations need a request-context object (or equivalent) passed from request construction through response verification. A response-only verification API that accepts just status, headers and body is insufficient.

### 8.5 Response header and field processing rules

- There MUST be exactly one `Signature-Input`, `Signature`, `Content-Digest`, and operation-specific correlation field. Duplicate instances, combined ambiguous values, malformed Structured Fields, unknown signature labels, and unsupported component identifiers are rejected.
- The `Signature` dictionary MUST contain exactly `sig1`; its value is the RFC 9421 byte-sequence serialization of the 64-octet Ed25519 signature.
- The signed response correlation field MUST be a single canonical protocol identifier and MUST equal the expected request message_id or callback event_id. It is not copied from an untrusted client-provided header.
- RFC 9530 `Content-Digest` is a Structured Field Dictionary. Every request-side and response-side Content-Digest component MUST use RFC 9421's `sf` component parameter so optional Structured Field whitespace is canonicalized; request-derived digest uses the component identifier parameter order `;req;sf`. The digest field's Structured Field type is known to both signer and verifier.
- Body bytes are hashed before JSON decoding, decompression, normalization, or application-level parsing. The deployment must disable intermediary transformations of signed response content; if content coding is used, the protocol must specify exactly which representation bytes are signed. V1 candidate profile therefore requires identity content coding for these endpoints.
- `Content-Digest` is required even when the response content is empty. A no-content response uses the SHA-256 empty-content digest above.
- Response signature verification, digest verification, key-status validation, freshness checks, nonce replay checks, request association, and correlation checks all complete before status/body is exposed as a typed application result.

### 8.6 Deterministic signature-base fixtures required

The acceptance suite MUST publish literal byte-for-byte fixtures containing the complete request, response, Signature-Input, Signature, and expected signature-base bytes. At minimum, publish separate fixtures for:

- Platform→SEM 202 with JSON body and X-SEM-Request-Id.
- Platform→SEM signed 409 structured error.
- SEM→AI-PM callback 200 ACK with X-SEM-Event-Id.
- Platform→SEM 304 with empty response content, ETag and If-None-Match.
- A bodyless non-304 response, proving the empty response digest path.
- A request-association negative vector where the response is replayed against a different method, authority, path, request digest, or conditional validator.

Each positive fixture must be generated independently by at least two implementations and cross-verified by a third implementation or a separately implemented verifier. Python, Node and Rust are candidate languages; library names and versions must be pinned in the fixture manifest after actual compatibility tests, not assumed in advance. Negative vectors must mutate one component at a time and prove verification failure.

### 8.7 Freshness and replay are separate acceptance gates

The exact freshness window and replay retention remain an explicit D-09/D-04 policy decision. Until ratified, no numeric TTL is implied by this draft. Irrespective of the chosen values:

- `created` and `expires` MUST both be present and satisfy `created <= now + allowed_clock_skew`, `expires >= now - allowed_clock_skew`, and `expires > created`.
- The maximum permitted lifetime `expires - created`, allowed clock skew, and maximum nonce-store retention MUST be explicit deployment constants in the ratified profile.
- Nonce uniqueness is enforced by the verifier's durable replay store within a documented scope. A nonce is consumed atomically with successful authentication; concurrent duplicate verification cannot both succeed.
- Replay-store outage or uncertainty fails closed. A response is never accepted merely because its signature and timestamp are valid.
- The request-context identifier and response correlation are checked in addition to nonce uniqueness; neither replaces the other.

### 8.8 Revised disposition

This section freezes a candidate serialization shape and runtime request-association contract, but does not close P0-01. Remaining blockers include executable cross-language fixtures, actual client/server API integration, duplicate-header behavior through supported HTTP stacks, proxy/authority normalization proof, nonce-store concurrency/crash tests, and a separately ratified freshness/replay policy. D-04 remains **CHANGES REQUIRED / NOT READY FOR IMPLEMENTATION**.


## 9. Deterministic signed-response vectors (2026-11-25; partial)

Added TEST-ONLY response vectors to [crypto-vectors-v1.json](../../tests/protocol/fixtures/crypto-vectors-v1.json):

- `http_response`: a signed 202 JSON acceptance response. Its signature base covers response status, response Content-Digest, X-SEM-Request-Id, Content-Type, and the exact originating request method/authority/path/Content-Digest via RFC 9421 `;req` components.
- `http_304`: a signed bodyless 304. Its signature base covers response status, the SHA-256 empty-content digest, X-SEM-Request-Id, ETag, and the associated GET request method/authority/path/Content-Digest/If-None-Match via `;req` components.

The fixture stores exact request bytes and response bytes. Python and Node validators independently recompute both request and response Content-Digest values, reconstruct the signature base from the request/response fields, verify Ed25519 signatures, and reproduce signatures from TEST-ONLY seeds. This exercises the candidate response serialization and the empty-content 304 path without relying on a precomputed signature-base string alone.

The Python and Node response-vector verification steps passed in CI run #171 on commit `534b74498c0f0b33889a743b2b55d915064f8b4b`. This is a deterministic fixture check, not a live HTTP-stack test.

This does **not** prove an RFC 9421 HTTP stack's live request-context association, duplicate-header handling, proxy behavior, redirect rejection, signed 4xx/5xx behavior, response nonce replay storage, or production client/server interoperability. The vectors are primitive/signature-base fixtures, not a complete RFC 9421 parser or runtime verifier. D04-H52 and D04-H57 have deterministic fixture coverage only; the rest of H52–H62 remain open, and P0-01 remains **OPEN / CHANGES REQUIRED** until live bilateral tests and replay-policy closure.
