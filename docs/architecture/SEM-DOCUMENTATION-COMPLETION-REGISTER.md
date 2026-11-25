# SEM / AI-PM Bilateral Documentation Completion Register

- Status: **OPEN — architecture and contract design is not yet complete**.
- Review date: 2026-11-25.
- Scope: `luqizheng/smark-sem` and its upstream consumer `luqizheng/ai-pm`.
- This register is the single checklist for reaching a development-ready documentation baseline.
- No implementation, migration, runtime configuration, Phase 0 or PR merge is authorized by this register.

## 1. Development gate

Implementation is prohibited until every P0 item is resolved in normative documents, both repositories reference the same contract versions, and the user explicitly authorizes development.

"Document exists" is not completion. A document is complete only when:
1. it has a named authority/owner and normative status;
2. all normative terms, identifiers, states and error outcomes are defined;
3. all request/response/event schemas are exact and versioned;
4. retry, duplicate, timeout, restart, crash and uncertain outcomes are specified;
5. security and authorization checks are explicit and testable;
6. cross-document and cross-repository references are consistent;
7. acceptance tests cover normal, adversarial and recovery paths.

## 2. Fixed architecture invariants

These are the current user-confirmed constraints and must not be reopened casually:

- SEM is a separate service/repository and a downstream dependency consumed by AI-PM.
- SEM is an infrastructure message transport/runtime manager, not an AI-PM business orchestrator.
- Business payloads (including prompt/body) are opaque to SEM.
- AI-PM owns Project, Requirement, Task, business Run/attempt, authorization, Task transitions, review/acceptance and the decision to release a runtime.
- Harness gets Task context and performs business operations only through AI-PM MCP.
- SEM owns its execution/delivery/release ledger, Runner connectivity/registration metadata, resource telemetry/reservations and binding_epoch.
- Runner Supervisor owns local Harness process start/stop, process identity and positive process-exit evidence.
- AI-PM and SEM use independent databases; SEM has no AI-PM DB access.
- AI-PM→SEM uses the smark-sem-owned, versioned Rust SDK over the versioned HTTP/HTTPS API; AI-PM owns durable Outbox/Inbox and retry scheduling. Runner↔SEM is authenticated WSS.
- SEM→AI-PM infrastructure events use an AI-PM-owned callback endpoint; smark-sem owns event schemas/fixtures, while AI-PM owns callback ingress, Inbox transaction and ACK-after-commit.
- No cross-database transaction; delivery is at-least-once, idempotent and reconciled.
- Runner default supervision is unattended; supervised mode is explicit.
- Runner CPU/memory/workspace-volume telemetry informs SEM admission/concurrency.
- Workspace backup is not required; process registry/evidence are operational state, not workspace backup.
- Each repository has one authoritative Git origin.
- Existing RabbitMQ is a separate non-clustered singleton; it is not an authority or correctness dependency. Optional wake-up use requires a separate decision.

## 3. Required normative document set

| Package | Required content | Current status |
|---|---|---|
| Architecture authority | service responsibilities, data ownership, trust boundaries, forbidden dependencies | Draft exists; needs final ratification |
| Deployment topology | process placement, network zones, ports, TLS, secrets, storage, HA assumptions | Incomplete |
| Runner identity/enrollment | device enrollment, key possession, attestation, rotation, revocation, recovery | **P0 open** |
| Delegated Harness identity | grant schema, bootstrap exchange, token scope, audit, revocation | Draft exists; **P0 open** |
| Platform–SEM wire protocol | OpenAPI/JSON Schema, all endpoints/events/ACK/error shapes, versioning | Draft examples exist; **P0 open** |
| SEM SDK and consumer integration | SEM-owned Rust SDK, AI-PM consumption, transport/auth, retries, errors, semver and bilateral CI | Draft exists; API/release details open |
| Runner–SEM wire protocol | WSS handshake, message schemas, sequencing, reconnect, backpressure | Superseded V1 exists; replacement incomplete |
| Lifecycle/state machines | AI-PM Run, SEM Execution, Runner Process, delivery/release and transitions | Draft exists; needs formal state tables |
| Process fencing/recovery | disconnect, host loss, process proof, rebind, termination/isolation | Draft exists; **P0 open** |
| Resource admission | telemetry, freshness, reservation, concurrency, disk pressure, fairness | Partial; needs concrete algorithm |
| Git delivery | credential injection, execution ref, push/fetch verification, cleanup | Partial; **P1 open** |
| Operations/security | secrets, TLS, logging, metrics, retention, backup/restore, upgrades, incident runbook | Incomplete |
| Implementation architecture | Rust modules, ports/adapters, database schema ownership, dependency graph | Incomplete |
| Test/acceptance | contract tests, security tests, process integration, chaos/recovery, load tests | Draft matrix exists; needs executable cases |

## 4. P0 design decisions to close

### D-01 — Runner identity trust chain

The current proposal is recorded in [Runner Enrollment and Cryptographic Identity Draft](./runner-enrollment-and-cryptographic-identity-draft.md). It adopts the GitLab-Runner-style operator workflow:

1. An SEM administrator creates a scoped, short-lived, single-use registration credential in SEM.
2. The operator runs `sem-runner register --registry https://sem.example.com --registration-token <TOKEN>` on the Runner host.
3. Runner generates its own Ed25519 keypair locally; only the public key is sent to SEM.
4. SEM atomically consumes the registration credential, assigns immutable `runner_id`, and binds the public key.
5. The installed Runner authenticates its long-lived outbound WSS connection with challenge-response proof of possession. The registration token is never reused for WSS or MCP.

Authority is split deliberately: SEM owns infrastructure enrollment, Runner identity, key versions, connection/admission state and revocation. AI-PM owns business grants and exact Task/Run authorization. SEM-issued Runner identity is not business authorization.

The same WSS connection is the dispatch channel; SEM must not open a fresh connection or poll Runner for every task. Dispatch eligibility is a derived predicate, not a socket-open boolean. It requires an authenticated current WSS session, fresh application heartbeat, fresh same-boot resource telemetry, healthy Supervisor, accepting-work admission state and sufficient capacity after durable reservations. Transport ping/pong alone is insufficient. A delivery is sent only after reservation and binding epoch are durable; missing ACK or WSS loss causes reconciliation, not blind reassignment.

The proposal remains pending ratification and D-04/D-09 contract closure. Open details include exact API/CLI schemas, token hashing and idempotency, key storage, WSS challenge canonicalization, heartbeat intervals/deadlines, identity assertion/key distribution, and rotation/recovery procedures.

**Required invariants:** registration token is bootstrap-only; Runner private key never leaves the host; WSS online does not prove process exit; disconnect does not prove process death; SEM cannot issue AI-PM grants; and no replacement Runner may start the same logical execution until the old binding/process is safely fenced.

### D-02 — Delegated grant and bootstrap protocol

A detailed proposal is now recorded in [Delegated Harness Grant and Credential Broker Draft](./delegated-harness-grant-and-credential-broker-draft.md). It recommends an AI-PM-owned exact-scope grant, one-time Runner-key-bound bootstrap ticket, opaque short-lived MCP token, local credential broker/proxy and per-request application-service authorization. The exact token/wire schema and Harness proxy transport remain open.

Specify the exact AI-PM-owned grant record/claims and lifecycle:
- grant_id, jti, tenant/project/task/run/attempt/execution tuple, authorization_generation;
- Runner identity/key binding, operation allow-list, delegating actor, Harness executor identity;
- issue/not-before/expiry, one-time redemption, revocation and consumed state;
- token audience, signing/verification keys, key rotation and replay prevention;
- credential broker API/IPC and injection into Harness MCP without prompt, argv, workspace or ordinary logs;
- per-call authorization at AI-PM application-service boundary;
- audit schema and secret redaction.

Explicitly prohibit reuse of human JWT/API keys, SEM service JWT, Runner WSS credential and existing `cpk_`.

### D-03 — Permanent Runner loss and process isolation

A safety proposal is now recorded in [Runner Host Isolation and Permanent-Loss Recovery Draft](./runner-host-isolation-and-permanent-loss-recovery-draft.md). It distinguishes local process containment from independent host fencing and defines three deployment profiles: managed VM, bare metal with BMC/IPMI, and unmanaged bare metal. Until the actual deployment profile is selected, safe behavior is quarantine plus operator intervention; automatic failover is not claimable.

Specify what constitutes independently verifiable host fencing:
- cloud/VM power-off or revoke compute lease;
- container/VM runtime isolation;
- host agent/management plane proof;
- physical/manual operator procedure where no reliable remote control plane exists.

Define which evidence is trusted, who can issue it, how it is signed/audited, and when SEM may release reservations or allow a new binding. A timeout, WSS disconnect, expired heartbeat or MCP grant revocation is never sufficient.

### D-04 — Complete bilateral protocol

A detailed Runner↔SEM WSS candidate is now recorded in [Runner–SEM WebSocket Protocol and Dispatch Contract Draft](../protocol/RUNNER-SEM-WSS-PROTOCOL-DRAFT.md). It defines the authenticated long-lived session, connection-generation fencing, heartbeat/health separation, telemetry, durable delivery ACK, reconnect/replay, backpressure and dispatch eligibility. It remains Draft; exact crypto canonicalization, timers, resource policy and machine-readable schemas remain open.

Publish machine-readable OpenAPI/JSON Schema and examples for:
- execution.requested / accepted / rejected;
- execution.binding_established;
- credential bootstrap transport and redemption;
- delivery received / started / start_failed;
- process exited / uncertain / reconciliation;
- resource telemetry;
- release requested / applied / failed;
- error envelope, retryability, retry-after, conflict and reconciliation response.

Specify canonical serialization, message_id, request_id, execution_id, delivery_id, release_id, event_id, event_sequence, binding_epoch, timestamp rules, payload size limits, encryption, retention, schema evolution and unknown-field policy. Clearly distinguish SEM→AI-PM events from Runner→SEM observations.

### D-05 — State machines and crash consistency

Provide normative state tables with allowed transitions, actor, preconditions, durable write, emitted event, duplicate behavior and recovery for:
- AI-PM business Run/attempt and authorization grant;
- SEM execution/delivery/binding/release;
- Runner Supervisor process lifecycle and local durable registry.

Cover races: release during start, natural exit before release, disconnect during delivery, SEM restart, Runner reboot, delayed/out-of-order events, event sequence gaps, duplicate message with changed payload, and stale binding epoch.

### D-06 — Delegated MCP application-service contract

Define every allowed MCP operation, request/response schema, exact resource scoping, required grant checks and audit event. Prove read and write paths both reject cross-task/project/tenant access. Keep formal review/approval and manual completion human-only. Preserve existing Task state machine semantics; do not let process exit or submission equal Task completion.

## 5. P1 design decisions to close

### D-07 — Remote Git delivery

Specify:
- repository credential source and least-privilege scope;
- how credentials reach the Harness without SEM visibility;
- execution-scoped branch/ref naming and uniqueness;
- baseline commit locking and allowed push semantics;
- remote verification and changed-file computation from Git objects;
- force-push/rebase policy, protected branch behavior, retries and partial push;
- ref retention/cleanup and audit;
- whether Runner-signed local-worktree attestation is needed.

### D-08 — Resource admission and fairness

Specify CPU, memory and workspace-volume reservation units; telemetry freshness; reservation expiry; reconciliation after SEM restart; overcommit policy; concurrency caps per Runner/profile/tenant; queue ordering, starvation prevention, cancellation and supervised-mode constraints. Do not treat telemetry as a perfect guarantee.

### D-09 — Deployment and operations

Specify service topology, network ingress/egress, TLS/mTLS, service identities, secret source/rotation, database migrations, health/readiness, rolling upgrades, compatibility window, observability, log redaction, event/prompt retention, incident response, disaster recovery and operator access. Clarify whether SEM DB needs backup/restore and what data can be rebuilt. Workspace backup remains out of scope.

### D-10 — Implementation architecture and repository ownership

Specify SEM modular-monolith crate/module boundaries, ports/adapters, database repository boundaries, HTTP/WSS adapters, Runner Supervisor contract, AI-PM outbox adapter, configuration ownership, dependency direction and test fixture strategy. Identify every AI-PM change separately from SEM changes. No direct shared database or implicit schema coupling.

### D-11 — Implementation sequence and acceptance

Define ordered milestones only after D-01–D-10 are closed. For every milestone specify:
- source repositories/files/modules;
- migration/API/protocol impact;
- prerequisites and forbidden parallel work;
- unit, integration, contract, concurrency, security and failure-injection tests;
- observable acceptance evidence and rollback/forward-recovery procedure.

## 6. Source compatibility findings already established

- Existing AI-PM `cpk_` credential is reusable and device-wide, and maps to the device owner's HumanActor; it is not a delegated Harness identity.
- Current device registration does not establish a cryptographic Runner public-key identity.
- Existing MCP authorization is human membership / project-scoped in key paths, not an execution grant bound to exact Task/Run/attempt/generation.
- Existing broad MCP permissions do not replace exact per-operation resource authorization.
- The current source has human-only formal review guards; those must remain hard gates.
- Existing remote Git evidence behavior does not prove Runner-local worktree HEAD and needs a separately specified remote evidence contract.

See the AI-PM [Harness identity and business fencing review](https://github.com/luqizheng/ai-pm/blob/docs/sem-02e-architecture-convergence/docs/architecture/server-execution-management/harness-identity-and-business-fencing-review.md).

## D-12 — SEM SDK provider and consumer contract

The user-confirmed provider/consumer direction is: **smark-sem provides and owns the supported SDK; AI-PM consumes it.** The provider/consumer boundary is recorded in [SEM SDK and Consumer Integration Contract](./sem-sdk-and-consumer-integration-contract-draft.md); the proposed three-operation API, error model, signing boundary, retry/idempotency semantics and acceptance suite are in [D-12 SEM SDK Public API Design](./sem-sdk-public-api-design-draft.md).

Required closure:
- Freeze the Rust crate name, workspace placement and distribution/release channel.
- Audit async runtime and HTTP dependency compatibility with AI-PM before selecting the implementation stack.
- Review and ratify the three typed client methods for execution submission, query/reconciliation and release against the final D-04 OpenAPI/JSON Schemas.
- Freeze structured error categories, idempotency behavior, timeout uncertainty and bounded retry primitives.
- Define SDK/API major-version compatibility, support window, deprecation and release notes.
- Decide whether shared protocol models and callback-verification primitives belong in the SDK crate or a companion crate.
- Add SEM schema/fixture validation and AI-PM pinned-SDK bilateral compile/contract CI.

The SDK must not own AI-PM Outbox, database, durable retry scheduling, business retry decisions, Task state or callback transaction. The callback receiver and Inbox remain AI-PM-owned. A source compatibility audit now recommends an isolated `sem-sdk` crate over canonical `sem-protocol`, Tokio 1 + reqwest 0.12/native-tls as a candidate, and internal Kellnr distribution subject to SEM CI access verification. Explicit certificate/public-key pinning must be proven independently from CA-chain validation. See [SEM SDK Source Compatibility Audit](./sem-sdk-source-compatibility-audit.md). The public API proposal is available for bilateral review but is not ratified. This is a Draft contract; no SDK code is authorized.

## 7. Document status vocabulary

- **Normative / Frozen:** approved by user; implement exactly.
- **Draft / Review:** detailed proposal exists; not yet approved.
- **Historical / Superseded:** preserve for audit only; never implement.
- **Open:** no sufficiently complete design yet.
- **Verified in source:** fact confirmed in a named source revision; not a design approval.

No item becomes Normative / Frozen solely because it is written in a draft or linked from a README.

## 8. Final readiness checklist

- [ ] D-01 Runner identity trust chain approved.
- [ ] D-02 Delegated grant/bootstrap approved.
- [ ] D-03 Permanent Runner loss/process isolation approved.
- [ ] D-04 Both wire protocols machine-readable and approved.
- [ ] D-05 All lifecycle/state machines and crash races closed.
- [ ] D-06 MCP operation/resource authorization contract approved.
- [ ] D-07 Remote Git evidence and credentials approved.
- [ ] D-08 Resource admission/fairness approved.
- [ ] D-09 Deployment, security and operations approved.
- [ ] D-10 Implementation architecture and repository ownership approved.
- [ ] D-11 Milestones and acceptance evidence approved.
- [ ] D-12 SEM SDK provider/consumer API, versioning, release and bilateral CI approved.
- [ ] AI-PM and SEM document sets cross-reviewed with no contradictions.
- [ ] User explicitly authorizes implementation.

**Current conclusion: NOT READY FOR DEVELOPMENT.** Continue documentation and review only.


### D-12 review disposition update — 2026-11-25

The SDK provider/consumer direction remains user-confirmed, but the API is **NOT RATIFIED / CHANGES REQUIRED**. The current D-12 review has identified the following hard closure gates:

- D-04 now has a Draft authenticated/pre-authentication error split: authenticated application errors are signed and direction-correlated; pre-authentication 401/early-413 are unsigned and carry no protocol IDs. D04-H78..H85 record the boundary. Deterministic signed-error vectors, normative ratification, replay/freshness, key rotation and live middleware proof remain open.
- Conditional GET 304 must define ETag behavior, signed response semantics and mandatory no-body behavior.
- Tokio/reqwest/native-tls is a compatibility candidate only; integrated SEM workspace resolution and explicit CA/pin/hostname/expiry tests are absent.
- Internal Kellnr is a distribution candidate only; SEM CI publish/read access and immutable release/rollback proof are absent.
- SDK-to-OpenAPI/schema/header/idempotency/error mapping traceability and bilateral AI-PM compile/contract CI are required. AI-PM PR #9's callback Inbox design currently has 44 acceptance cases, but no Rust JCS implementation, migration or PostgreSQL concurrency proof.
- Source audit provenance must distinguish AI-PM master code/manifests from the separate, unmerged AI-PM PR #9 design branch.

See [D-12 Public API Design](./sem-sdk-public-api-design-draft.md) and [SDK Source Compatibility Audit](./sem-sdk-source-compatibility-audit.md). The current reviewed API remains documentation only. No SDK implementation, migration, runtime configuration or merge is authorized.
