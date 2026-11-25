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

The source AI-PM repository contains the ongoing SEM-02J transaction and execution-path audit. Its findings are being migrated as design/audit material; unresolved findings remain unresolved. Platform-owned code and migrations stay in luqizheng/ai-pm.

## Repository structure

- docs/architecture/ — SEM architecture, contracts, audit, decisions
- docs/protocol/ — versioned Platform–SEM and Runner–SEM protocol specifications (to be established)
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
