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

The algorithm-family decision is recorded in [D-04 Cryptographic Profile Decision](./D04-CRYPTOGRAPHIC-PROFILE-DECISION.md). These 13 cases extended the previous 67-case matrix to 80 cases. The strict-payload/callback cases below add 12 cases, for 92 total. The strict-payload/callback cases below extend it to 92 cases. They are required additions to the HTTP/WSS test suites; their executable fixture IDs must be preserved in CI.

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