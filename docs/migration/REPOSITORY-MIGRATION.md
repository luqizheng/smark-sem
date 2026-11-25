# SEM Repository Migration Record

- Destination: `luqizheng/smark-sem`
- Source: `luqizheng/ai-pm`
- Source branch for SEM-02E–02J documents: `docs/sem-02e-architecture-convergence`
- Migration type: controlled repository-boundary extraction
- Status: **Documentation baseline migrated; runtime implementation not yet migrated**

## Ownership after migration

### Owned by smark-sem

- SEM architecture and design decisions
- SEM service API and Runner WSS protocol specifications
- SEM database schema design (SEM-local database only)
- Runner connection/session lifecycle
- Dispatch coordination and resource-aware scheduling
- Harness process supervision and process observations
- SEM recovery, delivery ledgers, and SEM integration tests

### Remains owned by ai-pm

- Platform Project, Task, Run, Lease, Generation and HIR state machines
- Platform PostgreSQL schema and migrations
- Platform MCP business tools
- Platform Outbox producer and Platform HTTPS API implementation
- Platform-side transaction/locking changes required to make the new contract safe
- Platform-side removal or fail-closed treatment of legacy Runner MCP claim/command paths

SEM must not copy or reimplement Platform authority. It must call the Platform's versioned HTTPS APIs.

## Documents migrated in this initial pass

The following files were copied into the same relative paths under this repository:

- `docs/architecture/server-execution-management/README.md`
- `docs/architecture/server-execution-management/sem-02e-architecture-convergence.md`
- `docs/architecture/server-execution-management/sem-02e-review-package.md`
- `docs/architecture/server-execution-management/sem-02f-executable-physical-and-protocol-contracts.md`
- `docs/architecture/server-execution-management/sem-02g-database-and-api-contract-draft.md`
- `docs/architecture/server-execution-management/sem-02h-ddl-integrity-and-transaction-review.md`
- `docs/architecture/server-execution-management/sem-02i-corrected-platform-schema-and-process-api-candidate.md`
- `docs/architecture/server-execution-management/sem-02j-transaction-and-execution-path-closure-review.md`
- `docs/architecture/server-execution-management/consistency-review.md`
- `docs/architecture/server-execution-management/code-contract-mapping.md`

These are source-preserving copies. Their design status and unresolved findings are unchanged. In particular, SEM-02J remains an audit with open findings; the migration does not approve implementation.

## Runtime code disposition

No independent SEM runtime implementation was identified in the source repository to move as-is. The existing Platform Worker, Run executor, MCP claim/reacquire/command paths, Platform database access, and Platform migrations are not SEM-owned code. They remain in `ai-pm` until the replacement Platform–SEM contracts are approved and a deliberate cutover is implemented.

Do not mechanically move `apps/ai-pm-worker`, `crates/pm-application`, `crates/pm-infrastructure`, or Platform migrations into this repository. These contain Platform authority and legacy execution paths that must be redesigned against the SEM boundary.

## Required next migration work

1. Finish SEM-02J's complete Platform transaction and execution-path audit in `ai-pm`; the Platform lock protocol and state-machine repairs remain Platform work.
2. Finalize the cross-repository HTTPS, Outbox/Inbox, WSS and process-observation contracts. Promote only reviewed contracts to normative protocol documents.
3. Inventory all SEM-01 deployment audit and SEM-specific design documents, then migrate the remaining relevant material with source provenance.
4. Establish a Rust modular-monolith service skeleton in this repository only after the contracts are approved.
5. Implement SEM-local persistence and control plane here; implement Platform API/outbox and legacy-path cutover in `ai-pm`.
6. Add bilateral contract tests and end-to-end tests across the two repositories.

## Safety constraints

- No shared database and no SEM direct Platform PostgreSQL connection.
- Platform remains the only authority for Run/Lease/Generation/HIR.
- SEM is the sole Runner control-plane coordinator after cutover.
- Runner WSS is the only Runner control channel; Harness retains Platform MCP for business operations.
- No distributed transaction.
- RabbitMQ is an existing independent single instance, not a required safety dependency or authority.
- Workspace is disposable and is not backed up; workspace loss is not process-exit evidence.
- Do not start Phase 0 or claim production readiness until the transaction audit and protocol review are closed.
