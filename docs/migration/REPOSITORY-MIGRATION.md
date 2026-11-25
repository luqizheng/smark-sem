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


## Additional historical/design documents migrated

The following earlier SEM design and deployment-audit documents were also copied, preserving their historical status:

- `docs/architecture/server-execution-management/decision-record.md`
- `docs/architecture/server-execution-management/deployment-topology.md`
- `docs/architecture/server-execution-management/runner-supervision-and-handoff.md`
- `docs/architecture/server-execution-management/security-model.md`
- `docs/architecture/server-execution-management/domain-model.md`
- `docs/architecture/server-execution-management/state-machines.md`
- `docs/architecture/server-execution-management/testing-and-acceptance.md`
- `docs/architecture/server-execution-management/execution-safety.md`
- `docs/architecture/server-execution-management/protocol-contracts.md`
- `docs/architecture/server-execution-management/session-manager-design.md`
- `docs/architecture/server-execution-management/sem-02d-final-architecture-review.md`
- `docs/architecture/server-execution-management/sem-02d-review-findings-corrective-design.md`
- `docs/architecture/sem-01-deployment-audit/README.md`
- `docs/architecture/sem-01-deployment-audit/migration-recommendation.md`

Older design records are historical inputs. Where they conflict with SEM-02E–02J or later confirmed decisions, the newer reviewed decision/audit material takes precedence. These copies do not imply that old recommendations are still normative.


## Complete source inventory verification

A GitHub directory-level comparison was performed against ai-pm master and the destination main branch after the copy.

- SEM architecture directory: **23 source files; all 23 present in smark-sem**.
- SEM-01 deployment audit directory: **6 source files; all 6 present in smark-sem**.
- SEM-02E–02J convergence/audit documents: copied from the dedicated source branch docs/sem-02e-architecture-convergence.
- No source files were deleted from ai-pm.

The complete 23-file SEM architecture directory is:
- README.md
- code-contract-mapping.md
- consistency-review.md
- decision-record.md
- deployment-topology.md
- domain-model.md
- execution-safety.md
- failure-recovery.md
- migration-roadmap.md
- operational-runbook.md
- protocol-contracts.md
- resource-aware-runner-scheduling.md
- runner-supervision-and-handoff.md
- security-model.md
- sem-02d-closure-design-proposal.md
- sem-02d-final-architecture-review.md
- sem-02d-review-findings-corrective-design.md
- sem-02d-review-package.md
- service-protocol-security-and-persistence.md
- session-manager-design.md
- state-machines.md
- testing-and-acceptance.md
- worker-role-separation.md

The complete 6-file SEM-01 deployment audit directory is:
- README.md
- docker-deployment-analysis.md
- execution-topology.md
- migration-recommendation.md
- session-current-state.md
- worker-loop-inventory.md

## New repository-boundary artifacts

The following documents were authored in smark-sem after source migration:

- docs/architecture/CROSS-REPOSITORY-CODE-OWNERSHIP.md — Platform/SEM/Runner responsibility matrix and source-code disposition.
- docs/protocol/PLATFORM-SEM-RUNNER-PROTOCOL-V1.md — bilateral HTTPS, Outbox/Inbox, Runner Ticket, WSS, Claim, Lease Renewal, process observation, command delivery/ACK, persistence and test contract.

These are new boundary artifacts, not copies. Protocol V1 is the implementation baseline; state-mutating Platform endpoints remain gated by SEM-02J closure and Platform-side review.

## Current completion state

- Historical and design document extraction: **complete for the two inventoried source directories**.
- Code ownership inventory: **documented**.
- Cross-repository protocol V1: **documented; implementation and bilateral review pending**.
- Rust SEM service skeleton: **not created**.
- Runtime code migration: **not started by design**; current Platform-coupled code remains in ai-pm.
- SEM-02J Platform transaction audit: **still Changes Required / Audit In Progress**.
- No Phase 0, no Platform business code changes, no Platform migration changes, and no PR merge were performed in this repository-boundary pass.


Directory comparison details:
- The 23-file SEM architecture source directory and destination have identical filenames. README.md and consistency-review.md have intentional destination-side updates for the standalone-repository ownership/status; all other source documents retain matching blob content.
- All 6 SEM-01 deployment audit files have matching source/destination blob content.
- The destination contains additional SEM-02E–02J review documents and newly authored ownership/protocol documents.

## Modular-monolith skeleton PR

- Draft PR: https://github.com/luqizheng/smark-sem/pull/1
- Branch: feat/sem-modular-monolith-skeleton
- Head: 74adeaad863642972cf825573804584414c510c6
- Scope: Rust workspace, sem-server binary, sem-domain, sem-protocol, sem-application, sem-infrastructure, liveness-only HTTP endpoint and CI.
- GitHub Actions: Format, Test and Clippy passed on the current PR head (including after syncing latest main).
- PR remains Draft and unmerged. The skeleton is not a production-ready service.
