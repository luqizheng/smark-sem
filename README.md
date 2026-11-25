# smark-sem

Standalone Server Execution Management (SEM) service for the AI-PM platform.

## Repository boundary

This repository owns the execution infrastructure:

- Runner connection and authentication at the SEM edge
- Runner WSS control protocol
- Session and dispatch coordination
- Process supervision and process observations
- SEM-local persistence and recovery
- Platform–SEM integration contracts and SEM architecture documentation

The AI-PM Platform remains authoritative for Project, Task, Run/business execution state, approvals, HIR/Barrier, business commands, business results and audit state. SEM is an execution-message transport and runtime manager: it routes opaque prompts, supervises Runner/Harness processes, records infrastructure observations and releases execution resources when instructed by AI-PM. SEM must not connect to or share the Platform PostgreSQL database, mirror business state, or interpret prompt content.

## Integration

- AI-PM Platform Outbox → authenticated, versioned HTTPS → SEM Inbox (execution request, opaque prompt body, release instruction)
- SEM ↔ Runner over authenticated WSS (opaque prompt delivery, runtime control, process/resource observations)
- Harness → AI-PM MCP for all project/task context, business state transitions and business results
- SEM → AI-PM reports infrastructure delivery, process and cleanup facts only; it does not call business Claim/Lease/Task/HIR/Barrier APIs

No distributed transaction and no shared database. Cross-service delivery is idempotent and reconciled.

## Current status

**Architecture migration in progress. No production SEM implementation is declared complete.**

The SEM-02E–02J architecture and transaction-audit documents have been copied into this repository. SEM-02J remains **Changes Required / Audit In Progress**; unresolved findings remain unresolved. Platform-owned code and migrations stay in luqizheng/ai-pm. See [the repository migration record](docs/migration/REPOSITORY-MIGRATION.md), [cross-repository code ownership](docs/architecture/CROSS-REPOSITORY-CODE-OWNERSHIP.md), and [the authority-boundary decision](docs/architecture/SEM-AUTHORITY-BOUNDARY-AND-EXECUTION-MESSAGE-MODEL.md). The previous [Protocol V1](docs/protocol/PLATFORM-SEM-RUNNER-PROTOCOL-V1.md) is superseded and retained only as historical material pending replacement wire schemas.

## Implementation status

- Rust modular-monolith skeleton: [Draft PR #1](https://github.com/luqizheng/smark-sem/pull/1); Format, Test and Clippy pass on the current head.
- The skeleton exposes only liveness and does not yet connect to Platform or SEM PostgreSQL.
- No production Runner WSS, service authentication, dispatch, process supervision or persistence implementation exists yet.

## Repository structure

- docs/architecture/ — SEM architecture, contracts, audit, decisions
- docs/migration/ — repository-boundary migration record
- docs/protocol/ — [Platform–SEM–Runner Protocol V1](docs/protocol/PLATFORM-SEM-RUNNER-PROTOCOL-V1.md)
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
