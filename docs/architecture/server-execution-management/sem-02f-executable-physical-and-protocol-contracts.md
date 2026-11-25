# SEM-02F — Executable Physical and Protocol Contracts

- Status: **Candidate / Review Pending / Not an approved ADR**.
- Code evidence baseline: GitHub `master@4bc78620f54440a21a113cf7cdb14964d1a14dcb`.
- Existing SEM design baseline: SEM-02E branch `docs/sem-02e-architecture-convergence`.
- Scope: translate SEM-02E decisions into concrete Platform schema, transaction, protocol and acceptance contracts.
- This document is a design specification, not executable SQL and not implementation authorization.

## 1. Verified current-code facts

1. `apps/ai-pm-worker/src/main.rs` calls `run_executor::reconcile_orphans` once at worker startup. The dispatch loop repeatedly calls `claim_and_start`, `poll_active_runs`, `interaction_timeout_sweep`, cleanup and finished-process cleanup, but does not periodically call `reconcile_orphans`.
2. Current `reconcile_orphans` selects `running` rows with `executor_session IS NOT NULL` and lease expired by more than one hour, then B06-D3 directly changes them back to `queued`. It does not establish process death and does not apply the normal claim candidate's Runner-project exclusion.
3. Normal claim candidate discovery selects `queued` and expired `claimed` delivery Runs. It locks the candidate Run, then the Task row; `candidate_shield != 'none'` is currently checked only in the expired-claimed recovery branch. The ordinary queued path can therefore miss that check.
4. `insert_task_run` is the shared Run creation helper and requires callers to hold the Task row lock. It is used by recovery and outbox paths, but every direct INSERT must still be audited.
5. Interaction creation currently writes `task_interaction`, `scheduling_shield=human_wait`, Task `awaiting_decision`, `task_waiting`, terminate command and audit in one transaction. It does not create a notification. Continue command consumption is in the Runner command path; the SEM-local CodexExecutor path needs an equivalent adapter.
6. `governance.human_intervention` is currently action history with `intervention_type` constrained to veto/rollback/freeze/unfreeze/mode_switch/policy_change/rollback_failed. `integration.notification` is a project feed read by `supervision/feed.rs`; multiple existing producers write to it. Its `read_at` is on the feed row and it has a unique `source_proposal_id`.
7. `governance.human_consultation` has the four states `pending/in_progress/decided/cancelled`, decision completeness checks and a supersede link. Its Task FK currently uses `ON DELETE SET NULL`.
8. `delivery.task` has `assignee_id`; `core.project_member` has owner/member roles. `delivery.task_waiting` and Interaction are separate existing mechanisms and must not be conflated with HIR.
9. The Platform and SEM databases remain independent. SEM must not connect to Platform PostgreSQL. SEM is an independent service, not an optional in-process Platform Worker role.
10. RabbitMQ already exists as an independent single-instance service without clustering.

## 2. Platform schema: Task Execution Barrier

Create a Platform-owned table named `delivery.task_execution_barrier`. Do not store the authoritative Barrier only in SEM DB.

Required columns:

| Column | Type / rule | Meaning |
|---|---|---|
| id | UUID PK | Barrier identity |
| tenant_id, project_id, task_id | NOT NULL, composite FKs | Safety scope |
| origin_run_id | UUID NOT NULL | Run whose execution became uncertain |
| origin_generation | integer NOT NULL | Exact generation |
| state | CHECK: `active`, `risk_accepted_unconfirmed`, `released` | Barrier lifecycle |
| evidence_class | nullable CHECK: E1–E5 | Latest classification; E6 is not evidence |
| evidence_ref | nullable text/JSON reference | Evidence pointer, not free-form authority |
| authorized_successor_run_id | nullable UUID, UNIQUE when non-null | The only E6-authorized successor |
| created_by / created_at | NOT NULL | Creation audit |
| updated_at | NOT NULL | Last state change |
| released_by / released_at | nullable | Set only on evidence-based release |
| release_evidence_ref | nullable | Exact E1/E2/E3 evidence reference |

Constraints and indexes:

- Partial unique index: one unreleased Barrier per Task, where `state IN ('active','risk_accepted_unconfirmed')`.
- Unique partial index on `authorized_successor_run_id` when non-null.
- Composite foreign keys must prove Task, Project, Tenant and origin Run belong together.
- A released Barrier is immutable except for audit metadata; never delete it as part of normal recovery.
- `risk_accepted_unconfirmed` remains an unreleased Barrier. It is not equivalent to released.

**Dispatch exception:** when a Task has an unreleased Barrier in `active`, no Run is dispatchable. When its state is `risk_accepted_unconfirmed`, only the exact `authorized_successor_run_id` may pass the Barrier predicate. No other Run, retry or newly inserted Run may pass. After that one successor finishes, the old Barrier remains; another successor requires a separately reviewed policy, not an automatic retry.

The Task row is the serialization point. Every Barrier create/release/E6 operation and every Run creation/claim/requeue transaction must lock the Task and re-check the Barrier before committing.

## 3. HIR: reuse `governance.human_intervention` without semantic collision

The selected direction is to reuse and extend the existing table, not create a parallel HIR master table. Because the existing table currently means executed intervention actions, introduce an explicit discriminator:

- `record_kind='action'`: preserve existing veto/rollback/freeze/etc. rows and current action semantics.
- `record_kind='hir'`: one durable human-intervention work item.

For the HIR row kind:

- Make `intervention_type` nullable; require it for `action`, require it NULL for `hir`.
- Keep `actor_id` as the creator for HIR rows; keep `reason` as the initial summary.
- Add `task_id`, `run_id`, `lease_generation`, `barrier_id`, optional `interaction_id`, `category`, `severity`, `status`, `assigned_to`, `resolved_by`, `resolved_at`, `disposition`, and `evidence_refs`.
- HIR rows require Task/Run/Generation/Barrier/category/severity/status. Action rows must not accidentally satisfy HIR-only fields.
- One HIR per Barrier: unique partial index on `barrier_id WHERE record_kind='hir'`.
- Keep action records append-only in meaning. HIR lifecycle updates must not rewrite or impersonate action records.

HIR state domain is exactly the seven states in `state-machines.md`: `open`, `assigned`, `awaiting_user`, `in_progress`, `resolved`, `closed`, `cancelled`. Only explicit reopen moves closed/cancelled back to open. HIR closure never releases a Barrier.

Do not use `delivery.task_interaction` as HIR. Interaction remains the Agent's request for input/decision/permission; HIR is an execution exception and human recovery work item. Do not overload `delivery.task_waiting` as HIR either; its current contract is Task workflow waiting and Interaction coordination.

## 4. E6: extend `governance.human_consultation`

Keep its existing four-state lifecycle, decision completeness CHECK and supersede chain for ordinary consultations. Add typed E6 scope:

- `decision_kind`: `general` or `execution_risk_acceptance`.
- `hir_id`, `barrier_id`, `successor_run_id`.
- `residual_risk_summary`, `mitigations`.
- Explicit risk acknowledgement fields: `risk_confirmed_by`, `risk_confirmed_at` (a distinct confirmation action from opening the consultation).
- E6 rows require `task_id`, HIR, Barrier, successor, decision content, decided actor/time, residual-risk summary, mitigations and risk confirmation.
- E6 rows must be `status='decided'` before authorization is effective.
- Unique partial index on `barrier_id` for E6 and unique partial index on `successor_run_id` for E6.
- E6-specific FK behavior must not permit Task/Barrier/Successor anchors to become NULL through `ON DELETE SET NULL`; use restrictive deletion semantics for E6 anchors.

E6 authorization is one Platform transaction:

1. Lock Project → origin Run → Task → Barrier (follow the globally documented lock order).
2. Revalidate exact origin Run/Generation, active Barrier and HIR.
3. Validate the authorized human principal and explicit risk confirmation.
4. Create exactly one successor Run in a reserved/non-dispatchable state.
5. Insert the decided Human Consultation with typed E6 anchors.
6. Set Barrier to `risk_accepted_unconfirmed` and bind `authorized_successor_run_id`.
7. Append audit and commit.

The successor is dispatchable only after the transaction commits and only because its ID exactly matches the Barrier authorization. E6 never writes E1/E2/E3, never sets `released_at`, and never releases the old Barrier.

## 5. Notification: preserve the project feed; add recipient inbox membership

Do not change the meaning of existing `integration.notification.read_at` or break existing project-feed producers/readers.

Keep `integration.notification` as the project-level notification/event feed. Add a child table `integration.notification_recipient`:

- `id`, `tenant_id`, `project_id`, `notification_id`;
- nullable `recipient_principal_id` (NULL only for explicit unassigned queue item);
- `assignment_state`: `assigned` / `unassigned`;
- `delivery_state`: `available` / `failed` (V1 in-app inbox row is available when committed);
- `attempt_count`, `next_attempt_at`, `last_error` reserved for optional external delivery adapters;
- `delivered_at`, per-recipient `read_at`, `created_at`.

Constraints:
- Unique `(notification_id, recipient_principal_id)` when recipient is non-null.
- At most one unassigned row per notification.
- Recipient principal must belong to the same tenant; project membership/visibility is checked by the resolver and read API.
- Parent notification and recipient rows are inserted in the same Platform transaction as HIR/Interaction. A notification failure must not leave a HIR/Interaction committed without its durable in-app notification intent.
- Existing project feed remains unchanged. New personal Inbox query joins recipient rows and filters to the authenticated principal; unassigned queue is visible only to authorized project operators.
- Do not use parent `read_at` as per-user read state.

V1 recipient resolution:
1. Use `delivery.task.assignee_id` if it is an active member of the project.
2. Otherwise notify active project members with role `owner`.
3. If no eligible recipient exists, insert an explicit unassigned recipient row and raise an operational alert. Never silently drop the notification.

HIR creation and Interaction creation both create notification + recipient rows immediately in their existing business transaction. The 120-second Interaction deadline remains only the user's response deadline; it is not a notification delay or HIR timeout.

No separate delivery table is required for V1 in-app delivery. Add a channel-attempt table only if email/push/webhook fan-out is approved and one recipient may have multiple independently retried channels.

## 6. Platform process identity sequence and Lease Renewal fence

Platform must persist the active process sequence because Platform owns Lease Renewal and cannot query SEM DB.

Add `delivery.task_run_process` (Platform-owned process identity registry):

- `id` UUID PK;
- `tenant_id`, `project_id`, `task_id`, `run_id`;
- `lease_generation`, `process_sequence` (positive integer);
- `device_id`, `boot_id`, `process_instance_id`;
- `os_pid`, `os_process_start_identity` (PID alone is insufficient);
- `harness_kind`, `launch_reason` (`initial_start`, `interaction_continue`, approved recovery);
- `registered_at`, `started_at`;
- nullable `exit_observed_at`, `exit_code`, `exit_evidence_kind`, `exit_evidence_id`, `exit_command_id`.

Constraints:
- Unique `(run_id, lease_generation, process_sequence)`.
- Unique `(run_id, lease_generation, process_instance_id)`.
- Process identity columns are immutable after registration.
- Exit fields can be written once by an authenticated evidence endpoint; duplicate same evidence is idempotent, conflicting evidence is quarantined.
- `delivery.task_run.active_process_sequence` is the Platform-authoritative fence. It points to the only process identity allowed to renew the current Run+Generation.
- Composite FKs bind process rows to the same Task/Project/Tenant/Run.

Protocol:

1. Initial start: SEM-local adapter or SEM service registers sequence 1 with exact process identity before the first process-bound Lease Renewal. Platform validates current Run/Generation/Lease and atomically sets active sequence.
2. Continue command issuance: Platform locks the Run, reserves the next sequence in the command/continuation record, and binds the terminate/continue command to the expected old/new sequence.
3. `continuation.consumed`: after reply injection and successful new process spawn, execution adapter sends the reserved sequence and new process identity. Platform validates current Run/Generation, Interaction/continuation and command, then atomically inserts the process row and advances `active_process_sequence`.
4. Lease Renewal must include `process_sequence` and `process_instance_id`. Platform rejects renewal unless both match the active process row and current Run+Generation+Lease.
5. `runner.process.exit` can be reported for any registered sequence. Natural exit has no `command_id`; command-triggered exit includes the exact command ID. Evidence for an older sequence may close only that old row; it cannot clear or replace a newer active sequence.
6. Barrier release requires Platform to verify that every registered process identity for the origin Run+Generation is terminal with accepted E1/E2/E3 evidence, and that no current active identity remains. A late exit for sequence N cannot release a Barrier if sequence N+1 is active.

The exact placement of the sequence reservation field (typed `worker_command` column versus a continuation-operation record) must be chosen during the SQL migration design. Do not rely only on JSON payload fields for uniqueness or locking.

## 7. Platform DB-only periodic orphan scanner

Replace startup-only orphan reconciliation as the sole safety mechanism. Keep the scanner in the Platform worker/database boundary; it must not call SEM, Runner, CodexExecutor or RabbitMQ.

Candidate predicate:

- Run kind = delivery;
- status in `claimed/running`;
- lease expired beyond configurable grace;
- Interaction `scheduling_shield='none'`;
- no accepted E1/E2/E3 evidence for the active process identity sequence;
- no existing unreleased Task Barrier.

Suggested initial cadence: every 15–30 seconds. Grace is configurable and initially conservative (suggested 120 seconds after lease expiry); tune with measured lease/heartbeat latency before production. The one-hour threshold is removed as a safety trigger.

For each candidate, in one transaction:

1. Lock Project → candidate Run → Task; re-read status, generation, lease expiry, shield and process fence.
2. Re-check the candidate predicate and any accepted exit evidence.
3. Insert Task Barrier under the unique active-per-Task constraint.
4. Insert/associate one HIR row in `governance.human_intervention`.
5. Insert project-feed notification and recipient inbox rows.
6. Append audit.
7. Commit.

If a concurrent scanner wins, the loser observes the existing Barrier and does nothing. If the candidate gains accepted E1/E2/E3 evidence before the lock/recheck, do not create a Barrier; route to the evidence-based safe recovery path.

B06-D3 is removed as an independent direct `running → queued` path and folded into this scanner. The scanner never marks a Run safe merely because the lease expired. It creates a Barrier/HIR; it does not automatically requeue.

The scanner is periodic, idempotent, and safe across Platform Worker restarts. Startup may invoke one immediate pass as an optimization, but correctness comes from the periodic loop.

## 8. One dispatchability predicate

Implement one Platform transaction helper, conceptually:

```text
is_dispatchable(task, run):
  task/project are active and eligible
  run is an eligible delivery Run in the expected state
  run.scheduling_shield == none
  no active Task Execution Barrier exists
    OR (
      barrier.state == risk_accepted_unconfirmed
      AND barrier.authorized_successor_run_id == run.id
      AND matching E6 consultation is decided and complete
    )
  current lease/generation/claim conditions pass
  device/project binding and concurrency conditions pass
```

The predicate must be called under the Task row lock and revalidated in the same transaction by:
- normal queued claim;
- expired claimed recovery;
- B3-1/B3-2;
- retry and backoff requeue;
- B06-D3 replacement/removal;
- all direct Run creation helpers;
- outbox TaskReady handlers;
- failure/review paths that create a successor delivery Run;
- handoff and E6 successor reservation.

A pre-query filter is only an optimization; it is never the final safety check. Any code path that can create or dispatch a Run without this predicate is a release blocker.

## 9. RabbitMQ boundary

RabbitMQ is an existing independent single-instance service without clustering. V1 does not require it for correctness.

Allowed future use, only if separately approved: non-authoritative wake-up hints for notification or SEM inbox processing. A lost message, broker restart, duplicate delivery or broker outage must be repaired by database polling/outbox-inbox reconciliation.

Forbidden use:
- Claim or Lease authority;
- process-exit/E1/E2/E3 evidence;
- Barrier creation/release;
- HIR/E6 decision authority;
- sole delivery path for Platform→SEM events;
- sole notification persistence.

Do not add a RabbitMQ cluster or a new broker deployment as part of SEM.

## 10. Migration and implementation order

1. Add Task Barrier and process identity schema plus FK/index/trigger tests.
2. Extend existing human_intervention with record discriminator and HIR lifecycle while preserving action row behavior.
3. Extend human_consultation with typed E6 anchors and restrictive integrity.
4. Add notification_recipient and recipient resolver; preserve existing feed API and read_at.
5. Add Platform process registration, continuation-consumed, process-exit evidence and process-bound Lease Renewal APIs.
6. Add unified dispatchability predicate and convert every Run creation/claim/recovery/requeue path.
7. Replace B06-D3 direct requeue and startup-only reconcile dependency with periodic DB-only scanner.
8. Add Runner and SEM-local execution adapters for terminate/continue and process evidence.
9. Run full empty-database migration, concurrency, restart and failure-injection acceptance.

No implementation starts until the exact SQL, lock order, API schemas and tests are reviewed and approved.

## 11. Mandatory acceptance cases

- Worker starts once, then stays up: orphan is detected without restart.
- Worker restarts repeatedly: duplicate Barrier/HIR/notification rows are impossible.
- Two scanners race on the same Task: one active Barrier and one HIR only.
- A new Run row is inserted while a Task Barrier exists: it cannot be claimed.
- A Task has a Barrier and a second Run row is created through each of the three known creation paths: every path rejects or creates only the exact E6-bound successor.
- B06-D3 cannot bypass shield or Barrier.
- Interaction `human_wait` / `start_wait` is not misclassified as orphan by the DB scanner.
- Interaction continue starts process sequence N+1 in the same Run+Generation; Lease Renewal from N is rejected after N+1 is accepted.
- Sequence N exit evidence arrives after N+1 starts: it updates only N and does not clear N+1.
- Natural exit without command_id is accepted only when the full registered process identity matches.
- A conflicting PID/boot/process identity is quarantined and cannot release a Barrier.
- E6 authorizes one exact successor; a second successor, duplicate E6 or mismatched Task/Barrier/HIR is rejected.
- E6 does not release the Barrier; after the one successor completes, no further Run can dispatch until the Barrier is independently released.
- HIR closed/cancelled, Interaction consumed, Runner offline, Workspace missing, RabbitMQ ACK and lease expiry alone never release a Barrier.
- Notification recipient resolution: assignee, project owner fallback, and explicit unassigned queue.
- Existing project-feed producers/readers and parent `read_at` behavior remain unchanged.
- SEM database outage, RabbitMQ outage and WSS disconnect do not alter Platform execution authority.

## 12. Remaining decisions before SQL/API freeze

- Confirm the proposed `record_kind` discriminator strategy for `governance.human_intervention` (preferred over a parallel HIR master table).
- Confirm that V1 notification is in-app inbox only, with external channels deferred.
- Confirm the initial orphan grace value after measuring current lease and heartbeat settings.
- Decide the exact typed reservation field location for continuation process sequence.
- Complete a full search of all direct Run INSERTs and every notification read/write route before drafting executable migrations.

Until these are closed, SEM-02F remains a candidate specification and the overall architecture status remains **Changes Required / Review Pending**.
