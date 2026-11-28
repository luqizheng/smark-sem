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

## 6. Bilateral receiver design proposal

A downstream draft has now been added to the AI-PM documentation branch:
[AI-PM SEM Callback and Inbox Design](https://github.com/luqizheng/ai-pm/blob/docs/sem-02e-architecture-convergence/docs/architecture/server-execution-management/ai-pm-sem-callback-inbox-design-draft.md).

It proposes (not ratifies) the following:
- `execution_id == delivery.task_run.id` for one attempt row;
- a dedicated service-authenticated callback route;
- a SEM-specific application port that does not enqueue the generic `ai_analysis` job;
- reuse of the shared `integration.inbound_event` only if a safe no-analysis path, event-ID uniqueness and contiguous execution cursor can be guaranteed; otherwise a dedicated SEM Inbox;
- one transaction for Inbox deduplication, Run observation, cursor advance and success ACK;
- no TaskStatus, Submitted, Completed, approval or acceptance mutation from infrastructure callbacks.

This proposal is Draft and requires bilateral review against the canonical SEM D-04 contract. It does not close P0-05 or authorize implementation.

## 7. Disposition

**P0-05 remains OPEN.** The OpenAPI callback route is not source-aligned with current AI-PM because it does not yet exist. The strict SEM event payload schemas are now drafted in `platform-sem-v1.schema.yaml`, but this does not close receiver ownership, Inbox transaction, ACK cursor or retry semantics.

Required next work is a bilateral AI-PM/SEM design review. The first decision is whether to add a SEM-specific Inbox or safely extend the existing generic Inbox through a dedicated port that suppresses the `ai_analysis` side effect and adds per-execution sequence/cursor semantics. Do not implement the callback, change AI-PM migrations, or claim end-to-end event delivery until both repositories have approved the contract and the user authorizes implementation.


## 5. Callback ACK sequence-field cross-check — 2026-11-25

The bilateral review compared the AI-PM callback/Inbox proposal against the canonical Platform–SEM event envelope and acknowledgement schema. The SEM contract uses execution_event_sequence for the per-execution SEM→AI-PM event stream; event_sequence is reserved for the Runner journal stream, while message_sequence is WSS-connection scoped.

The AI-PM PR #9 callback design had one stale response-field alias in §5.2 step 7 (`event_sequence`). It has been corrected on the AI-PM review branch to `execution_event_sequence`, with an explicit prohibition on the ambiguous alias. This is a documentation alignment only; no AI-PM route, Inbox, database or runtime behavior exists yet.

P0-05 remains OPEN. The callback route, service authentication, shared-Inbox application port, transaction/cursor behavior, exact response schema, retry semantics and bilateral runtime tests still require ratification and separate implementation authorization.

A second cross-document mismatch was found in the AI-PM PR #9 callback proposal: §5.2 and OI-02/OI-03 named the attempt cursor sem_last_event_sequence, while its exact DDL/concurrency proposal names the column delivery.task_run.execution_event_sequence. The callback proposal has been corrected to use execution_event_sequence consistently. This is the same per-execution SEM→AI-PM cursor defined by D-04 and is distinct from Runner journal event_sequence and WSS message_sequence.


## 6. SEM event catalogue and AI-PM Inbox cross-audit — 2026-11-25

### 6.1 Corrected: protocol prose omitted the binding-established event

The normative Platform event JSON Schema defines five event variants, including `execution.binding_established`, but the §8 prose catalogue listed only four. The catalogue now explicitly lists all five and points to the discriminated-union schema as normative.

### 6.2 Corrected: AI-PM Run-observation dedupe key contradicted its DDL

AI-PM PR #9 callback prose said `task_run_event.dedupe_tag = event_id`. Its companion exact DDL requires `detail.execution_event_sequence = dedupe_tag` and creates the partial unique index `(run_id, dedupe_tag)` to enforce one observation per Run sequence. These cannot both be true. The callback design now uses canonical base-10 `execution_event_sequence` as `dedupe_tag`; event-ID idempotency remains enforced by `integration.inbound_event.id` and `idempotency_key`. This aligns the prose with the SQL CHECK, index and INBOX-46 acceptance case.

### 6.3 P0-06 OPEN: AI-PM has no specified current-binding projection or first-bind rule

The callback transaction algorithm says it validates every event against the “current SEM infrastructure binding tuple” (`runner_id`, `runner_key_version`, `boot_id`, `supervisor_instance_id`, `binding_epoch`, plus process/launch/containment identities). However, the proposed DDL adds only the per-attempt event cursor to `delivery.task_run`; it adds no binding projection/table, and it specifies no deterministic query/replay algorithm over `task_run_event` to derive the current binding.

This is especially visible for the first `execution.binding_established` event: there is no prior current binding tuple against which to validate it. The generic step-2 rule is therefore not implementable as written. Without a defined projection/first-bind rule, the receiver cannot reliably distinguish initial binding, exact duplicate, stale lower epoch, conflicting same epoch, and authorized rebind after prior binding release/isolation. This is a stale-binding acceptance and fencing gap, not merely a reporting omission.

Before ratification, AI-PM PR #9 must choose and specify one of:
1. a minimal AI-PM-owned current-binding projection keyed by `task_run.id`, updated atomically with Inbox + Run observation + cursor; or
2. a fully specified deterministic event-history replay/query algorithm that identifies the latest accepted binding and proves allowed rebind transitions without relying on unspecified “current” state.

The contract must explicitly cover first bind, exact duplicate, same-epoch conflicting identity, lower/stale epoch, higher-epoch rebind after positive prior release/exit or authorized host-isolation disposition, and rebind while prior process state remains uncertain (must reject/retain quarantine). SEM remains authoritative for binding allocation; the AI-PM projection is only the consumer's last accepted binding reference and must never authorize a new Runner or change business Run/Task state.

No implementation is authorized by this finding. AI-PM PR #9 remains Draft / Changes Required until the projection and acceptance cases are specified. The event-catalogue and dedupe-tag corrections are documentation-only.


### 6.4 Corrected: release status must not require a stop-fence ID before the fence exists

The Platform `ReleaseStatusPayload` previously required `stop_fence_id` for every state, including `requested`, `release_uncertain` and `stale_rejected`. That is not sound: the Runner creates the immutable local fence journal record only after it has processed the release command; an accepted request or a stale rejection may occur before such a record exists. The schema now requires `stop_fence_id` only for post-fence states (`stop_fenced`, `termination_requested`, `process_exited`, `released`, `cleanup_failed`), and the protocol text defines this boundary. Added D04-H89/H90 and positive/negative fixture checks. `process_exited` continues to require `process_exit_evidence_id`.

### 6.5 P0-07 OPEN: release cannot cancel an execution that has not yet been bound

The execution lifecycle explicitly says `binding_epoch` is allocated only when SEM establishes a Runner binding. However, `ExecutionReleaseRequest` requires `expected_binding_epoch >= 1`, and the release-status event schema requires `binding_epoch` plus Runner identity fields. An accepted execution may still be queued/unbound when AI-PM cancels the Task/attempt. There is currently no representable release request that asserts “this execution is still unbound; cancel it and prevent any later dispatch,” nor an event that confirms that unbound cancellation.

This is a dispatch/release race, not a harmless optional-field issue. A safe contract must define a linearization point shared with dispatch: an unbound-release request must atomically fence future assignment, and if assignment already won the race it must return/reconcile the actual bound epoch and require the normal fenced release path. The response/event contract must distinguish `released_unbound` (no Runner was ever bound and future dispatch is fenced) from process-exit states; it must not fabricate a Runner stop fence or process-exit evidence.

Before ratification, specify the request union (for example, an explicit expected-binding condition of `unbound` versus `bound(epoch)`), the SEM dispatch sequencer behavior, replay/idempotency, and a Platform event shape that can report unbound release without inventing Runner identity. Add tests for cancel-before-dispatch, dispatch-wins race, lost response/retry, and no late Runner assignment after unbound release. This is P0-07 / Changes Required; no implementation is authorized.


### 6.6 Required acceptance coverage for P0-07

Added D04-H91/H92/H93 to make the unbound-release race explicit: cancel-before-dispatch must atomically fence future dispatch; dispatch-wins must return the actual bound epoch and require normal fenced release; release-wins must reject any delayed assignment and remain replayable/idempotent. These are required future contract behaviors, not passing implementation tests; P0-07 remains open until the request/event schema and SEM dispatch sequencer define them.


### 6.7 P0-07 proposed resolution: tagged unbound release with a SEM dispatch tombstone

The bilateral proposal is now documented in Platform protocol §7.1 and AI-PM exact DDL/concurrency design §12. It uses expected_binding={state:unbound} versus {state:bound,binding_epoch:N}, one SEM per-execution sequencer shared by dispatch and release, and a distinct execution.unbound_release_applied event with dispatch_fence_id but no Runner/process fields. Dispatch-wins returns BINDING_ALREADY_ESTABLISHED and requires normal bound release; release-wins permanently prevents late assignment. D04-H94..H100 define the race/replay cases. This is a proposed sixth event; the existing five-event JSON Schema has not been changed and P0-07 remains open pending schema/OpenAPI/fixture and runtime proof.


### 6.8 Canonical AI-PM projection and lock order

AI-PM has consolidated P0-06 and P0-07 consumer state into one proposed per-attempt delivery.task_run_sem_execution projection. It carries dispatch_state plus a nullable current binding tuple; released_unbound has no Runner identity/epoch and carries only SEM dispatch_fence_id. The earlier task_run_sem_binding table name is superseded and must not become a second table. The exact DDL design §13 freezes callback lock order: Run → execution projection → Inbox → Run observation → cursor CAS, all in one transaction. This avoids dual projections and keeps the unbound tombstone in the same current-state record. The complete SQL CHECK matrix and live PostgreSQL tests remain open.
