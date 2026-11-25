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
- AI-PM→SEM is a versioned internal HTTP/HTTPS contract over the company private network, with durable Outbox/Inbox and idempotent reconciliation; HTTPS is optional in V1 and supports enterprise CA or self-signed certificates. No public internet ingress is provided. Runner↔SEM remains authenticated WSS with the same internal certificate trust options.
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
2. The operator runs `sem-runner register --registry https://sem.internal.example --registration-token <TOKEN> --ca-cert /etc/sem/internal-ca.crt` (or use an explicitly configured certificate/public-key pin for a self-signed endpoint) on the Runner host.
3. Runner generates its own Ed25519 keypair locally; only the public key is sent to SEM.
4. SEM atomically consumes the registration credential, assigns immutable `runner_id`, and binds the public key.
5. The installed Runner authenticates its long-lived outbound WSS connection with challenge-response proof of possession. The registration token is never reused for WSS or MCP.

Authority is split deliberately: SEM owns infrastructure enrollment, Runner identity, key versions, connection/admission state and revocation. AI-PM owns business grants and exact Task/Run authorization. SEM-issued Runner identity is not business authorization.

Platform↔SEM supports HTTP or HTTPS on the private network; HTTPS certificate validation accepts explicitly trusted enterprise/self-signed certificates and never permits silent verification bypass. Runner registration and WSS also accept explicitly provisioned internal trust material. See the transport deployment profile in the architecture README. The same WSS connection is the dispatch channel; SEM must not open a fresh connection or poll Runner for every task. Dispatch eligibility is a derived predicate, not a socket-open boolean. It requires an authenticated current WSS session, fresh application heartbeat, fresh same-boot resource telemetry, healthy Supervisor, accepting-work admission state and sufficient capacity after durable reservations. Transport ping/pong alone is insufficient. A delivery is sent only after reservation and binding epoch are durable; missing ACK or WSS loss causes reconciliation, not blind reassignment.

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

A safety proposal is recorded in [Runner Host Isolation and Permanent-Loss Recovery Draft](./runner-host-isolation-and-permanent-loss-recovery-draft.md). User decision (2026-11-25): V1 Runner OS is Linux-only. The selected V1 architecture candidate is a host-managed systemd transient service per execution on cgroup v2, with Supervisor as a host systemd service and Harness in a distinct unprivileged identity. Windows/non-systemd/cgroup-v1 hosts and Runner containers without a trusted host-side broker are unsupported. This closes the V1 OS-scope choice, but systemd D-Bus idempotency, unit retention/GC, cgroup exit evidence and crash behavior still require Linux integration/failure-injection proof. Permanent host loss is now a user-confirmed V1 operating decision: visible alert + quarantine + auditable on-site operator intervention; no cloud/VM power API or BMC/IPMI integration. The minimal manual-resolution audit/authorization behavior and Linux failure-injection proof remain to be completed.

Specify what constitutes independently verifiable host fencing:
- cloud/VM power-off or revoke compute lease;
- container/VM runtime isolation;
- host agent/management plane proof;
- physical/manual operator procedure where no reliable remote control plane exists.

Define which evidence is trusted, who can issue it, how it is signed/audited, and when SEM may release reservations or allow a new binding. A timeout, WSS disconnect, expired heartbeat or MCP grant revocation is never sufficient.

### D-04 — Complete bilateral protocol

Narrative and machine-readable Draft contracts exist for both directions: [Platform–SEM Execution Message Protocol](../protocol/PLATFORM-SEM-EXECUTION-MESSAGE-PROTOCOL-DRAFT.md), [Runner–SEM WSS Protocol](../protocol/RUNNER-SEM-WSS-PROTOCOL-DRAFT.md), [OpenAPI 3.1](../protocol/openapi/platform-sem-v1-draft.yaml), the Platform–SEM and Runner–SEM JSON Schemas, and the [D-04 acceptance matrix](../protocol/D04-PROTOCOL-ACCEPTANCE-MATRIX.md). Cryptographic algorithm families are selected as Draft baselines: Ed25519 + RFC 9421 + RFC 9530 for Platform↔SEM HTTP; Ed25519 + RFC 8785 JCS for Runner WSS proof-of-possession.

The HTTP response contract now has an explicit candidate split between authenticated application errors and pre-authentication failures. Deterministic signed 404 vectors now cover both Platform GET and SEM callback directions; Python/Node verify exact request context and direction-specific correlation. Unsigned 401/early-413 fixtures are also checked for absence of protocol signature/correlation headers and IDs in the body. Authenticated 400/404/409/412/422/429/500 responses are signed and correlated only to the authenticated Idempotency-Key; pre-authentication 401 and early 413 responses contain no protocol correlation identifiers or response signatures. Application-level 429 is signed and carries Retry-After. OpenAPI defines direction-specific signed error components and a structurally restricted pre-authentication error envelope. D04-H78..H85 cover middleware order, correlation safety, rate limiting and signing failure.

The callback receiver design in [AI-PM PR #9](https://github.com/luqizheng/ai-pm/pull/9) now specifies reuse of `integration.inbound_event`, full-envelope JCS replay identity, exact Inbox column mapping, Run-row lock order, READ COMMITTED conflict recovery and 39 PostgreSQL/JCS acceptance cases. A shared callback envelope vector is pinned to SEM; a Rust canonicalizer candidate is evaluated but not selected. No AI-PM migration, callback route, production JCS dependency or runtime receiver is implemented.

The [D-04 Independent Protocol Review](../protocol/D04-INDEPENDENT-PROTOCOL-REVIEW.md) remains **CHANGES REQUIRED**. Deterministic Python/Node fixtures and schema CI do not prove live HTTP middleware request-context association, response nonce replay storage, reverse-proxy behavior, full signed-error vectors, production Rust JCS integration, two-connection PostgreSQL concurrency, or bilateral callback runtime interoperability. WSS handshake/session lifecycle and producer/receiver evidence mapping also require runtime tests. D-04 remains Draft / P0 OPEN and is not an implementation authorization.

### D-05 — State machines and crash consistency

Detailed proposal: [Lifecycle State Machines and Crash Consistency Draft](./server-execution-management/lifecycle-state-machines-and-crash-consistency-draft.md). It defines the source-aligned AI-PM Task/Run/attempt model, full 31-edge TaskStatus matrix and guards, SEM Execution and Runner Supervisor transition tables, uncertain-state recovery edges, durable-before-effect rules, release/start linearization requirements, independent fencing, Linux systemd/cgroup v2 process-owner profile, Runner event-stream replay and 94 acceptance cases. It remains Draft / Review. Linux V1 architecture candidate now specifies systemd 250+, Type=exec, ExitType=cgroup, RemainAfterExit=yes, CollectMode=inactive, Restart=no, KillMode=control-group, GetUnit/job reconciliation and durable launch tombstones; exact distro behavior still needs integration proof. Independent transition-matrix review, D-04 schemas, the minimal manual-resolution audit/authorization behavior and Linux systemd integration proof remain open. A focused [Linux launch/release/exit-proof challenge addendum](./server-execution-management/d05-linux-launch-release-exit-proof-addendum.md) now makes lost D-Bus reply handling, sole-broker privilege, waiting/running job release behavior, bracketed exit evidence and retention proof obligations explicit. D-05 now has 94 acceptance cases. A D-04 cross-check pins the seven durable Runner message branches and adds negative tests for missing journal cursors. Runner process-exit events now carry immutable evidence_id, evidence_schema_version and a JCS/SHA-256 evidence_digest; SEM persists the complete event before durable-sequence ACK, and Runner retains raw evidence until ACK. No second evidence transport is introduced; D-10 must prove journal durability, digest generation, replay and post-ACK retention. The addendum does not close P0-02/P0-03/P0-04; D-10 Linux failure-injection evidence remains mandatory.

Independent review: [D-05 Independent Architecture Audit](./server-execution-management/d05-independent-architecture-audit.md). Disposition: **CHANGES REQUIRED**. Follow-up edits correct the AI-PM source mapping, strengthen launch/release linearization requirements, recommend a durable Runner event stream, and add ten acceptance cases. Linux systemd/cgroup launch and durable exit proof remain P0 until integration-tested; D-04 machine-readable schemas remain open. Keep PR #3 Draft; no implementation.

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

Specify service topology and private-network ingress/egress; HTTP/HTTPS selection; enterprise CA and self-signed certificate trust provisioning/pinning; mandatory certificate validation; certificate renewal/rotation/overlap/revocation; service identities; request authentication/integrity/replay defense; secret source/rotation; database migrations; health/readiness; rolling upgrades; compatibility window; observability; log redaction; event/prompt retention; incident response; disaster recovery and operator access. Clarify whether SEM DB needs backup/restore and what data can be rebuilt. Workspace backup remains out of scope.

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
- [ ] D-03 V1 permanent-host-loss operating mode (visible alert + quarantine + on-site operator disposition) user-confirmed; minimal manual-resolution audit/authorization behavior and process-isolation proof remain open.
- [ ] D-04 Both wire protocols fully machine-readable, independently validated, cross-repository compatible and approved (initial Draft artifacts exist; not complete).
- [ ] D-05 All lifecycle/state machines and crash races closed (detailed draft exists; open decisions and cross-contract ratification remain).
- [ ] D-06 MCP operation/resource authorization contract approved.
- [ ] D-07 Remote Git evidence and credentials approved.
- [ ] D-08 Resource admission/fairness approved.
- [ ] D-09 Deployment, security and operations approved.
- [ ] D-10 Implementation architecture and repository ownership approved.
- [ ] D-11 Milestones and acceptance evidence approved.
- [ ] AI-PM and SEM document sets cross-reviewed with no contradictions.
- [ ] User explicitly authorizes implementation.

**Current conclusion: NOT READY FOR DEVELOPMENT.** Continue documentation and review only.
