# Cross-Repository Code Ownership and Migration Plan

- Status: **User-confirmed authority boundary; implementation mapping pending review**.
- Repositories: luqizheng/ai-pm (Platform) and luqizheng/smark-sem (SEM).
- This document supersedes earlier ownership plans that made SEM a proxy for Platform Claim, Lease Renewal, business command ACK, Task/HIR/Barrier, or business completion.

## 1. Binding ownership rules

1. AI-PM Platform is the sole authority for Project, Task, Task status, business Run state, requirements, acceptance criteria, approvals, HIR, Barrier, business commands/results, retry/successor decisions and business audit.
2. SEM is an independent execution-message transport and runtime-management service. It receives opaque execution requests/prompts, routes them to infrastructure-eligible Runners, coordinates delivery/release messages, records Runner-reported process/resource facts, and reports infrastructure status.
3. Harness obtains Task context and performs all business reads/writes directly through independently authenticated AI-PM MCP. SEM never supplies business context and never mutates business state.
4. AI-PM decides when a Task is complete/cancelled and explicitly instructs SEM to release the associated execution resources. SEM forwards the release instruction; Runner Supervisor performs local cleanup and reports process facts through SEM. Cleanup does not decide Task completion.
5. Runner checks/starts the Harness and injects the prompt. Runner reports delivery/process/resource facts to SEM. Harness MCP operations go directly to AI-PM.
6. Platform and SEM are separate deployable services, separate repositories and separate PostgreSQL databases. SEM has no Platform DB credentials or direct SQL access.
7. A Task lifecycle and a SEM Execution lifecycle are separate state machines. Opaque execution/correlation IDs associate them without making SEM a mirror of Task/Run state.
8. No shared filesystem, shared SQL, distributed transaction, or second business authority.

## 2. Canonical communication paths

- AI-PM Platform Outbox → authenticated, versioned HTTPS → SEM Inbox: execution request, opaque prompt body/reference, release/stop instruction and explicitly scoped infrastructure control.
- SEM ↔ Runner Supervisor over authenticated WSS: prompt delivery, transport receipt, Harness launch request, release/stop request, heartbeat, resource telemetry, process identity/exit observations and cleanup result.
- Harness ↔ AI-PM MCP: Task lookup, project/requirement/design context, progress, Task state transitions, business interactions and business result submission.
- SEM → AI-PM infrastructure reporting API: delivery, process and resource/cleanup observations only. It must not be a proxy for Platform Claim, Lease Renewal, Task transition, business command ACK, HIR, Barrier or business-result mutation.
- RabbitMQ remains an existing separate single-instance service without clustering. It is not required for correctness and is not an authority. It may be considered later for non-authoritative wake-up acceleration only.

## 3. AI-PM-owned code in ai-pm

AI-PM retains:
- Public product APIs, authentication, authorization, Project/Task/requirements/design domain services and PostgreSQL.
- All Task status transitions, business Run/approval/governance semantics, HIR, Barrier, retry/successor and business result validation.
- AI-PM MCP tools used by Harness for context retrieval and business operations.
- Transactional Outbox producer and authenticated Platform-side ingress/reporting endpoints.
- Business audit/event records and the decision that a Task is complete.

Existing implementation mapping is **not yet approved**. The following source areas require a fresh ownership audit rather than a mechanical migration:
- Run dispatch/claim modules: determine which parts are true business authorization/state transitions and which are legacy process scheduling. Business authority stays in Platform; SEM must not become a proxy that independently grants it.
- Run executor and Worker loops: separate Platform business transitions/audit/outbox from local Harness process spawn/monitor/terminate responsibilities.
- WorkerCommand and Runner MCP tools: classify each operation as business state mutation or infrastructure transport/runtime control. Preserve business operations in AI-PM; move only infrastructure control to SEM/Runner.
- Interaction, Continuation, HIR and Barrier: retain all business semantics in AI-PM. SEM receives only explicit infrastructure instructions and reports facts.
- Runner/Harness integration: preserve Harness business MCP access; remove the assumption that Runner must poll Platform MCP for dispatch/control.

No code or migration changes are authorized until this mapping is reviewed.

## 4. SEM-owned code in smark-sem

| Proposed module | Owns | Explicitly does not own |
|---|---|---|
| sem-api | Authenticated Platform ingress, Inbox acceptance, infrastructure reporting endpoint | Platform business rules or Platform DB |
| sem-inbox | Durable message acceptance, deduplication, retry and replay | Platform Outbox table or business event authority |
| sem-runner-gateway | Authenticated WSS, connection identity/epoch, reconnect and revocation | Task/Run/Lease authority |
| sem-session | Runner session and infrastructure availability lifecycle | Human approval or Task status |
| sem-dispatch | Infrastructure-eligible Runner selection, capacity admission, atomic resource reservation and durable prompt delivery operation | Business Task eligibility, Claim, retry or approval |
| sem-prompt-delivery | Opaque prompt/body delivery and transport receipt tracking | Parsing prompts or deriving Task semantics |
| sem-runtime | Runtime-control message coordination, Runner-reported process/cleanup observations, infrastructure uncertainty and orphan reconciliation | Local OS process ownership, business Run terminalization or Task completion |
| sem-resources | CPU/memory/disk telemetry, capacity snapshots and reservations | Business priority or Task status |
| sem-persistence | SEM PostgreSQL schema and repository adapters | Mirrored Task/Run/Lease/HIR/Barrier state |
| sem-protocol | Versioned HTTPS/WSS transport DTOs and schema validation | Duplicated Platform domain entities |
| sem-observability | Logs, metrics, traces, redaction and infrastructure diagnostics | Business result judgment |

Initial deployment remains one modular-monolith SEM service plus its independent PostgreSQL dependency. Modules are code boundaries, not microservices.

## 5. Runner and Harness ownership

Runner Supervisor owns:
- Device identity and secure connection to SEM.
- WSS connection/reconnection and local delivery/process evidence spool.
- Harness availability check, process launch/attach, prompt injection and local process supervision.
- OS process identity and exact process-exit observation.
- CPU, memory and workspace-volume resource sampling.
- Local disposable workspace lifecycle.
- Installing/configuring the AI-PM MCP integration for Harness, without impersonating a user or reusing SEM credentials.

Harness owns execution of the prompt and interacts with AI-PM business capabilities only through authenticated AI-PM MCP. The MCP identity must be scoped and authorized by AI-PM on every operation.

Runner/Harness must not:
- Treat SEM transport ACK as Task status or business completion.
- Treat process exit code zero as Task completion.
- use SEM service identity as a Platform human/project identity.
- Start duplicate Harness processes for one execution generation.
- Infer process death from heartbeat loss, PID absence without identity proof, workspace deletion or cleanup intent.

## 6. SEM-local persistence boundary

SEM persistence is limited to infrastructure and transport records, for example:
1. inbox_event
2. runner_connection
3. execution_delivery
4. execution_process
5. resource_snapshot / resource_reservation
6. infrastructure_outbox or platform_delivery

Names and exact table count are candidates, not approved DDL. SEM must not persist a business mirror of Task status, Project, Task/Run approval, HIR, Barrier, business command state or business results. It may retain opaque execution_id, correlation_id, delivery IDs and execution generation/epoch for idempotency and stale-message fencing.

## 7. Lifecycle and failure boundaries

- AI-PM Task completion is committed by AI-PM through its business rules/MCP; it then sends SEM a release instruction.
- SEM release is idempotent and generation-fenced. It asks Runner to stop/close the exact Harness process, waits for the configured graceful window, escalates if policy permits, and reports cleanup outcome.
- Natural process exit or non-zero exit is reported as infrastructure evidence. AI-PM decides the business consequence.
- Runner disconnect or missing heartbeat means infrastructure uncertainty, not proven process death.
- Task completed while SEM is still releasing is valid. SEM failed while Task remains non-terminal is also valid.
- Workspaces are disposable/rebuildable and are not backed up. Workspace loss is not process-exit evidence.
- Runner defaults to unattended; supervised mode remains explicit.
- Each Git repository has one authoritative origin.

## 8. Cutover sequence and gates

1. Reconcile every SEM-02E–02J document and ADR with the authority boundary.
2. Inventory current ai-pm APIs, MCP tools, Worker loops, Runner control paths and database entities. Classify each as business authority, transport, runtime/process, or obsolete.
3. Replace the old Protocol V1 Claim/Lease/business-command proxy contract with opaque execution request/delivery/release/runtime-observation schemas.
4. Specify Harness MCP identity provisioning, project scoping, expiry, revocation and negative authorization tests.
5. Define execution ID/generation fencing, duplicate delivery prevention, stale release protection, process identity and orphan reconciliation.
6. Implement Platform-owned business changes and SEM infrastructure changes only after bilateral contract review and explicit implementation authorization.
7. Pass bilateral contract tests, duplicate/reorder/reconnect tests, process crash/exit tests, release idempotency tests, MCP authorization tests and resource reservation race tests.
8. Cut over without running two competing dispatch/runtime authorities. Remove obsolete paths only after acceptance proves the replacement.

## 9. Non-goals

- No shared Platform/SEM database.
- No SEM ownership of business Task/Run/HIR/Barrier/approval/result state.
- No Runner-side Platform MCP polling for dispatch/control.
- No Redis/Kafka/RabbitMQ cluster requirement.
- No workspace backup.
- No mechanical move of Platform business transaction code into SEM.
- No implementation or migration authorization from this documentation update.
