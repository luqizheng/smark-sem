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

The existing Python verifier still independently validates only the fixed ASCII/integer WSS transcript. The new Unicode/number edge vectors are currently Node-only and therefore do **not** satisfy the two-independent-implementation requirement in §4. The Node validator currently uses JSON.parse for object materialization; duplicate member names (including escaped-equivalent names) are not yet rejected before last-key-wins parsing and D04-W56 remains open.

CI run #157 on commit `8b3eec5aa5711edee98b9da7dc1102c7c094040d` completed successfully, including the Node JCS edge-vector step. This proves the committed Node checks execute successfully; it does not prove cross-language JCS conformance or close P0-02.

Updated disposition: **PARTIAL PROGRESS / P0-02 OPEN / CHANGES REQUIRED**. Remaining gates include a second independent implementation for the same Unicode and numeric fixtures, duplicate-member rejection at the raw JSON parsing boundary, reference-byte fixtures, transcript semantic checks, and challenge replay/expiry tests with no-side-effect assertions.
