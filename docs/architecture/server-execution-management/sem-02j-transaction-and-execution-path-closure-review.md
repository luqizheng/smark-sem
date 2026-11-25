# SEM-02J — Platform Transaction and Execution-Path Closure Audit

- Status: **Changes Required / Audit In Progress**.
- Source baseline: GitHub `master@d0e72fa6805aebeadf1b282e430deba493072fd6`.
- Related design: [SEM-02H](./sem-02h-ddl-integrity-and-transaction-review.md), [SEM-02I](./sem-02i-corrected-platform-schema-and-process-api-candidate.md).
- Scope: read-only source audit of Platform Run/Task/Interaction/Command/Recovery/Review paths.
- Change boundary: this audit changed no application code, migrations, API, WSS, Dockerfile, Compose or runtime configuration. Phase 0 remains Not Started and unauthorized.
- Important: line references below refer to the source baseline above; they are navigation hints, not stable API contracts.

## 1. Executive result

The source audit confirms that the existing code has multiple cross-aggregate lock-order inversions. The Interaction Run↔Interaction inversion already identified in SEM-02H is real at the SQL lock-acquisition level. The wider audit found additional Run↔Command and Run↔Task inversions.

The Task Execution Barrier cannot safely be implemented by adding a `SELECT ... FOR UPDATE` to only the new scanner. Existing Claim, Task cancellation, Interaction, recovery and review paths acquire the same rows in inconsistent orders. A single global lock graph and a complete dispatchability gate are P0 prerequisites.

No lock-order remediation is approved by this document. The final order must be selected only after the remaining source paths and foreign-key/trigger side effects are inventoried.

## 2. Confirmed lock-order inversion candidates

### P0-01 — Run ↔ Interaction

Observed paths:

- `interaction.rs::report_interaction` locks `delivery.task_run` first (`FOR UPDATE OF r`, around line 129), then locks the active `delivery.task_interaction` chain row (`FOR UPDATE`, around line 197).
- `interaction.rs::retry_interaction` locks the prior Interaction first (around line 783), then locks its Run (around line 816).
- `interaction.rs::cancel_open_interaction_tx` updates/locks the open Interaction first (around line 705), then updates the Run scheduling shield (around line 720).
- Continue ACK also follows Run → Interaction: `worker_command::ack_command` locks the command, updates the Run shield, then invokes continuation/Interaction recovery writes (around lines 365, 500 and 537).

A report/retry, report/cancel, or continue-ACK/cancel interleaving can form a wait cycle on the same Run and Interaction. This is not closed by the existing single-request idempotency tests.

### P0-02 — Run ↔ worker_command

Observed paths:

- `recovery::reacquire_lease` locks the Run first (`FOR UPDATE`, around line 189), then updates all non-terminal `delivery.worker_command` rows for that Run (around line 282).
- `worker_command::ack_command` locks the selected command first (`FOR UPDATE`, around line 365), then updates the Run scheduling shield for a continue ACK (around line 500), and may update Interaction/Continuation/Task state afterwards.

A concurrent ACK and same-Run reacquire can therefore hold Command→Run and Run→Command respectively. The existing ACK generation fence does not eliminate this database deadlock possibility.

### P0-03 — Run ↔ Task

Observed paths:

- `run_dispatch::claim_core_in_project` locks Project, then the queued Run (`FOR UPDATE OF r SKIP LOCKED`), then the Task (`FOR UPDATE`, around lines 417, 445/462 and 522). The source comment explicitly documents Project → Run → Task.
- Run transition/recovery paths commonly lock/update the Run before transitioning or updating the Task. Examples include `run_transition_guard::lock_and_validate_transition`, `run_executor::recover_lost` and the shared `recover_lost_run` path.
- Task cancellation first locks the Task row in `pm_write::update_task` or `command_executor::apply_task_transition` (around `pm_write/task.rs:217` and `command_executor/transition.rs:67`). The cancellation hook then enters `task_cancelled_linkage_tx` → `cancel_open_interaction_tx`, which updates Interaction and then the Run (around `interaction.rs:686-724`).

A Claim/Run-transition transaction can hold Run and wait for Task while a Task-cancellation transaction holds Task and later waits for the same Run. This is a cross-module inversion, not merely an Interaction-local issue.

### P0-04 — The current lock graph is not globally specified

The paths above are only the confirmed cycles found so far. Existing lock patterns include:

- Project → Run → Task: normal delivery Claim and Project archive.
- Project → Task → new Run insert: TaskReady handler and review enqueue.
- Run → Task: Run terminal/recovery transitions.
- Task → Interaction → Run: Task cancellation linkage.
- Run → Interaction → Task: report/continue lifecycle.
- Interaction → Run: retry/cancel.
- Command → Run → Interaction → Task: continue ACK.
- Run → Command: lease reacquisition.
- Consultation → Task waiting state: existing generic Human Consultation transition path.

These sequences cannot be combined safely by adding Barrier/HIR locks ad hoc. The final lock order must cover Project, Task, Run, Barrier, Interaction, worker_command, HIR and Human Consultation, including all multi-row Task operations and deterministic ordering when a Task has multiple Runs.


### P0-05 / P1 — Project dependency-graph advisory lock participates in the lock graph

The Task lifecycle has a transaction-scoped project graph lock in `task_dependency::acquire_project_graph_lock`. Its source contract explicitly says it must be acquired before any row lock.

- `pm_write::update_task` for terminal transitions acquires the graph advisory lock before locking the Task row (`pm_write/task.rs:200-222`).
- `command_executor::apply_task_transition` also acquires the graph lock for terminal transitions, before its Task `FOR UPDATE` (`command_executor/transition.rs:55-73`).
- However, some callers already hold another row lock before invoking that transition service. In particular, `review::run_review` locks and finalizes the Review Run, then calls `advance_after_review`; the approved auto-completion path calls `apply_task_transition(TaskStatus::Completed)`, which acquires the graph lock afterwards (`review/worker.rs` run-finalization path; `review/decide.rs:240-382`). This violates the graph-lock helper's documented “before any row lock” rule.

This is a lock-order contract violation that must be included in the full graph and tested against Task cancellation, dependency-edge mutation and other terminal transitions. The current evidence is sufficient to reject a claim that the global lock order is already consistent, but not sufficient to assert a specific deadlock cycle for every such pairing.

### P0-06 — Task cancellation extends the inversion beyond a single Interaction helper

Both Task cancellation entrypoints lock the Task before invoking `task_cancelled_linkage_tx`:
- REST direct update: `pm_write::update_task` locks Task at `pm_write/task.rs:217`, updates it, then invokes the cancellation linkage.
- Command channel: `command_executor::update_task_status` calls `apply_task_transition` (Task lock) and then invokes the same linkage.

The linkage then takes Interaction → Run locks. This gives Task → Interaction → Run, while delivery Claim and several recovery paths take Run → Task. The Task-level cancellation race therefore remains even if report/retry are individually reordered.

## 3. Execution Barrier bypasses found in existing paths

The proposed Task Barrier must be checked at both Run creation and every dispatch/ownership transition. Current source paths do not yet have this gate.

| Path | Current source behavior | Required SEM contract |
|---|---|---|
| Delivery Claim | Locks Project → Run → Task; no Task Barrier check exists | Under the canonical Task/Run lock order, atomically check active Barrier and Interaction shield before Claim/Generation |
| TaskReady handler | Locks Project → Task, checks active delivery Run, then calls `insert_task_run`; no Barrier check | Must refuse/record suppression while an active Task Barrier exists |
| Review enqueue | Locks Project → Task, then creates a review Run; no Barrier check | Define whether Barrier blocks review Run creation; V1 should not allow a different Run kind to bypass the Task-level safety fence |
| Review Claim | `review::worker::claim_review_run` locks only the queued review Run; it does not lock Project/Task or check Barrier | Must use the same Project/Task dispatch gate; no special review bypass |
| Review retry | `review::worker::schedule_retry` directly inserts a new review Run without locking Project/Task or checking Barrier | Must be serialized with Project archive and Task Barrier |
| Delivery retry after failure | `review::failure` updates Task and calls `insert_task_run`; it has a Task lock but the reviewed path does not show a Project activity gate or Barrier check | Add Project activity and Barrier checks in the same transaction |
| Same-Run reacquire | `recovery::reacquire_lease` locks Run and re-signs generation/token, then reroutes commands; no Task Barrier check | Reacquire must not restore execution authority through an active Barrier |
| Orphan reconciliation | Existing `reconcile_orphans` requeues an expired Run and changes Task state without a Task Barrier/HIR transaction | Replace with the new Platform-only scanner; never reuse the old requeue behavior |

The review-specific rows matter because `delivery.task_run` stores both `delivery` and `review` Run kinds. A Task-level Barrier cannot be considered complete if the review queue/worker has a separate dispatch path.

## 4. Run creation inventory (current code)

The source search identified these business creation paths:

1. Delivery TaskReady: `pm-infrastructure/src/outbox_handlers.rs` → `run_dispatch::insert_task_run`.
2. Delivery retry/recovery: `run_dispatch::lease::recover_lost_run` → `insert_task_run`.
3. Delivery retry after failure: `review::failure` → `insert_task_run`.
4. Review enqueue: `review::queue::insert_review_run`.
5. Review retry: `review::worker::schedule_retry` direct `INSERT INTO delivery.task_run`.

The shared delivery helper documents a Task-row-lock precondition (`run_dispatch/port.rs:8`). Review enqueue currently locks Project then Task before insertion. Review retry is a notable exception: the inspected transaction reads the failed Run and inserts a new review Run without acquiring the Task row lock. It also does not acquire the Project activity gate in that transaction.

All five paths must be included in the final Barrier/Project-gate matrix. Any additional direct INSERT found in the remaining repository scan must be added before this inventory is declared exhaustive.

## 5. Project lifecycle and dispatch observations

- Normal delivery Claim uses the Project activity row lock before Run Claim.
- TaskReady and review enqueue also use the Project activity gate.
- Review Claim currently selects/locks a review Run without the Project gate. This can race Project archive: a review worker may claim a queued review Run while archive is changing the Project and cancelling queued Runs.
- Review retry creates a new review Run without the Project gate, so it can create queued work after Project closure unless another invariant blocks it.
- The old orphan reconciliation path has no Project activity lock. Its queued requeue can race archive; the new scanner must explicitly serialize with Project lifecycle.
- Project archive itself locks Project before selecting and cancelling queued Runs. Any path that creates or claims a Run must participate in this same Project gate.

## 6. Existing test evidence and missing concurrency coverage

Existing tests establish useful but narrower properties:

- `run_dispatch::concurrent_claims_yield_exactly_one_claimed_run`: competing delivery claims serialize correctly for one queued Run.
- `run_executor::c66_concurrent_finalization_wins_over_poll`: a Run finalization/poll race is covered.
- ACP tests cover Interaction idempotency, command ACK validation, and repeated continue ACK behavior.

The inspected ACP test file contains many sequential report/retry/ACK assertions, but the targeted search did not find deterministic two-connection tests for:

- report ↔ retry;
- report ↔ Task cancellation;
- continue ACK ↔ Task cancellation;
- ACK ↔ reacquire;
- Claim ↔ Task cancellation;
- Barrier scanner ↔ Claim/TaskReady/retry/review Claim;
- review Claim ↔ Project archive.

Do not treat single-call idempotency tests or random `tokio::join!` tests as proof of deadlock freedom. Required tests must use two independent PostgreSQL connections, explicit transaction barriers, bounded lock/statement timeouts and assert both final database state and absence of partial audit/notification effects.

## 7. Required next audit passes

Before deciding the final lock order, complete these read-only passes:

1. Enumerate every `delivery.task_run` INSERT and every state/lease/generation UPDATE, including delivery submit, review completion/failure, run context, cleanup, project archive and outbox handlers.
2. Enumerate every path that locks or updates `delivery.task`, `task_interaction`, `worker_command`, `continuation`, `human_intervention`, `human_consultation`, Barrier candidates and notification rows.
3. Inspect SQL foreign keys, triggers, cascade behavior and unique-index conflict paths that may acquire implicit row/key locks.
4. Inspect all API/MCP entrypoints and background loops to prove no alternate claim, requeue, continue, terminate, ACK or recovery route bypasses the application transaction contract.
5. Decide whether review Runs are blocked by Task Barrier (recommended: yes) and whether E6 successor authorization applies only to a delivery Run or another explicitly typed successor.
6. Select one global lock order and deterministic ordering for multiple Runs/Interactions per Task; then map every transaction to it.
7. Only after the source audit is complete, author the DDL/API/transaction changes and deterministic concurrency tests.

## 8. Required deterministic concurrency acceptance matrix

| ID | Transaction A | Transaction B | Required result |
|---|---|---|---|
| J01 | Report Interaction | Retry/cancel same Interaction | No deadlock; exactly one valid lifecycle outcome |
| J02 | Continue ACK | Task cancellation | No deadlock; terminal Task cannot be reopened by late ACK |
| J03 | ACK command | Same-Run lease reacquire | No deadlock; current generation fences stale ACK |
| J04 | Delivery Claim | Task cancellation | Exactly one serialized outcome; no active Run on cancelled Task |
| J05 | Periodic scanner | Delivery Claim | Either Claim wins before expiry/Barrier eligibility, or Barrier+HIR+Inbox+Audit commit before any later Claim |
| J06 | Periodic scanner | TaskReady/retry/review enqueue | No Run creation can escape the Task Barrier |
| J07 | Periodic scanner | Review Claim/retry | Review execution cannot bypass Task Barrier |
| J08 | Project archive | Review Claim/retry and orphan scan | No new/claimed Run after Project closure |
| J09 | E6 decision | Competing E6 decision/successor allocation | Exactly one consultation and one successor authorization |
| J10 | Continue new process | Late exit from prior process sequence | Old process evidence cannot clear the active process fence or release Barrier |

Each test must assert transaction completion, lock timeout behavior, unique constraints, Run/Task/Barrier/Interaction/Command state, and audit/outbox/inbox row counts.

## 9. Current decision

**Changes Required.** The Task Barrier design is directionally correct but not safe to implement until the complete lock graph, all Run creation/claim/reacquire paths, Project lifecycle gates and review execution paths are closed.

- No migration authoring.
- No business-code changes.
- No Phase 0 start.
- PR #9 remains Draft and must not be merged.



## 9. Second audit pass — Run writes, FK/index/trigger side effects

Source baseline remains `master@d0e72fa6805aebeadf1b282e430deba493072fd6`. This pass inspected the concrete Run creation/retry implementations and the checked-in schema/inventory evidence. It remains read-only.

### 9.1 Run INSERT paths — expanded findings

The application source confirms the five business creation paths listed above. Their transaction properties are not equivalent:

| Path | Source behavior | Lock/gate result |
|---|---|---|
| Delivery TaskReady | `run_dispatch::insert_task_run`; shared helper documents that caller must already hold Task `FOR UPDATE` | Helper itself does not acquire Project gate or Task Barrier; caller must supply both |
| Delivery lease-loss recovery | `recover_lost_run` → terminalize old Run → `insert_task_run` | Caller precondition is Task row lock; Run transition happens before new Run insert; Barrier/gate still must be supplied by outer transaction |
| Review enqueue | `review::queue::enqueue_review` → Project activity gate → Task `FOR UPDATE` → `insert_review_run` | Project gate and Task lock exist; Task Barrier check is absent |
| Review retry | `review::worker::schedule_retry` directly inserts `delivery.task_run` | **No Project activity gate, no Task row lock, no Task Barrier check**; reads max review attempt and current Task revision without locking Task |
| Delivery retry after failure | `review::failure::judge_delivery_failures` → `insert_task_run` | The retry transaction updates Task before INSERT, which obtains a Task row lock, but this code path has no Project activity gate or Task Barrier check |

Review retry has an additional concurrency defect candidate: two workers can read the same `max(attempt_no)+1` before either inserts. The partial unique index `uq_task_run_attempt_review` rejects the duplicate, while `uq_task_review_active` only permits one queued/running Review Run. These constraints are useful last-line integrity guards; they do not replace the missing Task lock, Project gate or Barrier check. A deterministic two-connection retry/retry test is required.

The failure-judge path needs a precise lock-order interpretation: it performs a conditional Run `UPDATE finished_at` as a standalone pool statement, so that Run row lock is released before its later transaction updates Task and inserts a replacement Run. The inspected code therefore does **not**, by itself, prove a simultaneous Run→Task lock hold in that specific retry transaction. It still lacks Project activity and Barrier checks, and the scan/claim/decision sequence must be tested against duplicate workers and Project closure. Do not overstate this path as another proven Run→Task deadlock.

### 9.2 Run UPDATE and ownership-transition paths

The inspected source confirms the following distinct classes of writes:

- Delivery claim/lease issuance and same-Run reacquire update lease owner, token hash, expiry and generation.
- Recovery can terminalize an old Run and create a successor in the same transaction.
- Dispatch qualification can requeue an eligible queued Run with backoff; redispatch also performs a guarded same-row queued update.
- Run executor and cancellation/finalization paths update status/outcome/finished timestamps and record Run events.
- Review worker paths update Review Run status through separate Review-only transitions: queued→running, running→succeeded/failed/timed_out. Review retry creates a successor Review Run.
- Project archive cancels queued Runs in its Project-close transaction; active Run cancellation is then handled by the follow-up cancellation protocol.
- Run cleanup updates `task_run_cleanup`, not the authoritative Run lease/status. Cleanup state must not be treated as process-exit evidence.

This is a source-path inventory, not yet a claim that every SQL statement in every module has been exhaustively enumerated. The remaining code-search pass must continue across all Run state columns and all API/MCP/background entrypoints before the inventory can be marked closed.

### 9.3 Foreign-key side effects

The checked-in schema evidence establishes that `delivery.task_run` is not an isolated row:

- Parent references include `(tenant_id, project_id) → core.project`, `(project_id, task_id) → delivery.task`, device identity through `(tenant_id, lease_client_id)`, and self-reference through `supersedes_run_id`.
- Child references include Interaction, Continuation, interaction responses/deliveries, checkpoints, worker commands, failure records, Run repository snapshots, cleanup, execution authorization, review findings/verdicts/approvals and repository commits.
- Several child references use `ON DELETE CASCADE` (for example cleanup, Run repository snapshot, review finding/verdict/approval rows); others use RESTRICT/NO ACTION or the default behavior. Run deletion is therefore not a harmless cleanup operation and must remain outside the execution-recovery protocol.
- In PostgreSQL, FK validation and unique-index conflict handling can acquire implicit key-share/index locks. The transaction graph must account for these effects, especially when a path inserts a child row while another path updates/deletes its parent, or when two paths concurrently allocate the same per-Task attempt number.

The FK/index inventory also shows why a Task-level Barrier must be enforced before creating either Run kind: both delivery and review Runs share the same Task parent and the same `delivery.task_run` identity space.

### 9.4 Unique indexes and triggers

The checked-in index inventory records these important guards:

- `uq_task_run_active`: at most one active Delivery Run per Task for queued/claimed/running.
- `uq_task_review_active`: at most one active Review Run per Task for queued/running.
- `uq_task_run_attempt_delivery` and `uq_task_run_attempt_review`: per-kind attempt uniqueness.
- `uq_task_run_source_event`: one Run per non-NULL source event.
- `uq_task_run_project_id` / `uq_task_run_tenant_id`: composite FK targets.

These indexes serialize some conflicting inserts or reject duplicates, but none encodes “Task has an unreleased Execution Barrier”; they cannot be used as a substitute for the Platform transaction predicate.

The inspected trigger inventory shows:
- `trg_review_report_immutable` on `delivery.task_run` (BEFORE UPDATE) protects Review report/anchor immutability.
- `trg_task_run_event_guard` protects the append-only Run event table.
- `task_run_failure_immutable` protects failure evidence against UPDATE/DELETE.

No inspected trigger was found to acquire Project, Task, Run, Interaction or Command locks as a secondary side effect. The Review report trigger runs on the already-targeted Run row; the event/failure triggers target their own row. This is limited to the inspected trigger inventory and must be rechecked against the final migration chain, not generalized to every database trigger.

### 9.5 Updated conclusions

1. Review retry is a confirmed direct Run-creation bypass: no Project gate, no Task row lock and no Task Barrier.
2. Delivery retry after failure has a Task write/row lock but still lacks the Project activity gate and Barrier check.
3. Review Claim and stuck-Review recovery still operate without the Project activity gate; Project archive pairing tests remain required.
4. Unique indexes are integrity backstops, not dispatch authorization. They do not close Barrier bypasses.
5. FK validation introduces implicit parent-key locks and must be included in the final lock graph. The current evidence does not justify declaring a complete global lock order.
6. The exact failure-judge sequence must not be mislabeled as a simultaneous Run→Task lock inversion: its standalone Run update commits/releases before the later Task transaction.

### 9.6 Remaining audit work

- Finish exhaustive code search for every Run INSERT and every write to `status`, `lease_generation`, `lease_token_hash`, `lease_owner`, `lease_expires_at`, `scheduling_shield`, `executor_session`, `supersedes_run_id` and process-sequence fields.
- Finish the full Task/Interaction/Continuation/Command/HIR/Consultation/Barrier/Notification read-write route inventory.
- Reconcile migration DDL from the current migration head against the 2026-11-15 schema inventory; the inventory is evidence, not a substitute for replaying the current migration chain.
- Add deterministic tests for Review retry vs Review retry, Review retry vs Project archive, Review Claim vs Project archive, Delivery retry vs Project archive, and FK/unique-conflict wait behavior.
- Only after those passes, derive the canonical lock order and decide whether some writes need a shared transaction helper or a single dispatchability predicate.

Status remains **Changes Required / Audit In Progress**. No migration, business code, API/WSS, Dockerfile, Compose, Worker/Runner loop or runtime configuration was changed. Phase 0 remains Not Started; PR #9 must not be merged.


## 10. Third audit pass — lease business writes, legacy control entrypoints and governance carriers

This pass traced the production application call sites for lease renewal/progress, delivery submission, Runner-facing claim/recovery/command operations, Human Intervention, Human Consultation and notification feed. It remains a static source audit against the same master baseline.

### 10.1 Additional Run → Task lock edges

The first lock graph omitted several ordinary business paths that also hold a Run lock before transitioning Task:

| Path | Observed order | Consequence |
|---|---|---|
| MCP `report_progress` first-start path | `lock_lease` locks Run `FOR UPDATE` → `apply_task_transition(Running)` locks Task | Run → Task |
| MCP `submit_result` | delivery pipeline performs `lock_lease` fencing → accepted submission transitions Task to `submitted` in the same transaction | Run → Task |
| Platform Worker spawn confirmation | Project activity gate → Run transition lock/update → `apply_task_transition(Running)` locks Task | Project → Run → Task |
| Review success/advance | Review Run is locked/finalized → `advance_after_review` may transition Task (including Completed) | Review Run → Task; terminal path may then acquire graph advisory lock |

These are additional concrete Run→Task edges. The Task cancellation path remains Task→Interaction→Run. The report-progress and delivery-submit paths are not merely recovery edge cases; they are normal execution business writes and must be included in the canonical transaction design.

The Project gate in spawn confirmation is important for Project archive serialization, but it does not by itself solve the graph-lock contract: a terminal Task transition that acquires the graph advisory lock after the Run row has already been locked still violates the graph helper's “before any row lock” precondition.

### 10.2 Existing Runner/Worker control-plane entrypoints

The current code still contains the pre-SEM control topology:

- MCP `claim_task_run_as_client` is called from `crates/pm-mcp/src/tools.rs` and exposed by the MCP server. It lets the authenticated Client claim a Run directly from Platform.
- MCP `reacquire_lease` is exposed by the MCP server and calls `recovery::reacquire_lease` directly.
- MCP `poll_commands` / `ack_command` expose command delivery and ACK directly to the Runner.
- The Platform Worker also calls `run_executor::claim_and_start` / `claim_once` and owns local executor polling/recovery paths.

These are existing code paths, not the target SEM topology. Under the confirmed SEM architecture, Runner control must move behind Runner↔SEM WSS and SEM↔Platform HTTPS; SEM alone requests Claim, while Platform remains the Run/Lease/Generation authority. The migration must explicitly remove or fail-closed the old Runner-facing MCP Claim/reacquire/command poll/ACK routes and prevent the old Platform Worker executor loop from acting as a second dispatch authority. Do not remove Harness business MCP operations such as run context, progress, interaction reporting and result submission merely because they share the MCP transport.

The control-plane cutover needs negative tests proving:
- a Runner device credential cannot call legacy MCP Claim/reacquire/poll/ACK routes;
- only the SEM service identity can invoke the dedicated Platform Claim/command/renewal APIs;
- Harness MCP business operations remain available under their separate user/device and Run-lease scopes;
- the Platform Worker cannot independently claim or dispatch after SEM becomes authoritative.

### 10.3 Existing governance carrier audit

#### `governance.human_intervention`

Current application evidence shows:
- The production writer is `supervision::feed::record_intervention`, called by supervision veto/freeze operations.
- Its current intervention type CHECK is limited to seven action values: `veto`, `rollback`, `freeze`, `unfreeze`, `mode_switch`, `policy_change`, `rollback_failed`.
- The current row shape is an action record (actor, reason, optional proposal/command target, executed_at); it is not an open abnormal-execution work item with lifecycle/status, Run/Task/Barrier anchors, ownership, escalation and resolution evidence.
- The inspected production code does not expose a generic UPDATE/DELETE lifecycle for these rows; they are inserted as intervention-action history. Current readers found by the code search are primarily test/security snapshots, while the supervision feed reads `integration.notification`.

Therefore the chosen “extend `human_intervention`” direction is a schema/domain remodel, not a simple additive HIR status column. A discriminator must preserve the seven action values and all existing readers/filters. HIR-specific columns, status transitions and constraints must be scoped to the HIR record type; action history must not accidentally appear as an open HIR or vice versa. Exact DDL and route/read-model changes remain open.

#### `governance.human_consultation`

Current production operations are in `human_consultation.rs` and the PM API:
- create inserts a pending consultation and, when task-bound, inserts `delivery.task_waiting(reason='needs_decision')` in the same transaction;
- start/decide/cancel/supersede lock the Consultation row; decide/cancel end the corresponding Task waiting row;
- readers include the API list and Task traceability projection.

These operations lock Consultation before changing Task waiting state; they do not acquire the Project activity gate or Task row lock. The current table is a generic formal decision work item, but it does not have the proposed unique HIR/Barrier/successor binding or E6 authorization semantics. The E6 extension must be explicit and typed; generic Consultation creation/decision must not silently release an Execution Barrier or allocate a successor Run.

#### `integration.notification`

Current production writers include supervision feed, AI orchestration and outbox handlers; the supervision feed reader is project-scoped and cursor-based. The current table is a project Feed, with no per-principal recipient/inbox ownership model. It must remain non-authoritative: notification insertion or read state cannot prove process exit, Barrier release or E6 approval. The proposed recipient child table and its unique delivery/idempotency keys need their own transaction and reader/writer audit.

### 10.4 Task waiting is not an Execution Barrier

Current dispatch policy and dependency code read active `delivery.task_waiting` rows as a Task eligibility gate. Consultation, Interaction and Review paths write/end waiting rows with their own semantics. This does not provide the required Task Execution Barrier:

- waiting rows do not bind a specific old Run + Generation + Process Sequence;
- they do not encode E1–E6 evidence class or HIR lifecycle;
- their current readers do not enforce all new Run creation, Review Claim, same-Run reacquire and successor-allocation paths;
- generic consultation or interaction resolution is not equivalent to verified process exit.

Keep Task waiting, Interaction scheduling shield and Execution Barrier as distinct mechanisms. The final Platform dispatchability predicate must evaluate all applicable gates in one transaction rather than treating any one of them as a replacement.

### 10.5 New P0 closure items

1. Add normal Run→Task business writes (report_progress, submit_result, Worker start confirmation and Review completion) to the global lock graph and J01/J02/J04-style deterministic tests.
2. Make SEM the only control-plane entrypoint at cutover; explicitly disable the old Runner MCP Claim/reacquire/command poll/ACK paths and the old Worker dispatch authority, while retaining Harness business MCP.
3. Remodel `human_intervention` with a discriminator and preserve its existing seven intervention-action values and readers; do not conflate action history with HIR lifecycle.
4. Extend `human_consultation` only with typed E6 semantics and unique anchors; generic consultation status must not release Barrier or authorize a successor.
5. Add the Notification Recipient/Inbox lifecycle without changing the existing project Feed semantics or treating notification as safety evidence.
6. Prove that Task waiting, Interaction shield and Execution Barrier are independent gates evaluated by one Platform transaction predicate.

Status remains **Changes Required / Audit In Progress**. The global lock order remains deliberately unfrozen. No code, migration, API/WSS implementation or runtime configuration was changed; Phase 0 remains Not Started.


## 11. Fourth audit pass — Interaction/Continuation/Command transaction paths

This pass traced the concrete Interaction response/consume/retry/cancel paths, Continuation lifecycle hooks, lease progress/renewal and Worker Command ACK. It remains static source review; no implementation was changed.

### 11.1 Confirmed lock sequences

| Transaction path | Observed order | Notes |
|---|---|---|
| Interaction report | Run `FOR UPDATE` → Interaction lookup/insert → Run scheduling-shield UPDATE → Task transition (`FOR UPDATE`) → TaskWaiting insert → Command insert | Run→Task is an additional normal path; interaction row is newly inserted, not an existing conflicting lock |
| Interaction retry | Interaction `FOR UPDATE` → Run lookup/lock/update → TaskWaiting / new Interaction / command writes | Confirms the previously identified Interaction→Run edge |
| Interaction response persisted | Interaction UPDATE (row lock) → Run scheduling-shield UPDATE | Interaction→Run |
| Interaction consumed | ResponseDelivery update → Continuation update → Interaction UPDATE → Run shield UPDATE → TaskWaiting resolve → Task `FOR UPDATE` / transition | A multi-aggregate chain; delivery and continuation FKs add implicit parent-key checks |
| Continue Command ACK | Command `FOR UPDATE` → Run generation read/update scheduling shield → ResponseDelivery update → Continuation started update → Interaction chain update → TaskWaiting resolve → Task `FOR UPDATE` / transition | Command→Run→Interaction/Continuation→Task; the Run generation read is not itself a row lock, but shield UPDATE is |
| Terminate Command ACK/failure | Command `FOR UPDATE` → Run/cleanup updates → Continuation freeze → Task `FOR UPDATE` / transition | Command→Run/Continuation→Task |
| Task cancellation linkage | Task transition obtains Task `FOR UPDATE` → Interaction chain updates/cancel → Run shield update / command writes → Continuation close | Task→Interaction→Run/Continuation |
| Run terminalization | Run terminal UPDATE → Continuation close-by-Run → cleanup enqueue and event/audit writes | Run→Continuation |
| Lease renewal | Run `FOR UPDATE` via `lock_lease` → Run lease UPDATE → Task plain SELECT | Task SELECT is MVCC read, not a Task row lock |
| Progress first-start | Run `FOR UPDATE` → Run lease/progress UPDATE → Task transition (`FOR UPDATE`) | Run→Task; normal business path, not only recovery |

### 11.2 Important corrections and additional conflict edges

1. The earlier lock inversion is broader than report-vs-retry: response-persisted is Interaction→Run, while report/first-start is Run→Interaction/Task. ACK and cancellation introduce Command and Continuation into the same connected graph.
2. The Task cancellation path's order is Task→Interaction→Run/Continuation. Any path holding Run or Command and then waiting for Task can conflict with cancellation if the reverse edge is held concurrently. This is a concrete candidate cycle family; deterministic pair tests must establish each reachable interleaving.
3. `mark_consumed` updates ResponseDelivery and Continuation before Interaction and Task. It can race with continue ACK, which updates Command, Run shield, ResponseDelivery, Continuation, Interaction and Task. Both are intended to be idempotent at individual state predicates, but predicate idempotency is not proof of deadlock freedom.
4. `open_continuation_tx` allocates `MAX(generation)+1` then inserts. Its normal caller currently holds the Run row lock through Interaction report, which serializes same-Run creation; any future caller must preserve that serialization or replace it with a DB uniqueness/sequence allocation protocol.
5. `close_open_by_task_tx` updates all open/started/frozen Continuations for a Task. It is called from Task cancellation after Task row locking; `close_open_by_run_tx` is called after Run terminalization. Their ordering is Task→Continuation versus Run→Continuation and must be covered in the final graph.
6. The cleanup ledger is deliberately separate from Run authority. `claim_batch` locks only cleanup rows with SKIP LOCKED; `mark_completed/failed` update cleanup rows only. Cleanup completion must never be interpreted as authoritative E3 process-exit evidence unless the new process-evidence contract explicitly binds the verified process identity and generation.

### 11.3 Lock graph is connected; no global order can yet be selected

The current evidence establishes at least these directed edges:

- Project → Run → Task (archive/Worker start confirmation/Run claim paths)
- Run → Interaction (report/progress-related paths and shield updates)
- Interaction → Run (retry/response/cancel paths)
- Task → Interaction → Run (Task cancellation linkage)
- Command → Run → Interaction/Continuation → Task (ACK paths)
- Run → Continuation (Run terminalization)
- Task → Continuation (Task cancellation)
- Task graph advisory lock → Task row (terminal Task transitions and dependency graph mutation)

The Project graph advisory lock has a strict pre-row-lock requirement. Existing Review completion can still reach Task transition after locking Review Run, so the advisory-lock contract violation remains open. The graph must additionally include parent-key locks from FK validation and unique-index conflict waits.

Do not “solve” this by documenting a preferred order without changing call boundaries. A viable redesign likely needs a shared transaction entry protocol that resolves immutable scope IDs without row locks, acquires advisory locks in a deterministic aggregate order, then row-locks Project/Task/Run/Interaction/Command/Continuation in one canonical order. The exact order must be derived from all paths and tested; this paragraph is a design direction, not a selected lock order.

### 11.4 New deterministic concurrency cases

Add these to the existing J01–J10 matrix:

- J11 report_interaction vs retry_interaction and response_persisted.
- J12 continue ACK vs mark_consumed (both race for response delivery/continuation/interaction/task effects).
- J13 terminate ACK failure/freeze vs Task cancellation.
- J14 Run terminalization/continuation close vs Task cancellation/close-by-task.
- J15 lease progress first-start vs Task cancellation.
- J16 Worker spawn confirmation vs Task cancellation and Project archive.
- J17 same-Run concurrent open_continuation attempts; assert one generation allocation and one continuation row per intended event.
- J18 cleanup claim/complete vs Run terminalization and new process-evidence ingestion; assert cleanup state never upgrades to authoritative exit evidence.

Every case uses two independent PostgreSQL connections, explicit barriers, bounded lock/statement timeouts, and verifies final aggregate states plus audit/command/delivery/continuation/event effects.

Status remains **Changes Required / Audit In Progress**. This pass expands the connected lock graph but does not select a global lock order. No code, migration, API/WSS implementation or runtime configuration changed; Phase 0 remains Not Started.


## 12. Fifth audit pass — current migration head and late execution-related DDL

The current `master` migration directory contains migrations through **0059** (latest observed: `0059_discovery_round_error.sql`). This pass checked the late migrations that can affect execution ownership, process cleanup, workspace lifecycle or formal human decisions. It does not claim a full replay/semantic review of every migration from 0001 through 0059; the complete chain reconciliation remains open.

### 12.1 Relevant late migration findings

| Migration | DDL effect | SEM relevance |
|---|---|---|
| 0046 `human_consultation` | Creates generic four-state Consultation; task FK is `ON DELETE SET NULL`; no composite tenant/project/task FK; no HIR/Barrier/successor unique anchors | E6 cannot be inferred from this table's generic `decided` state; E6 needs typed binding and same-scope FK integrity |
| 0053 `device_single_active_run` | Partial unique index `uq_task_run_device_active` on `lease_client_id` for claimed/running | Enforces one active Run per device identity, not one process per Runner host or SEM connection; new SEM Runner slot/concurrency authority must preserve and deliberately replace/extend this invariant |
| 0054 `task_run_cleanup_claim_fencing` | Adds cleanup claim token and due index | Cleanup worker claims are fenced independently; no Platform Run lease/generation authority is transferred |
| 0055 `workspace_reclamation_ledger` | Adds separate workspace reclamation ledger with Project/Repository/RunRepository FKs and unique resource keys | Filesystem reclamation is separate from process termination and Run state; FK restricts deletion while resource ledger exists |
| 0056 `workspace_reclamation_bytes` | Adds logical reclaimed byte count | Metrics/accounting only; no execution authority |
| 0057 `workspace_reclamation_totals` | Adds cumulative resource-kind totals | Metrics/accounting only; no execution authority |
| 0058 `external_commit_adoption` | Adds external Commit discovery/adoption tables and repository scan anchors | No direct Run ownership change identified in this DDL |
| 0059 `discovery_round_error` | Adds discovery session error fields | No direct Run ownership change identified in this DDL |

### 12.2 Migration-level integrity observations

1. `human_consultation` has a task FK with `ON DELETE SET NULL`, but no composite FK that proves the Consultation's tenant/project/task all belong to the same scope. This is a schema integrity gap for future E6 use, not a demonstrated current cross-tenant exploit; existing service authorization and data model need separate audit.
2. The device-active partial unique index is a valuable DB backstop, but its key is `lease_client_id` and it only covers claimed/running. It does not model SEM's Runner connection epoch, host identity, supervisor session, resource reservation or dispatch operation. SEM must not equate device uniqueness with Runner process uniqueness.
3. Workspace reclamation is intentionally derived-resource bookkeeping. Its completion cannot prove process exit; the process may have exited before cleanup, or cleanup may fail after exit. Conversely, cleanup completion is not a substitute for a process-specific, generation-fenced E3 receipt.
4. The late migrations 0055–0057 introduce separate filesystem reclamation state and counters. Do not merge these into Run status or the proposed process-evidence ledger.
5. The current migration head is 0059, whereas the existing schema inventory snapshot is dated 2026-11-15 and predates at least the PA-08 migrations. It is not sufficient evidence for current schema constraints/triggers. Rebuild a fresh schema inventory from the exact current migration head before final DDL approval.

### 12.3 Remaining migration audit

- Inspect baseline DDL sections for `task_run`, `task_interaction`, `worker_command`, `continuation`, `interaction_response_delivery`, `human_intervention`, `task_run_cleanup`, their unique indexes, FKs and triggers.
- Inspect every intervening migration 0002–0059 for DROP/ADD/RENAME of those constraints and for trigger functions that may introduce additional writes.
- Replay the full migration chain against an empty PostgreSQL database and capture `pg_constraint`, `pg_index`, `pg_trigger`, `pg_proc` definitions at the resulting head.
- Compare that live-schema capture with the checked-in migration-derived expectation. The 2026-11-15 inventory must remain historical evidence only.
- Add DDL tests for the composite tenant/project/task identity guarantees required by HIR, Barrier, E6 and process evidence.

Status remains **Changes Required / Audit In Progress**. The latest migration head is identified as 0059, but the full 0001–0059 schema/trigger reconciliation is not yet complete. No global lock order is selected; no code, migration, API/WSS implementation or runtime configuration changed; Phase 0 remains Not Started.
