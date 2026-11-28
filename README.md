# smark-sem

Standalone Server Execution Management (SEM) service for the AI-PM platform.

## Repository boundary

This repository owns the execution infrastructure:

- Runner enrollment, connection and authentication at the SEM edge
- Runner WSS control protocol
- Infrastructure-only execution dispatch and resource admission
- Runtime-control coordination and authenticated Runner process observations
- SEM-local persistence and recovery
- Platform–SEM integration contracts, the supported Rust SDK and SEM architecture documentation

The AI-PM Platform remains authoritative for Project, Task, Run/business execution state, approvals, HIR/Barrier, business commands, business results and audit state. SEM is an execution-message transport and runtime manager: it routes opaque prompts, coordinates Runner runtime commands, records Runner-reported infrastructure observations and releases SEM-side reservations when instructed by AI-PM. Runner Supervisor owns local Harness process start/stop and OS process identity. SEM must not connect to or share the Platform PostgreSQL database, mirror business state, or interpret prompt content.

## Integration

- AI-PM's durable Outbox worker calls SEM through the **Rust SDK provided and versioned by smark-sem**. AI-PM owns Outbox persistence, business authorization and durable retry scheduling; the SDK owns typed SEM API calls, transport/authentication primitives and protocol compatibility.
- AI-PM → SEM uses the versioned HTTP/HTTPS service contract over the company private network. HTTP is permitted only on the restricted internal network; HTTPS supports enterprise CA or explicitly pinned self-signed certificates. Certificate verification must never be disabled.
- SEM → AI-PM reports infrastructure delivery, process and cleanup facts through an AI-PM-owned callback endpoint. SEM owns the event schema and shared conformance fixtures; AI-PM owns callback authentication, Inbox transaction, Run observation and ACK-after-commit.
- SEM ↔ Runner uses authenticated persistent WSS (opaque prompt delivery, runtime control, process/resource observations).
- Harness → AI-PM MCP for all project/task context, business state transitions and business results. SEM does not provide business context or call business Claim/Lease/Task/HIR/Barrier APIs.

No distributed transaction and no shared database. Cross-service delivery is at-least-once, idempotent and reconciled. The SDK does not poll or own the AI-PM Outbox and does not make business retry decisions.

## Current status

**Architecture migration in progress. No production SEM implementation is declared complete.**

SEM-02E–02J and the original V1 domain/state/security/recovery designs are historical source-audit material; they are not implementation contracts. The active review baseline is indexed in [SEM Architecture README](docs/architecture/server-execution-management/README.md) and tracked by the [Bilateral Documentation Completion Register](docs/architecture/SEM-DOCUMENTATION-COMPLETION-REGISTER.md). Start with the [authority-boundary model](docs/architecture/SEM-AUTHORITY-BOUNDARY-AND-EXECUTION-MESSAGE-MODEL.md), [SEM SDK and Consumer Integration Contract](docs/architecture/sem-sdk-and-consumer-integration-contract-draft.md), [draft SEM SDK public API](docs/architecture/sem-sdk-public-api-design-draft.md), [SDK source compatibility audit](docs/architecture/sem-sdk-source-compatibility-audit.md), [replacement execution-message protocol](docs/protocol/PLATFORM-SEM-EXECUTION-MESSAGE-PROTOCOL-DRAFT.md), and [identity/lifecycle/fencing/delivery contract](docs/protocol/EXECUTION-IDENTITY-LIFECYCLE-FENCING-DELIVERY-CONTRACT-DRAFT.md). Platform-owned code and migrations remain in luqizheng/ai-pm.

## Confirmed operating constraints

- Runner supervision defaults to unattended; supervised mode is opt-in.
- Runner CPU, memory and workspace-volume telemetry informs SEM capacity admission and concurrency.
- Workspace/worktree backups are not required; durable process registry and execution evidence are operational state, not workspace backup.
- Each repository has one authoritative Git `origin`.
- RabbitMQ exists as a separate single-instance service without clustering. SEM correctness must not depend on it; any future use is limited to optional non-authoritative wake-up/notification acceleration.

## Implementation status

- Rust modular-monolith skeleton: [Draft PR #1](https://github.com/luqizheng/smark-sem/pull/1); Format, Test and Clippy pass on the current head.
- The skeleton exposes only liveness and does not yet connect to Platform or SEM PostgreSQL.
- No production Runner WSS, service authentication, dispatch, process supervision or persistence implementation exists yet.

## Repository structure

- docs/architecture/ — SEM architecture, contracts, audit, decisions
- docs/migration/ — repository-boundary migration record
- docs/protocol/ — active replacement Platform–SEM message protocol and execution identity/lifecycle/fencing/delivery contract
- src/ — SEM modular-monolith implementation (not yet migrated/created)
- tests/ — SEM unit, integration, contract, and concurrency tests

## Non-goals

- No Platform database access from SEM
- No duplicate authority for Run/Lease/Generation/HIR
- No Runner-side Platform MCP claim/command polling control plane
- No Redis/Kafka/RabbitMQ requirement for execution safety
- No Workspace backup; workspaces are disposable/rebuildable and are not process-exit evidence

## Development policy

Architecture and transaction contracts must be reviewed before implementation. The initial service should be a modular monolith, not a fleet of microservices.

**Security review gate:** The protocol and companion contract drafts cover delegated Harness identity, a proposed Runner-bound bootstrap, independent AI-PM authorization-generation vs SEM binding-epoch fencing, uncertain-Runner quarantine, idempotent lifecycle messaging, and the distinction between delivery submission and Task completion. These are review requirements, not implemented features.
