# D-04 AI-PM Cross-Repository Protocol Review

- Status: **READ-ONLY SOURCE AUDIT — CHANGES REQUIRED**
- Audit date: 2026-11-25
- AI-PM source baseline: `luqizheng/ai-pm@d0e72fa6805aebeadf1b282e430deba493072fd6` (master source revision pinned by the current bilateral review branch)
- SEM protocol baseline: this branch, D-04 Draft 0.2
- Scope: verify the proposed SEM callback receiver and distinguish it from existing AI-PM event/MCP surfaces.
- No AI-PM source, migration or runtime configuration was modified.

## 1. Executive finding

The OpenAPI proposal currently names `POST /internal/ai-pm/v1/sem-events` as the SEM-to-AI-PM callback receiver. **That route is not present in the inspected AI-PM route table.** It is a proposed future endpoint, not an existing API.

The existing `POST /api/v1/events` endpoint is a generic project-event ingestion surface with its own idempotency/processing contract. It is not evidence of a SEM infrastructure-event Inbox and must not be reused without a separately approved contract.

Likewise, AI-PM's existing transactional Outbox is an outbound event producer/worker mechanism. It does not establish an inbound SEM callback receiver, Inbox deduplication, or a per-execution infrastructure-event cursor.

## 2. Source evidence

| Source | Observed fact | Protocol implication |
|---|---|---|
| `apps/pm-api/src/routes.rs` | Router registers `POST /api/v1/events`, supervision routes, notification route and merged business routers; no `/internal/ai-pm/v1/sem-events` route is registered | Proposed SEM callback is new API work |
| `crates/pm-application/src/ingestion.rs` | Generic `submit_event()` writes `integration.inbound_event` and an `integration.job(job_type='ai_analysis')` in one transaction; idempotency key is project+source+key and duplicate detection compares payload hash | Existing generic Inbox must not be reused unchanged for SEM telemetry |
| `docs/architecture/ai-pm-architecture-principles.md` §7.2 / `docs/architecture/knowledge-services/ownership-checklist.md` | Generic Inbox requires project_id + actor_id; shared Outbox/Inbox writes are required to go through application ports | A dedicated SEM application port/handler is required; do not write tables from the HTTP route directly |
| `apps/pm-api/src/routes.rs` | The generic event endpoint is `submit_event_handler`; module comments describe event ingestion outcomes Accepted/ Duplicate/ IdempotencyConflict/UnknownProject | Its semantics and schema are not interchangeable with SEM infrastructure events |
| `crates/pm-infrastructure/src/outbox.rs` | Transactional Outbox operates over `integration.outbox_event` and has bounded delivery attempts/dead-letter behavior | Outbox is not an inbound Inbox |
| `crates/pm-infrastructure/src/outbox_worker.rs` | Worker claims and dispatches registered Outbox handlers | No SEM callback route or receiver transaction follows from this worker |
| `crates/pm-infrastructure/src/outbox_handlers.rs` | Existing handlers process AI-PM domain events such as TaskReady, DeliverySubmitted and RunCompleted | These are AI-PM-owned domain event consumers, not SEM event ingestion |
| `crates/pm-mcp/src/server.rs` | Existing `pm_get_run_context`, `pm_report_progress` and `pm_submit_result` tools belong to the current MCP execution flow | Harness business MCP is separate from SEM callback transport |
| AI-PM execution/MCP source mapping in the existing SEM review branch | Existing Run-context/progress/result flow still uses lease token/generation assumptions; formal review remains human-principal gated | Runner identity cannot be substituted for the current HumanActor/lease model; delegated execution grant is separate D-06 work |

The source files above were fetched at the pinned AI-PM revision. This audit is not a claim that no unrelated branch or unmerged change could add such a route; it establishes that the pinned master baseline does not contain it.

## 3. Required receiver contract before implementation

AI-PM must separately own the receiver and business interpretation. The bilateral contract must specify:

1. Dedicated internal callback route and service-to-service authentication using the approved Ed25519/RFC 9421/RFC 9530 profile.
2. A durable Inbox identity keyed by `event_id`, with canonical-body conflict detection.
3. Per-`execution_id` `execution_event_sequence` cursor and explicit gap/replay/reconciliation behavior.
4. One-event or bounded batch delivery semantics.
5. A transaction boundary that commits Inbox deduplication and the permitted Run/infrastructure-observation update atomically before returning a success ACK.
6. An explicit mapping from each SEM event type to an AI-PM-owned application-service operation. SEM events may not set TaskStatus, approval, acceptance, or other business decisions.
7. HTTP response/ACK schema, retryable vs permanent status classification, Retry-After behavior, dead-letter handling and operator replay.
8. Authentication principal and authorization policy distinct from HumanActor and distinct from Runner identity.
9. Retention, replay cursor reset, event schema version compatibility and audit behavior.

The SEM OpenAPI route remains a **proposed endpoint placeholder** until AI-PM confirms route ownership and approves its own application/DB contract.

## 4. Existing generic event endpoint is not a substitute

The existing `/api/v1/events` route must not be silently repurposed. It is a project-scoped generic event ingestion API with its own event envelope and processing semantics. Its `integration.inbound_event` table is a generic shared Inbox, but the current ingestion application service also enqueues `ai_analysis`; it has no SEM execution cursor or infrastructure observation handler. SEM infrastructure event identity, Runner provenance, binding fencing and per-execution sequence are a different domain contract. A new dedicated SEM receive application operation must decide whether to extend the shared Inbox safely or add a SEM-specific inbox/cursor store.

No route alias, payload adapter or direct database write is authorized by this review.

## 5. Harness MCP is a separate channel

The SEM-to-AI-PM infrastructure callback is not the Harness-to-AI-PM MCP business channel.

- SEM reports infrastructure facts through the dedicated service callback.
- Harness obtains business context and performs permitted business operations through AI-PM MCP.
- Runner identity authenticates the infrastructure endpoint/session only.
- The proposed delegated execution grant must be issued and enforced by AI-PM and scoped to the exact Task/Run/attempt/authorization generation/operation.
- Existing lease-token tools cannot be assumed to accept the future delegated grant without a separately reviewed D-06 application-service design.
- Formal review, approval and acceptance remain human-only.

## 6. Disposition

**P0-05 remains OPEN.** The OpenAPI callback route is not source-aligned with current AI-PM because it does not yet exist. The strict SEM event payload schemas are now drafted in `platform-sem-v1.schema.yaml`, but this does not close receiver ownership, Inbox transaction, ACK cursor or retry semantics.

Required next work is a bilateral AI-PM/SEM design review. The first decision is whether to add a SEM-specific Inbox or safely extend the existing generic Inbox through a dedicated port that suppresses the `ai_analysis` side effect and adds per-execution sequence/cursor semantics. Do not implement the callback, change AI-PM migrations, or claim end-to-end event delivery until both repositories have approved the contract and the user authorizes implementation.
