# Cross-Repository Code Ownership and Migration Plan

- Status: Architecture baseline for implementation planning; no runtime code moved.
- Repositories: luqizheng/ai-pm (Platform) and luqizheng/smark-sem (SEM).
- Source inventory baseline: ai-pm master as inspected during this migration.
- This document supersedes older worker-role notes wherever they imply that SEM is merely an ai-pm-worker role or shares the Platform process/database.

## 1. Binding ownership rules

1. Platform is the sole authority for Project, Task, Run, Lease, Generation, Scheduling Shield, Execution Barrier, HIR/Consultation, business command state, business audit and business event state.
2. SEM is the sole Runner control-plane coordinator after cutover. It owns Runner connections, tickets consumed, dispatch operations, WSS delivery ledgers, local process observations, resource snapshots/reservations and SEM-local recovery.
3. Platform and SEM are separate deployable services, separate repositories and separate PostgreSQL databases. SEM has no Platform database credentials and no direct SQL access to Platform.
4. Runner Supervisor ↔ SEM WSS is the only Runner control channel after cutover. Harness ↔ Platform MCP remains the project/business channel.
5. A Platform API response can authorize a state transition only when the Platform transaction has committed it. SEM transport ACKs and Runner ACKs are not substitutes for Platform business state.
6. No shared filesystem, shared SQL, distributed transaction, or second Run/Lease authority.
7. Existing source code is not moved mechanically. Platform SQL transaction logic remains in ai-pm; SEM process and connection logic is reimplemented behind the new service contract in smark-sem.

## 2. Platform-owned code in ai-pm

| Existing source area | Responsibility retained in Platform | Required change for cutover |
|---|---|---|
| apps/pm-api | Public product API, authentication, MCP mounting, internal Platform service API | Add narrowly scoped service-to-service endpoints and Runner ticket issuance; do not allow SEM to use ordinary human endpoints |
| crates/pm-application/src/run_dispatch/claim.rs and related dispatch modules | Candidate eligibility, atomic Claim, Lease issuance, Generation increment, Task/Project gates | Expose through an application service called by the Platform internal API; retain the full transaction and canonical lock protocol |
| crates/pm-application/src/run_executor.rs | Platform-side Run/Task business state, audit/event writes, terminalization decisions | Remove local process orchestration responsibility; replace SEM-owned process calls with API-driven evidence/result transitions |
| crates/pm-application/src/worker_command.rs | Command creation, command state machine, authorization, generation fencing and business ACK decision | Add service API operations for delivery/ACK; SEM may track transport delivery only |
| Interaction / Continuation / HIR / Barrier modules | Human interaction and governance authority, Task waiting, execution barrier and successor authorization | Complete SEM-02J lock/transaction audit and expose narrowly scoped operations; generic Consultation must not release HIR/Barrier |
| crates/pm-infrastructure/src/outbox* | Platform transactional Outbox, single Platform consumer and event catalog | Add SEM delivery handler; only acknowledge after SEM Inbox has durably accepted event |
| crates/pm-mcp and MCP tools | Harness project/task context, progress, interaction, result and knowledge business operations | Remove/fail-close Runner-only claim, reacquire, command poll/ACK control tools after SEM cutover; preserve Harness business tools |
| Platform migrations and DB functions | All Platform-owned schema and constraints | Keep in ai-pm; add/alter only after SEM-02J audit and Platform API design are approved |
| apps/ai-pm-worker | Analysis, repo import, review, failure judgement, conversation/consultation orchestration and Platform Outbox consumption | Retain Platform-only loops; remove process spawn/monitor/terminate and SEM dispatch loops after cutover |

Platform code remains in ai-pm even when a SEM operation triggers it. SEM calls Platform APIs; it does not import Platform crates or reuse Platform database adapters.

## 3. SEM-owned code in smark-sem

The following are new SEM modules, not copied Platform modules.

| Proposed module | Owns | Explicitly does not own |
|---|---|---|
| sem-api | Platform HTTPS ingress, service JWT validation, Inbox acceptance, health/readiness | Platform business rules or Platform DB |
| sem-platform-client | Signed service JWT, Platform API client, request idempotency and timeout/unknown-outcome handling | Direct SQL or direct Outbox reads |
| sem-inbox | Durable event_id deduplication, inbox processing state and retry | Platform Outbox table |
| sem-runner-gateway | WSS handshake, one-time ticket consumption, connection epoch, revocation revalidation, message validation | Run/Lease authority |
| sem-session | Runner session lifecycle, supervised/unattended mode, reconnect and reconciliation coordination | Human presence inference from online state |
| sem-dispatch | Runner selection, capability matching, atomic resource reservation, durable dispatch operation and crash recovery | Candidate authorization / Lease issuance |
| sem-process | Harness spawn, poll, terminate, OS process identity, process-exit evidence and local evidence spool | Platform Run terminalization or HIR decisions |
| sem-workspace | Disposable workspace/worktree setup and reclamation on the Runner host | Workspace backup or business knowledge authority |
| sem-persistence | SEM PostgreSQL schema, migrations and repository adapters | Platform schema, mirrored Run state or Platform credentials |
| sem-protocol | Versioned HTTPS DTOs, Outbox event envelope, WSS message envelope and schema validation | Duplicated Platform domain entities |
| sem-observability | Structured logs, metrics, traces and redaction | Lease token persistence or process-exit inference from heartbeat |

Initial deployment is one modular-monolith SEM service plus its independent PostgreSQL service/deployment dependency. Modules are code boundaries, not eight microservices.

## 4. Runner-owned code

The Runner is a separately installed client, not a child process of SEM.

Runner Supervisor owns:
- Device key/credential protection and Platform ticket acquisition.
- WSS connection/reconnection and local durable evidence spool.
- Harness process spawn/supervision/termination on its own machine.
- OS process identity and exit observation.
- CPU, memory and workspace-volume resource sampling.
- Local workspace lifecycle.
- Forwarding Harness business calls to Platform MCP where applicable.

Runner must not:
- Claim or reacquire Runs directly through Platform MCP.
- Poll Platform commands or ACK them through Platform MCP after cutover.
- Independently change Lease/Generation or infer successful Claim.
- Treat WSS heartbeat, Agent Activity, resource telemetry, process cleanup intent, or workspace deletion as E3 process-exit evidence.
- Start a second Harness for a Run without an explicit Platform authorization and SEM dispatch operation.

## 5. Existing code disposition

| Existing code | Disposition |
|---|---|
| apps/ai-pm-runner/src/runner_loop.rs and mcp.rs | Refactor into Runner Supervisor WSS client + local process supervisor. Remove MCP claim/reacquire/command polling/ACK paths. Keep Harness business MCP configuration and result flow as separately authorized. |
| crates/pm-application/src/run_executor.rs | Do not move. Split Platform business transaction operations from SEM process lifecycle orchestration. |
| crates/pm-infrastructure/src/codex_executor.rs | Use as behavioral/reference input for a new SEM process adapter; do not copy its Platform-coupled orchestration assumptions blindly. |
| crates/pm-application/src/run_dispatch/claim.rs | Keep in Platform. Wrap in Platform API application service; never port its SQL into SEM. |
| crates/pm-application/src/worker_command.rs | Keep in Platform. Add transport-facing API; SEM records delivery facts, Platform decides business ACK state. |
| apps/ai-pm-worker/src/main.rs | Keep Platform loops and sole Outbox consumer. Remove SEM execution loops only after new SEM service is deployed and cutover gates pass. |
| crates/pm-mcp | Keep Harness business MCP. Runner control tools become fail-closed/deprecated and are removed after all clients migrate. |
| Platform migrations | Never migrate into smark-sem. SEM gets a separate schema/migration chain for its own seven tables. |

## 6. SEM-local persistence boundary

The initial SEM database is limited to these seven logical tables:

1. inbox_event
2. runner_connection
3. runner_ticket_use
4. dispatch_operation
5. command_delivery
6. platform_delivery
7. process_observation

Runner resource snapshots and reservations live in runner_connection and dispatch_operation; do not add an eighth table without a documented need. These records are not replicas of Platform Run/Lease/Generation/HIR state.

## 7. Cutover sequence and gates

1. Close SEM-02J Platform transaction audit, including full migration/constraint inventory, canonical lock order and deterministic concurrency tests.
2. Approve the bilateral protocol contract in this repository and corresponding Platform API ownership in ai-pm.
3. Implement Platform service endpoints and Outbox producer/handler in ai-pm; add Platform-side API/transaction tests.
4. Implement SEM modular monolith, SEM DB and WSS gateway in smark-sem; add SEM-local tests.
5. Implement Runner Supervisor WSS client and local process evidence in the Runner codebase (currently under ai-pm until separately extracted).
6. Pass bilateral contract tests, crash-window tests, E1–E6 safety tests, duplicate/reorder/reconnect tests, resource reservation races and negative authority tests.
7. Enable SEM dispatch for a controlled environment. Verify Platform Outbox remains single-consumer and old Runner MCP control paths fail closed.
8. Remove legacy Platform worker process execution and Runner MCP control paths only after production-equivalent acceptance. Do not run both dispatch authorities concurrently.

## 8. Non-goals for this migration

- Do not create a separate protocol-only repository in V1.
- Do not create multiple SEM microservices.
- Do not add Redis, Kafka or a RabbitMQ cluster. The existing RabbitMQ single instance is not an execution authority or a required SEM dependency.
- Do not back up disposable workspaces.
- Do not modify Platform migrations or business code as part of this documentation-only repository-boundary pass.
