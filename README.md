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

The AI-PM Platform remains authoritative for Project, Task, Run, Lease, Generation, Human Intervention/Consultation, business commands, and audit state. SEM must not connect to or share the Platform PostgreSQL database.

## Integration

- Platform Outbox → authenticated, versioned HTTPS → SEM Inbox
- SEM → authenticated Platform HTTPS APIs for claim, lease renewal, and other authorized operations
- Runner ↔ SEM over authenticated WSS
- Harness → Platform MCP for project/task context and business operations

No distributed transaction and no shared database. Cross-service delivery is idempotent and reconciled.

## Current status

**Architecture migration in progress. No production SEM implementation is declared complete.**

The SEM-02E–02J architecture and transaction-audit documents have been copied into this repository. SEM-02J remains **Changes Required / Audit In Progress**; unresolved findings remain unresolved. Platform-owned code and migrations stay in luqizheng/ai-pm. See [the repository migration record](docs/migration/REPOSITORY-MIGRATION.md), [cross-repository code ownership](docs/architecture/CROSS-REPOSITORY-CODE-OWNERSHIP.md), and [Protocol V1](docs/protocol/PLATFORM-SEM-RUNNER-PROTOCOL-V1.md) for current boundaries and contracts.

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
