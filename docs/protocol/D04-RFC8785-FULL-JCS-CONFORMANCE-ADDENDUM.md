# D-04 RFC 8785 Full JCS Conformance Review Addendum

- Date: 2026-11-25
- Status: **DRAFT / REVIEW ONLY / NOT RATIFIED**
- Scope: Runner↔SEM authentication transcript canonicalization.
- Disposition: The current deterministic vector proves only a restricted ASCII/integer subset. P0-02 remains open.

## 1. Source-level finding

The current Python crypto validator serializes the WSS transcript with Python json.dumps(sort_keys=True, separators=(',', ':')). The checked-in fixture intentionally contains only ASCII property names/values and an integer, for which this serialization happens to match the fixture bytes. Python's default key ordering is Unicode code-point ordering, not RFC 8785's UTF-16 code-unit ordering. The validator is therefore not a general JCS implementation and must not be presented as one.

The current Node-side check is described as independent, but the reviewed CI evidence only establishes the fixed ASCII/integer fixture. It does not establish complete RFC 8785 behavior. No claim of full JCS conformance is permitted.

## 2. Required canonicalization rules to test

An implementation must follow RFC 8785, including ECMAScript-compatible JSON primitive serialization and UTF-16 code-unit ordering of object property names. The test suite must cover:

1. UTF-16 property ordering, including BMP and supplementary-plane keys whose Unicode code-point order differs from UTF-16 code-unit order.
2. String escaping: quotation mark, reverse solidus, control characters, and characters that must remain literal UTF-8 rather than being unnecessarily escaped.
3. Number serialization: negative zero, integral values, fractional values, exponent thresholds, large/small magnitudes, and IEEE-754 binary64 rounding behavior.
4. Rejection of non-finite numbers (NaN, +Infinity, -Infinity) before canonicalization.
5. Duplicate object member names: reject at JSON parsing boundary; do not allow parser last-key-wins behavior to silently canonicalize ambiguous input.
6. Invalid Unicode such as unpaired UTF-16 surrogates: reject rather than emitting ill-formed UTF-8.
7. Nested arrays/objects and property order recursively.
8. Domain separation: exact UTF-8 bytes of SEM-RUNNER-WSS-AUTH-V1 followed by LF, then exact JCS UTF-8 bytes; no BOM, normalization, or whitespace insertion.
9. Transcript schema validation before signature acceptance: exact required fields/types, no unknown properties, and semantic equality between challenge/proof/session negotiation values.
10. Negative mutations of runner_id, key_version, challenge_id, both nonces, audience, endpoint_authority, selected protocol version, and domain prefix.

## 3. Cross-language acceptance matrix

| ID | Scenario | Expected result |
|---|---|---|
| D04-W52 | UTF-16 ordering fixture with supplementary-plane and BMP property names | Python and Node produce exact RFC 8785 bytes, independently checked against a published/reference vector |
| D04-W53 | String escaping fixture with control characters, quotes, reverse solidus and non-ASCII text | Exact canonical UTF-8 bytes match reference vector |
| D04-W54 | Number serialization boundary fixture | Python and Node match RFC 8785/ECMAScript number serialization exactly |
| D04-W55 | Negative zero and non-finite numeric values | -0 serializes as 0; NaN and infinities are rejected before signing |
| D04-W56 | Duplicate object member names | Parser rejects before transcript verification; no last-key-wins acceptance |
| D04-W57 | Unpaired surrogate in transcript string/property name | Reject before UTF-8 signing; no replacement-character normalization |
| D04-W58 | Nested object/array ordering and canonicalization | Exact reference bytes match across independent implementations |
| D04-W59 | Transcript contains unknown or missing required field | Schema/semantic validation rejects before signature acceptance |
| D04-W60 | Proof uses mismatched challenge nonce, key version, audience or authority | Reject authentication and do not establish session |
| D04-W61 | Replayed challenge_id or server_nonce | Reject atomically; no second session |
| D04-W62 | Challenge expires while proof is in flight | Reject according to server receipt-time freshness rule |
| D04-W63 | Selected protocol version is unsupported or downgrade-forced | Reject; no fallback to weaker/older protocol |

## 4. Implementation-independent fixture requirements

- Include expected canonical UTF-8 bytes as hex/base64, not only a parsed JSON object.
- Include source provenance for every reference vector (RFC 8785 examples or independently generated and cross-checked fixture).
- Run at least two independent canonicalization implementations. Do not implement both sides by copying the same helper.
- The Python test must not use sorted json.dumps as a JCS substitute for Unicode/general values.
- The Node test must not merely serialize the same ASCII-only fixture with JSON.stringify and call it full conformance.
- Every negative case must assert both rejection and absence of session creation / durable authentication side effect.
- Keep deterministic private keys TEST-ONLY and separate canonicalization vectors from key/signature lifecycle integration tests.

## 5. Review disposition

The current fixed vector remains useful and should be retained as a smoke test. It does not close P0-02. Before D-04 ratification, add the full edge-case corpus, independent cross-language byte comparisons, duplicate-member rejection, challenge replay/expiry tests, and semantic binding between the challenge and proof. No production WSS authentication implementation is authorized by this addendum.

## 6. Partial implementation progress (2026-11-25; not a closure)

The Node-side validator now adds executable checks for:
- RFC 8785 §3.2.3 UTF-16 property ordering using the RFC's BMP/supplementary-plane example.
- Recursive object sorting while preserving array order.
- Control-character and Unicode serialization.
- Representative RFC 8785 Appendix B IEEE-754 samples, including positive/negative zero, subnormals, large values, and exponent notation.
- The fixed/scientific notation boundary values around 1e-6, 1e-7, 1e20 and 1e21.
- Malformed JSON, lone high/low surrogate values, and non-finite numbers.

The Python verifier now includes an independent test-only JCS canonicalizer: UTF-16BE property ordering, shortest-round-trip binary64 number rendering with ECMAScript fixed/scientific thresholds, string/control escaping, recursive object sorting and array-order preservation. It independently executes the same Unicode property-ordering vector, the representative RFC 8785 Appendix B binary64 cases, exponent boundaries, malformed JSON, duplicate-member, unpaired-surrogate and non-finite-number negatives. It does not call Node or reuse the Node canonicalizer. This closes the deterministic Python/Node cross-check for the committed edge corpus at test-helper level, but does not prove every possible binary64 input or a production Rust parser. The Node validator now performs a pre-parse object-member scan, decodes member-name string tokens before uniqueness comparison (so escaped-equivalent names collide), and delegates final JSON syntax validation to JSON.parse. This is a test helper, not a production parser or proof of zero authentication side effects; D04-W56 remains open until the behavior is independently cross-checked and integrated at the real WSS JSON parsing boundary.

CI run #157 on commit `8b3eec5aa5711edee98b9da7dc1102c7c094040d` completed successfully, including the Node JCS edge-vector step. This proves the committed Node checks execute successfully; it does not prove cross-language JCS conformance or close P0-02.

CI run #197 on commit `1367ecc3eb4d78b1484ad1b279df6ae55b251d12` completed all validation steps successfully. It includes Node UTF-16/number/duplicate-member vectors, Python duplicate-member rejection, RFC 9421 `sf` Content-Digest canonicalization, and Python/Node signed 202/304 response verification.

Updated disposition: **PARTIAL PROGRESS / P0-02 OPEN / CHANGES REQUIRED**. Remaining gates include third/reference-implementation cross-checks, production Rust canonicalizer and raw-parser integration, no-session-side-effect proof for duplicate members, additional reference-byte/differential vectors, transcript semantic binding, and challenge replay/expiry tests with no-side-effect assertions.


## 8. Shared Platform → AI-PM callback envelope vector (2026-11-25)

A deterministic callback-envelope vector now lives at `tests/protocol/fixtures/platform-sem-callback-envelope-jcs-v1.json` (introduced at commit `ad09195d44d557b5a5d174d6bdfdef687dcef4b5`). It uses a valid `execution.infrastructure_uncertain` envelope and publishes:

- Exact payload JCS UTF-8 bytes and `payload_hash`.
- Exact complete authenticated event-envelope JCS UTF-8 bytes and `event_envelope_hash`.
- Stable UUIDs, timestamps and payload fields matching the Platform–SEM callback schema, including the optional top-level `correlation_id`.

Both SEM Python and Node validators now independently verify the exact canonical bytes and SHA-256 values. They also prove that changing `event_type`, `occurred_at` or optional `correlation_id` (including omitting a previously present optional field) changes the full-envelope hash while leaving the payload hash unchanged, and that reordering object members does not change canonical bytes. The Python verifier rejects duplicate members before materializing values; the Node verifier parses the fixture through the strict duplicate-rejecting parser.

The fixture is deliberately ASCII-only with integer numbers. It proves agreement for the full callback envelope shape and the two-hash contract, but does not replace the broader Unicode, UTF-16 ordering and numeric boundary cases in §4. AI-PM's Rust implementation must consume this exact pinned fixture and match all bytes/hashes; the consumer-side acceptance requirement is recorded in AI-PM PR #9.

This remains protocol test evidence, not a production parser, database migration, or live bilateral callback test.


CI evidence update: the optional-correlation-id value and omission assertions passed in runs #224 and #225; the latest PR head `cda9912d106cd0bb90f67da42c3f971f9147b8b7` passed runs #226 (push) and #227 (pull_request), all ten validation steps green.


## 9. Independent Python JCS edge verifier added (2026-11-25)

The Python verifier now independently mirrors the Node edge corpus without using `json.dumps(sort_keys=True)` as a JCS substitute. It sorts property names by UTF-16BE code units and implements ECMAScript notation thresholds over shortest-round-trip IEEE-754 binary64 values. It passes the same RFC supplementary-plane/BMP property-ordering example, 15 representative Appendix B bit-pattern values, negative zero, subnormal values, large magnitudes, the 1e-6/1e-7 and 1e20/1e21 boundaries, recursive object/array/control escaping, malformed JSON, duplicate decoded member names, lone surrogates and non-finite numbers.

This provides independent Python/Node deterministic coverage for the committed edge corpus. It remains test-only and does not select or implement the production Rust JCS dependency. It also does not establish zero-side-effect behavior at the actual HTTP/WSS parsing boundary. P0-02 remains open pending production integration, third/reference implementation, expanded differential vectors and challenge replay/expiry semantics.
