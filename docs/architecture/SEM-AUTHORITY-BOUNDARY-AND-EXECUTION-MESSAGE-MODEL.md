# SEM Authority Boundary and Execution Message Model

- Status: **User-confirmed architecture direction; protocol replacement and implementation mapping in progress**.
- Scope: normative ownership boundary for the independent SEM service and AI-PM Platform.
- Repositories: `luqizheng/ai-pm` (business authority) and `luqizheng/smark-sem` (execution transport/runtime).
- This document supersedes conflicting SEM-02E–02J assumptions and the previous Platform–SEM–Runner Protocol V1 wherever they assign Platform business-control semantics to SEM. Detailed wire schemas remain to be reconciled before implementation.

## 1. Core decision

**SEM is an independent execution-message transport and runtime-management service. It does not own or interpret AI-PM business semantics.**

- AI-PM Platform is the sole authority for Project, Task, Run/business execution state, approvals, business commands, business results, and task completion.
- SEM receives execution messages from AI-PM, routes the opaque prompt/body to an eligible Runner, coordinates infrastructure delivery/release messages, records Runner-reported observations, and reports infrastructure facts.
- Runner starts or attaches to the configured AI Harness and delivers the prompt.
- Harness obtains Task context and performs authorized business operations through AI-PM MCP using a per-execution delegated identity (exact credential exchange remains under review).
- Harness does not use SEM as a business-context provider or business-state writer.
- AI-PM decides when the business task is complete and explicitly instructs SEM to release the associated execution resources.

SEM may parse and validate its own transport envelope and infrastructure-routing metadata. It must not parse prompt text to infer Task IDs, Task status, business intent, approval, completion, or retry eligibility.

## 2. Authority split

| Concern | Sole authority / owner |
|---|---|
| Project, Task, requirements, design, acceptance criteria | AI-PM |
| Task status and business lifecycle | AI-PM, mutated through authorized AI-PM APIs/MCP |
| Business result validation and task completion | AI-PM |
| Business approvals, HIR, Barrier, retry/successor decisions | AI-PM |
| Prompt content and business instructions | AI-PM authors; SEM transports opaquely |
| Execution request delivery ledger | SEM |
| Runner registration/connection and routing eligibility | SEM infrastructure boundary, subject to AI-PM-issued authorization |
| Harness process start/stop supervision and OS observations | Runner Supervisor |
| Runner CPU, memory, disk and capacity telemetry | Runner reports; SEM stores/uses for infrastructure admission |
| Execution resource reservation/release | SEM |
| Business-to-execution correlation | AI-PM owns the mapping; SEM stores only opaque correlation identifiers |

A transport acknowledgement is not a business acknowledgement. A process exit is not a Task completion. A successful resource release is not proof that the Task succeeded.

## 3. Canonical flow

1. **AI-PM → SEM: execution request.** AI-PM sends an idempotent request containing an opaque execution ID, prompt body, infrastructure routing/profile hints, and correlation metadata. The body may contain arbitrary instructions. SEM treats it as opaque content.
2. **SEM → Runner: delivery.** SEM selects an eligible connected Runner according to infrastructure capacity and authorization constraints, reserves capacity, and delivers the request.
3. **Runner → Harness: launch/inject.** Runner checks whether the requested Harness is available, starts or attaches to it, and supplies the prompt. Runner reports process/runtime facts to SEM.
4. **Harness → AI-PM MCP: business work.** Harness authenticates independently to AI-PM MCP, fetches the referenced Task and all required context, and performs authorized Task transitions and business operations directly in AI-PM.
5. **Harness → AI-PM MCP: business result.** Harness reports progress/results through MCP. AI-PM validates and commits business state. Only AI-PM decides whether the Task is complete.
6. **AI-PM → SEM: release instruction.** After its own business decision, AI-PM sends an idempotent release/stop instruction for the opaque execution ID.
7. **SEM → Runner: runtime cleanup.** SEM sends the release/stop instruction to Runner. Runner Supervisor performs graceful/forced local process termination under its policy and reports exact process/cleanup observations. SEM records the result and releases its infrastructure reservation only when evidence and reconciliation policy permit.
8. **SEM → AI-PM: infrastructure result.** SEM reports released, still-releasing, failed, or uncertain infrastructure status. AI-PM records this separately from Task status.

The execution request does not grant Harness permission to bypass AI-PM MCP authorization. Installing/configuring the AI-PM MCP is a Harness prerequisite, but each MCP operation still uses an independently authenticated, project-scoped identity and AI-PM authorization.

## 4. Independent lifecycles

The AI-PM business Task lifecycle and SEM infrastructure Execution lifecycle are related by an opaque correlation, but are not one state machine.

Examples:
- AI-PM Task = `completed`, SEM Execution = `releasing`: business work is complete while the Harness process is still being cleaned up.
- AI-PM Task remains non-terminal, SEM Execution = `failed`: the process crashed; AI-PM decides whether to retry, pause, request human action, or close the Task.
- AI-PM requests cancellation, SEM Execution = `releasing`: cancellation intent is business-owned; process termination is infrastructure work.
- SEM reports process exit code 0: this is process evidence only. It does not set the Task to completed.
- SEM cannot contact Runner: execution becomes infrastructure-uncertain; SEM reports this and does not invent a Task outcome.

SEM-local states are infrastructure-only, for example:
`queued → assigned → starting → running → releasing → released`, with infrastructure failure/uncertainty branches. These states must not be named or presented as Task statuses.

## 5. Message contract principles

The exact V1 wire schema must be revised to follow these principles:

- Platform → SEM messages: `execution.requested`, `execution.release_requested`, and any explicitly defined infrastructure-control request.
- SEM → Platform messages: delivery/dispatch outcome, Runner/Harness process observations, resource/cleanup outcome, and infrastructure uncertainty.
- SEM → Runner messages: deliver opaque prompt payload, launch profile, release/stop request, and infrastructure control.
- Runner → SEM messages: receipt of transport delivery, Harness launch outcome, heartbeat/resource telemetry, process identity/exit observations, and cleanup result.
- Harness → AI-PM: business context reads, Task status changes, progress, decisions and results through AI-PM MCP. No business state is reported to SEM as an authority channel.

Every mutating message must be idempotent and bound to an immutable execution ID plus execution generation/epoch. Duplicate delivery must not start a second process. Stale release requests must not terminate a newer execution generation. Transport receipt, process start, process exit and resource release are separate facts.

SEM must not expose Platform Claim, Lease Renewal, business command ACK, Task transition, HIR, Barrier, or business-result mutation endpoints as SEM-owned operations. If Platform retains any execution authorization primitive, its authority and call path must be specified as Platform-owned and must not turn SEM into a business workflow proxy.

## 6. Failure, cancellation and recovery

- **Harness exits naturally:** Runner reports exact process-exit observation to SEM; SEM reports it to AI-PM. AI-PM decides the business consequence.
- **Harness crashes/non-zero exit:** SEM reports exit code and evidence. AI-PM decides retry or human intervention.
- **AI-PM releases:** SEM forwards the release instruction; Runner Supervisor performs local Harness cleanup and reports process facts through SEM.
- **Runner disconnects:** SEM marks infrastructure state uncertain and reconciles when Runner reconnects. It must not infer process death from heartbeat loss or workspace deletion.
- **Duplicate or late messages:** idempotency and generation fencing prevent duplicate starts and stale stops.
- **SEM restarts:** durable inbox/outbox and execution ledger recover message delivery and runtime reconciliation. No business state is reconstructed from SEM data.
- **AI-PM unavailable:** SEM may durably accept already-authorized messages within policy, but cannot obtain new business authority or infer Task context. Harness MCP business operations independently fail/retry according to AI-PM behavior.

Workspace/worktree backup is not introduced. A workspace is not process-exit evidence.

## 7. Explicit removals from the old model

The following old assumptions are incompatible and must be removed from normative contracts and implementation plans:

1. SEM calling Platform Claim to create/advance business Run authority.
2. SEM forwarding Runner Lease Renewal as the business execution authority path.
3. SEM acknowledging Platform business commands or changing Task/Run business state.
4. SEM owning or interpreting Task, HIR, Barrier, Consultation, successor authorization, retry eligibility, or business completion.
5. Runner polling Platform MCP for dispatch/control commands.
6. SEM using prompt parsing or Task status mirrors to make business decisions.

Platform MCP remains mandatory for Harness business context and business operations. It is not a Runner dispatch/control polling channel.

## 8. Security requirements

- SEM-to-Runner and Platform-to-SEM authentication remain mandatory, scoped, short-lived/rotatable and auditable.
- Harness-to-AI-PM MCP authentication is independent of SEM service identity. Never forward SEM service credentials as a human or project principal. A per-execution delegated grant must be scoped to one Task/attempt and must not impersonate a human.
- AI-PM must bind Harness MCP credentials to the intended tenant/project/principal and enforce permissions on every call.
- Prompt bodies may contain secrets or untrusted instructions: encrypt in transit and at rest where persisted, redact logs, constrain size/content type, and never execute them inside SEM.
- SEM routing metadata is not authorization. AI-PM-issued execution authorization and Harness MCP authorization remain separate controls.
- Correlation IDs are not credentials and must not be accepted as proof of business identity.



## 8.1 Dual fencing and uncertain Runner recovery

AI-PM authorization_generation fences delegated Harness MCP business operations; SEM execution_epoch/binding_epoch fences Runner delivery/release messages. These are separate authority domains and neither substitutes for the other. If a Runner disconnects without positive process-exit evidence, SEM must retain infrastructure uncertainty and must not dispatch a competing Harness for the same attempt. AI-PM may revoke the old delegated grant, but that does not prove the old process can no longer mutate Git remotes or external systems.

## 9. Required follow-up before implementation

1. Replace the previous Protocol V1 wire contract with request/delivery/release/runtime-observation messages.
2. Decide whether AI-PM sends the prompt inline or by a short-lived content reference; SEM must still treat it as opaque.
3. Specify the exact Harness MCP credential provisioning, project scoping, expiry and revocation model.
4. Define execution ID/generation semantics, duplicate-start prevention and stale-release fencing.
5. Define Runner/Harness process ownership, natural exit reporting, graceful/forced termination and orphan reconciliation.
6. Remove or explicitly supersede old SEM Claim/Lease/Command/Task/HIR/Barrier contracts in every architecture document.
7. Map each existing ai-pm control endpoint, Worker loop, MCP tool and database entity to retain, move, replace or retire. Do not change code or migrations until this mapping is reviewed.
8. Define the remote Runner Git evidence contract: unique execution branch/ref, pushed SHA verification, baseline ancestry and independently calculated changed-file facts. Do not assume AI-PM can access Runner-local worktrees or treat Harness declarations as independent evidence.
9. Add contract tests for duplicate request, duplicate delivery, delayed release, process exit before business completion, business completion before process exit, Runner disconnect, SEM restart and MCP authorization denial.

No implementation, migration, Phase 0 start or production-readiness claim is authorized by this document.
