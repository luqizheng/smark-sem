# Server Execution Management (SEM) — Architecture Review Baseline

> **Status: Architecture convergence in progress — documentation only.** This directory is the SEM architecture source of truth in `luqizheng/smark-sem`. No implementation, database migration, runtime configuration change, Phase 0 or merge is authorized by these drafts.

## 1. Current architecture direction

SEM is an independently deployable infrastructure service in the AI-PM dependency stack. It transports opaque execution messages and manages Runner/Harness runtime infrastructure. It does **not** own or interpret AI-PM business workflows.

- AI-PM owns Project, Task, business Run/attempt, business authorization, Task transitions, review/acceptance, and the decision that a runtime is no longer needed.
- SEM owns its execution delivery ledger, Runner registration/connectivity, capability and supervision metadata, resource telemetry/reservations, binding epochs, and infrastructure delivery/release observations.
- Runner Supervisor owns local Harness process launch, process identity, stop/termination and positive process-exit observation.
- Harness obtains business context and performs business operations directly through AI-PM MCP. Harness must not obtain Task context or mutate Task state through SEM.
- SEM treats prompt/body and AI-PM authorization bootstrap material as opaque bytes. It may enforce transport/routing/size/encryption/retention constraints but must not parse business meaning or turn business payload fields into dispatch authority.

## 2. Ownership boundary

| Concern | Authority |
|---|---|
| Task / Requirement / Project / approval / acceptance / HIR / business audit | AI-PM |
| Business Run/attempt and authorization_generation | AI-PM |
| SEM execution_id, delivery/release ledger and binding_epoch | SEM |
| Runner registration, capability, supervision mode and resource telemetry | SEM |
| Local process identity, process start/exit evidence and local stop lifecycle | Runner Supervisor |
| Harness Task context, progress and result submission | AI-PM MCP |
| Prompt/body business meaning | Opaque to SEM |

SEM must not connect to or share the AI-PM PostgreSQL database. SEM has its own database for infrastructure facts only. No Task, Requirement, approval, HIR, Barrier or business Run state is mirrored into SEM.

## 3. Confirmed deployment and operating constraints

- AI-PM ↔ SEM: versioned HTTPS service contract with durable Outbox/Inbox and idempotent reconciliation.
- Runner ↔ SEM: authenticated persistent WSS connection for delivery and infrastructure observations.
- The two services use independent databases; no cross-database transaction is assumed.
- Platform Outbox has one authoritative consumer in AI-PM. SEM does not consume the Platform database directly.
- RabbitMQ already exists as a separate single-instance service without clustering. It is not a required authority or correctness dependency for SEM; it may only be considered later for non-authoritative wake-up/notification acceleration.
- Runner supervision defaults to **unattended**. A supervised mode is optional and must be explicit.
- Runner reports CPU, memory and workspace-volume capacity/availability; SEM uses fresh telemetry plus its own reservations for admission/concurrency.
- Workspace/worktree backup is not required. Process registry and durable execution evidence are operational state, not workspace backups.
- Each repository has one authoritative Git `origin`.
- SEM must not infer process exit from heartbeat loss, WSS disconnect, timeout, missing workspace or command receipt.

## 4. Normative review documents

0. [Bilateral Documentation Completion Register](../SEM-DOCUMENTATION-COMPLETION-REGISTER.md) — authoritative development gate, P0/P1 decision register and readiness checklist.

These documents are the active design-review set. They are still drafts and must be reconciled before implementation.

1. [SEM Authority Boundary and Execution Message Model](../SEM-AUTHORITY-BOUNDARY-AND-EXECUTION-MESSAGE-MODEL.md) — service responsibility and opaque business payload boundary.
1.4. [Runner Host Isolation and Permanent-Loss Recovery Draft](../runner-host-isolation-and-permanent-loss-recovery-draft.md) — process containment, independent host fencing and quarantine.
1.6. [Delegated Harness Grant and Credential Broker Draft](../delegated-harness-grant-and-credential-broker-draft.md) — exact attempt grant, one-time bootstrap, short-lived MCP token and local broker.
1.5. [Runner Enrollment and Cryptographic Identity Draft](../runner-enrollment-and-cryptographic-identity-draft.md) — Runner proof of possession, AI-PM trust record and WSS identity.
2. [Platform–SEM Execution Message Protocol Draft](../../protocol/PLATFORM-SEM-EXECUTION-MESSAGE-PROTOCOL-DRAFT.md) — bilateral message directions, envelopes, delivery and release.\n2.1. [Runner–SEM WebSocket Protocol and Dispatch Contract Draft](../../protocol/RUNNER-SEM-WSS-PROTOCOL-DRAFT.md) — WSS authentication, heartbeat, resource telemetry, delivery ACK, reconnect/replay and dispatch readiness.
3. [Lifecycle State Machines and Crash Consistency Draft](./lifecycle-state-machines-and-crash-consistency-draft.md) — D-05 state tables, durable transitions, crash recovery and acceptance matrix.\n4. [Execution Identity, Lifecycle, Fencing and Delivery Contract Draft](../../protocol/EXECUTION-IDENTITY-LIFECYCLE-FENCING-DELIVERY-CONTRACT-DRAFT.md) — delegated Harness identity, three lifecycles, process fencing and Git evidence.
5. [Consistency Review](./consistency-review.md) — source-audit findings and cross-document invariants.
6. [Code Contract Mapping](./code-contract-mapping.md) — current source responsibilities and candidate adapter boundaries.
7. [Repository Migration Record](../../migration/REPOSITORY-MIGRATION.md) — repository ownership and document migration history.

## 5. Required design packages still to close

- Runner enrollment and key trust: independently verifiable Runner identity, key rotation, revocation and recovery.
- Delegated Harness credential bootstrap: ticket format, redemption endpoint, credential broker IPC, token storage, expiry and revocation.
- Complete wire contract: canonical OpenAPI/JSON Schema, all request/event/ack/error envelopes, version negotiation and compatibility.
- Lifecycle and recovery: durable state machines, duplicate/out-of-order messages, process start/exit, uncertain Runner quarantine, release/start races and host isolation.
- Resource admission: telemetry freshness, reservations, concurrency model, disk pressure and starvation/fairness policy.
- Git delivery: execution-scoped ref, credential provisioning, verification, cleanup and trust boundaries.
- Operations: deployment topology, secrets, TLS, health/readiness, observability, retention, disaster recovery and operator procedures.
- Implementation plan: repo ownership, module/port boundaries, dependency graph, ordered milestones and measurable acceptance tests.

## 6. Historical documents

Older SEM-02E–02J, V1 domain/state/security/recovery/runbook/testing and Protocol V1 documents describe a superseded Platform Claim/Lease/Task/HIR/Barrier control-plane model. They are retained for audit and migration traceability only. Each historical document is marked accordingly; none is an implementation source. When a historical statement conflicts with the active review documents above, the active authority-boundary direction governs.

## 7. Development gate

Development may begin only after:
- all required design packages above are complete;
- AI-PM and SEM contracts are reviewed together and have no unresolved ownership or wire-level contradictions;
- security and failure-recovery invariants have explicit acceptance tests;
- implementation sequence, rollback/forward-recovery strategy and operational readiness criteria are approved;
- the user explicitly authorizes the implementation phase.

Until then, work remains documentation and architecture review only.
