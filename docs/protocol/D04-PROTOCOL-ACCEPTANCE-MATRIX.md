# D-04 Bilateral Protocol Acceptance Matrix (Draft)

- Version: Draft 0.2
- Status: Review only; not normative and not implementation-authorizing.
- Scope: Platform↔SEM HTTP/HTTPS and Runner↔SEM authenticated WSS.
- Machine-readable artifacts:
  - [Platform–SEM OpenAPI 3.1](./openapi/platform-sem-v1-draft.yaml)
  - [Platform–SEM JSON Schema](./json-schema/platform-sem-v1.schema.yaml)
  - [Runner–SEM WSS JSON Schema](./json-schema/runner-sem-v1.schema.yaml)
  - [Runner–SEM handshake JSON Schema](./json-schema/runner-sem-handshake-v1.schema.yaml)
- Cryptographic decision: [D-04 Cryptographic Profile Decision](./D04-CRYPTOGRAPHIC-PROFILE-DECISION.md)
- Narrative contracts:
  - [Platform–SEM execution protocol](./PLATFORM-SEM-EXECUTION-MESSAGE-PROTOCOL-DRAFT.md)
  - [Runner–SEM WSS protocol](./RUNNER-SEM-WSS-PROTOCOL-DRAFT.md)

## 1. Contract-wide invariants

1. HTTP and HTTPS select transport only; schemas and application semantics are identical.
2. Platform↔SEM uses private-network HTTP or HTTPS. HTTPS validates enterprise CA or explicitly pinned self-signed trust; verification bypass is forbidden. HTTP has no confidentiality and still requires request authentication, integrity, replay defense and idempotency.
3. Runner↔SEM uses outbound authenticated WSS. Runner proves possession of its enrolled key; TLS server authentication is a separate check.
4. AI-PM owns business state and authorization. SEM owns infrastructure execution/delivery/binding/reservation state. Runner Supervisor owns local process lifecycle evidence.
5. Prompt and delegated bootstrap material are opaque to SEM. No Task status, approval or acceptance is inferred from infrastructure messages.
6. Delivery is at least once. Every durable operation has stable identity, duplicate semantics and reconciliation behavior.
7. Transport message sequence and durable Runner journal event sequence are distinct cursors.

## 2. Platform↔SEM HTTP contract cases

| ID | Scenario | Expected result |
|---|---|---|
| D04-H01 | Valid execution.requested with new request_id | 202 only after SEM inbox/request is durable; no claim of Runner binding or Harness start |
| D04-H02 | Same request_id and identical canonical body | Return original acceptance result; no second execution record |
| D04-H03 | Same request_id with different canonical body | 409 conflict; no mutation |
| D04-H04 | Header message ID differs from envelope message_id | Reject as invalid envelope |
| D04-H05 | Idempotency-Key differs from envelope request_id | Reject as invalid envelope |
| D04-H06 | Missing required schema_version/message_type/payload | Reject before durable side effect |
| D04-H07 | Unknown required message type or unsupported major schema version | Fail closed with structured compatibility error |
| D04-H08 | Unknown optional field under compatible schema policy | Apply the explicitly selected unknown-field policy; never silently reinterpret |
| D04-H09 | Oversized prompt body | Reject with payload-too-large response; no partial record |
| D04-H10 | Prompt contains apparent Task status or approval instruction | SEM treats bytes as opaque; no business-state inference |
| D04-H11 | Valid release with current expected_binding_epoch | Persist release intent before forwarding; return 202 |
| D04-H12 | Release with stale expected_binding_epoch | 412; newer binding/process remains untouched |
| D04-H13 | Duplicate release_id/request_id with identical body | Return original release acceptance; no second stop operation |
| D04-H14 | Reused release idempotency key with changed stop policy | 409 conflict |
| D04-H15 | GET reconciliation after lost acceptance response | Return current infrastructure snapshot or 404; never Task status |
| D04-H16 | SEM event delivered twice to AI-PM | AI-PM returns accepted/duplicate disposition and applies event once |
| D04-H17 | Same event_id with changed canonical body | 409 conflict and security audit |
| D04-H18 | SEM event attempts to set Task=completed | Reject/ignore as invalid contract; SEM has no such authority |
| D04-H19 | SEM event sequence gap within execution_id | Persist no unsafe advancement; request/retry replay or reconcile |
| D04-H20 | HTTP deployment with valid request authentication | Accept only on approved private network; no claim of confidentiality |
| D04-H21 | HTTP request has invalid/stale timestamp or replayed nonce | Reject and audit |
| D04-H22 | HTTPS uses enterprise CA or explicitly pinned self-signed certificate | Accept only after full trust and hostname/identity validation |
| D04-H23 | HTTPS certificate is untrusted, expired, hostname-mismatched or pin-mismatched | Fail closed |
| D04-H24 | Production client attempts verify=false / insecure downgrade | Configuration/startup rejected |
| D04-H25 | Transient 5xx/429 response | Bounded retry using the same request_id and message identity; honor Retry-After where present |


## 2.1 Approved cryptographic profile acceptance cases

The algorithm-family decision is recorded in [D-04 Cryptographic Profile Decision](./D04-CRYPTOGRAPHIC-PROFILE-DECISION.md). These 13 cryptographic cases extended the previous 67-case matrix to 80 cases. The strict-payload/callback cases add 12 cases, for 92. The executable crypto-vector cases add 12, for 104 total. They are required additions to the HTTP/WSS test suites; their executable fixture IDs must be preserved in CI.

| ID | Scenario | Expected result |
|---|---|---|
| D04-H26 | Valid Ed25519 RFC 9421 request with matching RFC 9530 Content-Digest | Signature and digest verify before request parsing or persistence |
| D04-H27 | Request body changes after signature creation | Digest/signature verification fails; no durable mutation |
| D04-H28 | HTTP method, authority, path or query changes | Signature verification fails |
| D04-H29 | Signature-Input has unknown/revoked keyid or unsupported algorithm | Fail closed; no unsigned fallback |
| D04-H30 | Signature created/expires violates configured freshness policy | Reject and audit |
| D04-H31 | Same nonce is replayed under the same keyid | Reject atomically; first accepted operation remains idempotent |
| D04-H32 | Valid signed HTTP response is altered in transit | Platform rejects response and does not trust its acknowledgement |
| D04-W35 | Valid Ed25519 signature over the exact domain-separated RFC 8785 JCS transcript | WSS authentication may proceed after TLS validation |
| D04-W36 | Any signed transcript field changes, including endpoint authority or audience | Signature verification fails; no session |
| D04-W37 | Same challenge_id is presented more than once | Replay rejected; no second session |
| D04-W38 | Runner key is rotated with an explicitly configured overlap window | Only keys in the active/overlap set authenticate |
| D04-W39 | Runner key is revoked | Authentication rejected even if the signature is otherwise valid |
| D04-W40 | TLS hostname/chain/pin validation fails while Runner proof is valid | Connection rejected before application authentication |

### 2.2 Executable cryptographic vector cases

The deterministic TEST-ONLY vectors live in [crypto-vectors-v1.json](../../tests/protocol/fixtures/crypto-vectors-v1.json). The verifier script checks the expected digest, RFC 9421 signature base, Ed25519 signature, RFC 8785 transcript serialization, WSS domain separation, deterministic key derivation and negative mutations. The fixture private seeds MUST never be used outside tests.

| ID | Scenario | Expected result |
|---|---|---|
| D04-H41 | Verify the fixed HTTP request Content-Digest and Ed25519 signature-base vector | Exact digest, canonical base and signature verify |
| D04-H42 | Change the body while retaining the original Content-Digest | Digest mismatch; reject before persistence |
| D04-H43 | Change HTTP method or authority | Signature verification fails |
| D04-H44 | Change path or Content-Type | Signature verification fails |
| D04-H45 | Change Idempotency-Key or Content-Digest | Signature verification fails |
| D04-H46 | Verify the official RFC 9421 Appendix B.2.6 Ed25519 signature-base vector in Python and Node | Both independent verifiers accept the published signature and reproduce it from the TEST-ONLY key |
| D04-W51 | Serialize and verify the fixed WSS JCS transcript independently in Python and Node | Canonical bytes and Ed25519 signature are byte-identical in both implementations |
| D04-W46 | Verify the fixed WSS transcript after RFC 8785 JCS serialization and domain separation | Exact transcript signature verifies |
| D04-W47 | Change runner_id, audience or endpoint authority | Signature verification fails |
| D04-W48 | Change challenge_id or protocol version | Signature verification fails |
| D04-W49 | Remove the domain-separation prefix | Signature verification fails |
| D04-W50 | Derive public key and signature again from the TEST-ONLY seed | Derived key and deterministic signature exactly match fixture |

### 2.3 Executable payload-schema fixture coverage

[Payload fixtures](../../tests/protocol/fixtures/payload-fixtures-v1.json) and [their validator](../../scripts/validate_sem_payload_fixtures.py) cover every current strict payload branch. The suite now contains 29 valid examples (20 Runner WSS messages, 2 Platform requests and 7 SEM infrastructure events). For each example it asserts rejection of an unknown top-level field, an unknown payload field and an empty payload missing required fields: 87 baseline negative mutations. Total baseline coverage: **116 positive/negative schema fixture assertions**, plus dedicated ACK and cross-field exit/uncertainty assertions in the validator. These are distinct from the scenario-level acceptance requirements below.

| Fixture group | Positive examples | Negative mutations | Coverage |
|---|---:|---:|---|
| Runner WSS application messages | 20 | 60 | Every post-handshake message type, including signal-terminated process exit |
| Platform HTTP requests | 2 | 6 | Execution request and release request |
| SEM infrastructure events | 7 | 21 | All five event types plus exited and unknown-exit process observations |

## 3. Runner↔SEM WSS contract cases

| ID | Scenario | Expected result |
|---|---|---|
| D04-W01 | Unknown, revoked or superseded Runner key | Authentication rejected |
| D04-W02 | Expired, replayed or wrong-audience challenge proof | Authentication rejected |
| D04-W31 | Challenge/proof transcript has a changed field, wrong domain prefix or non-canonical JSON | Ed25519 verification fails; no session is created |
| D04-W32 | Runner submits a second proof for the same challenge_id | Single-use challenge rejects replay |
| D04-W33 | Runner selects a protocol version not offered in challenge | Authentication/negotiation rejected; no downgrade |
| D04-W34 | server_nonce/client_nonce has wrong length or malformed base64url | Schema/authentication rejects before session establishment |
| D04-W03 | Valid key proof but invalid TLS server identity | Connection rejected before application authentication |
| D04-W04 | Second session authenticates for same Runner | Atomic session-generation winner; old session fenced |
| D04-W05 | Message runner_id/connection_id/session_generation mismatches authenticated session | Reject and audit |
| D04-W06 | Same message_id and identical canonical content | Original disposition returned; no duplicate side effect |
| D04-W07 | Same message_id with changed content | Protocol conflict; quarantine according to security policy |
| D04-W08 | message_sequence gap within a connection generation | Trigger transport replay/reconciliation; do not apply unsafe ordering |
| D04-W09 | Durable event_sequence gap within runner_id+journal_id | Trigger durable journal replay/reconciliation |
| D04-W10 | Reconnect creates new connection_id/session_generation | Transport sequence resets; durable journal cursor continues |
| D04-W11 | Duplicate execution.deliver | Same durable receipt; no duplicate Harness launch |
| D04-W12 | Delivery ACK sent before local durable journal commit | Test fails; ACK must follow durable write |
| D04-W13 | WSS disconnect before delivery ACK | Execution becomes uncertain; no blind reassignment |
| D04-W14 | WSS disconnect after delivery ACK but before started event | Reconcile; receipt is not process-start proof |
| D04-W15 | heartbeat fresh but Supervisor degraded | Runner ineligible |
| D04-W16 | WebSocket ping/pong succeeds but application heartbeat stale | Runner ineligible |
| D04-W17 | Resource report from previous boot/session | Ignore for admission |
| D04-W18 | Missing resource dimensions | Treat as unknown, not zero or unlimited |
| D04-W19 | Two schedulers reserve the last capacity concurrently | Atomic reservation allows only capacity-safe winner |
| D04-W20 | Duplicate release command with same release_id and binding_epoch | Idempotent local stop/release operation |
| D04-W21 | Stale release epoch | Reject; newer binding unaffected |
| D04-W22 | Stop request ACK but cgroup populated=1 | No process-exited event and no capacity release |
| D04-W23 | systemd invocation identity mismatch | Reject exit evidence; remain uncertain |
| D04-W24 | cgroup populated=0 but systemd start/restart job pending | No exit proof |
| D04-W25 | Harness exits and numeric exit status is lost during Supervisor crash | Report unknown status only if exact containment-empty evidence is proven |
| D04-W26 | Harness process attempts to access host systemd/Docker control socket | Deny; quarantine if containment integrity is uncertain |
| D04-W27 | Runner disk full prevents durable event journal write | Do not ACK or discard event; mark degraded/non-accepting and retain uncertainty |
| D04-W28 | Runner event replay after reconnect | Preserve original event_id, journal_id and event_sequence; deduplicate idempotently |
| D04-W29 | Prompt or delegated bootstrap bytes appear in protocol.error/log output | Test fails; secret/body redaction required |
| D04-W30 | Runner is draining or quarantined | No new delivery; existing execution supervision continues |


## 3.1 Strict payload and cross-repository callback cases

| ID | Scenario | Expected result |
|---|---|---|
| D04-W41 | Each post-handshake WSS message_type is matched to exactly one strict payload branch and one direction | Contract validator fails on missing/duplicate/unlisted branches |
| D04-W42 | Any WSS state-changing payload contains an undeclared field | Schema validation rejects it |
| D04-W43 | harness.started lacks exact process identity or systemd invocation ID | Reject; no started observation is accepted |
| D04-W44 | harness.process_exited lacks cgroup populated=0 and exact invocation/evidence identity | Reject; execution remains uncertain |
| D04-W45 | execution.release_applied reports stop_fenced only | SEM must not infer process exit or release capacity unless separate exit evidence is present |
| D04-W46 | execution.release_applied reports process_stopped or already_exited without process_exit_evidence_id | Reject; a positive stop/exit disposition must reference exact durable exit evidence |
| D04-W47 | execution.release_applied reports stop_fenced, stale_rejected or local_uncertain with process_exit_evidence_id | Reject; these dispositions must not masquerade as positive process-exit proof |
| D04-W48 | process_stopped/already_exited release_applied references a different execution, binding or later/missing Runner process-exit journal event | Reject/quarantine; no release completion or capacity release until the exact earlier process-exit evidence is linked |
| D04-W49 | stop_fenced is reported while a Harness invocation exists, a start/restart job is pending, or exact no-start proof is unavailable | Reject/mark local_uncertain; retain reservation/quarantine; a fence commit alone is not an effective no-start ACK |
| D04-H33 | Each SEM event_type maps to exactly one strict payload schema | Contract validator fails on missing/duplicate event branch |
| D04-H34 | SEM infrastructure event contains TaskStatus, approval or acceptance decision fields | Reject as authority-boundary violation |
| D04-H35 | Duplicate event_id with identical canonical body reaches AI-PM Inbox | One durable event observation; duplicate ACK |
| D04-H36 | Same event_id with different body reaches AI-PM Inbox | 409 conflict; no second application |
| D04-H37 | execution_event_sequence has a gap for execution_id | Do not advance cursor; request replay/reconciliation |
| D04-H38 | AI-PM generic /api/v1/events endpoint receives SEM infrastructure event | Reject or remain outside SEM contract; it is not the SEM Inbox |
| D04-H39 | SEM callback ACK is returned before AI-PM Inbox+observation transaction commits | Test fails; ACK must follow durable commit |

## 4. Cross-protocol consistency cases

| ID | Scenario | Expected result |
|---|---|---|
| D04-X01 | HTTP release arrives while systemd start operation is unresolved | SEM/Runner persist release fence; no effective stop ACK until launch is resolved/fenced |
| D04-X02 | AI-PM authorization_generation changes while SEM binding_epoch is unchanged | AI-PM rejects stale Harness MCP grant; SEM binding remains independently scoped |
| D04-X03 | SEM rebinds execution while old Runner may still be alive | Old binding/process must be positively fenced before competing Harness launch |
| D04-X04 | Harness process exits with code 0 | Infrastructure observation only; AI-PM independently decides Run outcome and Task state |
| D04-X05 | Task reaches Submitted/Reviewing while Harness process remains active | AI-PM may issue release based on its business policy; release does not mean Task completed |
| D04-X06 | SEM restarts after accepting request but before delivery | Recover durable inbox/outbox/reservation/binding state; same execution identity retained |
| D04-X07 | AI-PM is unavailable while Runner emits durable process event | Runner journals and retries; event identity/cursor remain stable |
| D04-X08 | Platform and Runner clocks disagree | Freshness/replay policy uses server receipt time where specified; sender time remains observational metadata |

## 5. Required validator and CI checks

- Parse OpenAPI as OpenAPI 3.1; reject unresolved references and invalid parameter/response structures.
- Validate each JSON Schema against the declared 2020-12 meta-schema.
- Validate every positive and negative fixture against the appropriate schema.
- Ensure each message_type in the WSS catalogue has exactly one schema branch and each schema branch is documented in the catalogue.
- Ensure every HTTP operation has request, success, authentication, conflict and retryable failure response definitions.
- Check that no schema introduces AI-PM Task/Requirement/Approval state into SEM-owned fields.
- Check all durable Runner events carry journal_id + event_sequence and that transport message_sequence remains connection-scoped.
- Run contract compatibility checks for additive optional fields, required-field changes and major-version negotiation.
- Run cross-repository contract fixtures against AI-PM Outbox/Inbox adapters before implementation is considered ready.

## 6. Still open; not silently frozen by these artifacts

1. HTTP request authentication/signature algorithm, canonicalization, timestamp/nonce replay window, key ID and rotation.
2. Exact endpoint ownership and route prefix alignment with the AI-PM server; callback URL registration and delivery authentication.
3. Complete event payload schemas for binding, delivery status, process observation, release status and uncertainty.
4. WSS challenge transcript candidate (Ed25519 + JCS domain-separated bytes) requires ratification, signature test vectors, challenge TTL and key-rotation overlap.
5. Full payload definitions for every WSS message, including replay snapshot, health probe/report, admission changes and release-applied evidence.
6. Exact event-journal ACK/cursor request and response, retention, compaction and recovery behavior.
7. Maximum prompt/frame sizes, content-reference alternative, compression and retention.
8. Heartbeat/resource-report intervals, freshness windows, stop grace-period policy and retry/backoff bounds.
9. Error code registry, retryability table, close/quarantine behavior and version negotiation.
10. D-01/D-02 credential bootstrap envelope and broker redemption binding.
11. D-08 capacity units and telemetry/admission constraints.
12. D-09 network, certificate and operational profile.

**Current disposition: machine-readable Draft baseline created; D-04 remains P0 OPEN and not ready for ratification or development.**

## 4.1 Bilateral ACK and identity/evidence semantic cases

| ID | Scenario | Expected result |
|---|---|---|
| D04-H40 | SEM callback ACK echoes event sequence | ACK uses `execution_event_sequence` exactly; legacy `event_sequence` is rejected |
| D04-H41 | Delivery/process/release/uncertainty event omits runner_key_version, boot_id or supervisor_instance_id | Strict schema rejects the event |
| D04-H42 | Process observation is exited with both exit_code and exit_signal | Reject; exactly one exit-status discriminator is allowed |
| D04-H43 | Process observation is exited without exact process identity or exit evidence | Reject; no process-exited fact is accepted |
| D04-H44 | Release state is process_exited without process_exit_evidence_id | Reject; no release completion/capacity release |
| D04-H45 | Evidence reference resolves to another execution/runner/boot/supervisor/binding/launch/containment | Semantic validation rejects or quarantines; cursor must not advance |
| D04-H46 | Structurally valid event has stale binding_epoch | Reject/quarantine as stale; do not overwrite newer binding observation |
| D04-H47 | exit_status_unknown has positive exact containment-empty evidence but no numeric status | Accept only as unknown process exit status; never infer exit code 0 or business success |


## 4.2 AI-PM Inbox transaction and concurrency acceptance cases

These cases complement the wire/schema cases above. They are normative test requirements for the bilateral callback adapter, not evidence that the adapter or database migration exists. The detailed transaction algorithm and SQL candidate are in the AI-PM PR #9 document [SEM Callback Inbox — Exact DDL and Concurrency Design](https://github.com/luqizheng/ai-pm/blob/docs/sem-02e-architecture-convergence/docs/architecture/server-execution-management/sem-callback-inbox-ddl-and-concurrency-design.md).

| ID | Scenario | Expected result |
|---|---|---|
| D04-BI-01 | First event for execution sequence 1 | One Inbox row, one append-only Run observation, cursor 1; ACK only after commit |
| D04-BI-02 | Same event_id, execution_id, sequence and JCS payload hash replayed | Duplicate ACK; no second Run observation |
| D04-BI-03 | Same event_id with changed payload hash | 409 IDEMPOTENCY_CONFLICT; no additional writes |
| D04-BI-04 | Same event_id with changed execution_id or execution_event_sequence | 409 IDEMPOTENCY_CONFLICT; no additional writes |
| D04-BI-05 | Same execution sequence concurrently delivered under different event IDs | Exactly one commits; loser receives 409 EVENT_SEQUENCE_CONFLICT |
| D04-BI-06 | Same event ID/body concurrently delivered | Exactly one durable application; other returns duplicate after winner commits |
| D04-BI-07 | Sequence N+1 arrives before N | 409 EVENT_SEQUENCE_GAP with expected_sequence; no cursor advance |
| D04-BI-08 | N commits but response is lost; exact N is replayed | Duplicate ACK; cursor remains N |
| D04-BI-09 | Process crashes before transaction commit | Inbox, Run observation and cursor all roll back; no success ACK |
| D04-BI-10 | Same event ID is submitted from another project/source | Existing global Inbox PK prevents second row; no cross-project data disclosure |
| D04-BI-11 | Unknown execution, wrong tenant or wrong project | Non-enumerating 404; no writes |
| D04-BI-12 | Execution ID resolves to review Run | Non-enumerating 404; no writes |
| D04-BI-13 | Runner key version, boot ID, Supervisor ID or binding epoch is stale | Reject/quarantine; cursor unchanged |
| D04-BI-14 | Process-exited event lacks exact process/exit evidence | Reject; cursor unchanged |
| D04-BI-15 | Release process_exited lacks process-exit evidence reference | Reject; cursor unchanged |
| D04-BI-16 | SEM service principal submits through dedicated service route | Accepted only as service identity; never HumanActor |
| D04-BI-17 | SEM callback is persisted | No integration.job row with job_type=ai_analysis |
| D04-BI-18 | Infrastructure event reports exit_code=0 | Infrastructure observation only; no Task/Run business-success mutation |
| D04-BI-19 | N and N+1 arrive concurrently | Run-row serialization yields ordered observations and cursor N+1 |
| D04-BI-20 | Failure after Inbox insert but before Run observation | Entire transaction rolls back |
| D04-BI-21 | Failure after Run observation but before cursor advance | Entire transaction rolls back |
| D04-BI-22 | Transient database failure and retry | Same event ID/body reused; no sequence skip |
| D04-BI-23 | Non-SEM generic ingestion after migration | Existing project/source/idempotency semantics remain unchanged |
| D04-BI-24 | Duplicate JSON member names or invalid JCS input | Reject before persistence or cursor movement |

**Execution status:** specification only. Every case still requires a real PostgreSQL two-connection test where applicable, exact row-count/value assertions across Inbox + Run event + cursor, and bilateral CI execution. No test is marked passed by the presence of this matrix.


### 2.4 Signed-response and conditional-GET acceptance cases (Draft addendum)

See [D-04 HTTP Signed Response and Conditional GET Addendum](./D04-HTTP-SIGNED-RESPONSE-AND-CONDITIONAL-GET-ADDENDUM.md). These cases are additional requirements and are not yet executable fixtures.

| ID | Scenario | Expected result |
|---|---|---|
| D04-H52 | Valid signed 202 response with matching X-SEM-Request-Id | Client trusts acceptance only after signature/digest/correlation verification |
| D04-H53 | Signed structured 4xx/5xx response | Client accepts typed error only after response verification |
| D04-H54 | Missing response Signature or Signature-Input | Client fails closed; no typed result |
| D04-H55 | Response Content-Digest mismatch | Client rejects before decoding/trusting body |
| D04-H56 | Response correlation header does not match request request_id/callback event_id | Client rejects as response-confusion/replay |
| D04-H57 | Valid 304 with ETag echo, empty-content digest and valid signature | Client returns NotModified only after all checks |
| D04-H58 | 304 missing ETag, signature, digest or correlation header | Client rejects; must not treat as cache hit |
| D04-H59 | 304 contains a response body | Client rejects as protocol violation |
| D04-H60 | 304 ETag differs from requested/current validator | Client rejects or performs unconditional reconciliation; never silently accepts |
| D04-H61 | Replay a previously accepted signed response nonce | Client rejects replay according to the ratified response replay scope |
| D04-H62 | Signed response uses unknown/revoked keyid | Client fails closed |
| D04-H68 | SEM→AI-PM callback ACK 200 has a valid response signature and `X-SEM-Event-Id = event_id` | Python and Node independently verify response digest/signature and associated request context |
| D04-H69 | Callback ACK response signs an `X-SEM-Event-Id` different from the request's authenticated `event_id` | Client rejects response-confusion/replay; signature verification fails; no ACK is accepted |
| D04-H70 | Platform→SEM signed 409 structured `IDEMPOTENCY_CONFLICT` response with `X-SEM-Request-Id = request_id` | Python and Node independently verify exact response digest/signature and associated request context |
| D04-H71 | Platform→SEM signed error response uses `message_id` instead of `request_id` in `X-SEM-Request-Id` | Client rejects; signature verification fails; transport message identity cannot substitute for operation/idempotency identity |
| D04-H72 | Replay a valid signed response against a different method, authority, path, request Content-Digest or (304) If-None-Match | Python and Node independently reject every mutated request-context signature base; response cannot be detached from its originating request |
| D04-H73 | GET snapshot 200 response includes ETag and a valid signature covering the exact ETag value | Python and Node verify response digest/signature and request context; ETag is a covered component |
| D04-H74 | GET snapshot 200 response ETag is modified while all other response fields remain unchanged | Signature verification fails; client rejects the altered cache validator |
| D04-H75 | Conditional 304 response ETag is modified while request `If-None-Match` and all other response fields remain unchanged | Signature verification fails; client rejects the altered cache validator |
| D04-H76 | Authenticated GET for an unknown execution returns a signed structured 404 with `X-SEM-Request-Id = request_id` | Client verifies response signature, digest and exact request context before returning typed `NotFound` |
| D04-H77 | Pre-authentication or malformed request has no trustworthy canonical request context | Generic error path does not echo attacker-controlled `request_id`, `message_id` or `event_id` as authenticated correlation; separate response-signing/correlation policy is applied |

These cases do not close P0-01 until they are represented in executable independent vectors and live request/response/replay integration tests.


### 3.2 Full RFC 8785 JCS conformance cases (Draft addendum)

See [D-04 RFC 8785 Full JCS Conformance Addendum](./D04-RFC8785-FULL-JCS-CONFORMANCE-ADDENDUM.md). The existing fixed WSS vector remains a smoke test only; these additional cases are required before P0-02 closure.

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


### 4.3 Cross-protocol process-exit and uncertainty invariants (Draft)

| ID | Scenario | Expected result |
|---|---|---|
| D04-H63 | Runner reports Harness termination by OS signal | Runner WSS schema accepts `exit_status.kind=signal`; SEM maps the exact signal into Platform `exit_evidence.exit_signal` without fabricating an exit code |
| D04-H64 | Runner reports `exit_status.kind=unknown` with a numeric code or signal | Reject contradictory status; unknown means no numeric status is available |
| D04-H65 | SEM emits `execution.infrastructure_uncertain` without `reservation_retained=true` | Schema rejects; uncertainty must retain the durable capacity reservation until reconciliation or an explicitly authorized terminal disposition |
| D04-H66 | SEM emits `harness.process_observed` with `observation=exit_status_unknown` and a numeric exit code/signal | Reject contradictory evidence; accept only exact containment-empty evidence without numeric status |
| D04-H67 | SEM emits `harness.process_observed` with `observation=exit_status_unknown` and no numeric exit status | Accept only as infrastructure process-exit evidence with unknown numeric status; never infer business success |

These are protocol/fixture requirements. They do not prove that the production Runner Supervisor, SEM event producer or AI-PM receiver implements the mapping.


### 3.3 Handshake/application frame ownership

| ID | Scenario | Expected result |
|---|---|---|
| D04-W64 | A message_type appears in both pre-application handshake and post-handshake application schemas | Contract validation fails; the two frame ownership sets must be disjoint. `runner.session.ack` is handshake-only; `runner.session.superseded` is post-handshake-only because it is sent over an already authenticated old connection. |


### 4.4 Authenticated and pre-authentication HTTP error boundary

| ID | Scenario | Expected result |
|---|---|---|
| D04-H78 | Valid request signature over malformed JSON bytes | Authenticated signed 400; response binds exact request context and correlates only to signed Idempotency-Key; no application/database side effects |
| D04-H79 | Missing/invalid signature, unknown/revoked key, stale timestamp or replayed nonce | Generic unsigned 401; no Content-Digest/Signature response headers, no protocol correlation headers and no request/event IDs in body |
| D04-H80 | Body-size limit rejects before the complete body can be authenticated | Generic unsigned 413; no protocol signature/correlation headers or attacker-controlled IDs |
| D04-H81 | Authenticated application-level rate limit | Signed 429 with Retry-After and direction-correct correlation; request is not applied |
| D04-H82 | Authenticated application failure returns 500 | Signed 500 bound to exact request context; if response signing is unavailable, terminate response/connection and never downgrade to an unsigned correlated response |
| D04-H83 | Callback Idempotency-Key differs from envelope event_id or event_id is absent after request signature verification | Signed 400 correlated only to the authenticated Idempotency-Key header; do not echo the untrusted body event_id; no Inbox/cursor writes |
| D04-H84 | HTTP framing/parser rejects request before API handler | Outside application protocol; no protocol correlation identifiers are reflected |
| D04-H85 | Network-edge/WAF rate limit rejects before API authentication | Outside application protocol; no protocol correlation identifiers are reflected; application-level 429 remains signed |
| D04-H86 | Authenticated callback references an unknown/wrong-scope execution | Signed 404 with X-SEM-Event-Id equal to authenticated Idempotency-Key; Python and Node verify response signature and exact originating request context |
| D04-H87 | Authenticated Platform GET references an unknown execution | Signed 404 with X-SEM-Request-Id equal to authenticated Idempotency-Key; Python and Node verify response signature and exact originating request context |
| D04-H88 | Pre-authentication 401/early-413 response fixture | Python and Node assert no signature/correlation headers and a minimal error body with no message_id/in_reply_to/request_id/event_id |

These cases define response-authentication classes only. They do not close D-04 P0-01 until deterministic signed-error vectors, OpenAPI validation, middleware ordering tests, and live HTTP/replay integration pass.

| D04-H89 | execution.release_status reports requested or stale_rejected before a stop fence exists and omits stop_fence_id | Accept; no fence may be fabricated before Runner durably records it |
| D04-H90 | execution.release_status reports stop_fenced/termination_requested/process_exited/released/cleanup_failed without stop_fence_id | Reject; every post-fence state must reference the exact immutable stop-fence journal record |