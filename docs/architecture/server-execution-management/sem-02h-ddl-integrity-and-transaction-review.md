# SEM-02H — DDL Integrity and Transaction Review

- Status: **Changes Required / Review Pending**.
- Reviewed draft: [SEM-02G](./sem-02g-database-and-api-contract-draft.md).
- Current code baseline: GitHub `master@d0e72fa6805aebeadf1b282e430deba493072fd6`.
- Current schema source blobs fetched from master: `migrations/0001_baseline.sql` blob `6f1e9e59a4a539a26bf83d1826c48ddaf9fea566`; `migrations/0046_human_consultation.sql` blob `96ff323d75f182b5587cc12f0cba0dd33ac51bae`.
- This is a read-only design review. No migration or application code was changed.

## 1. Executive result

SEM-02G is a useful physical-contract draft, but **it is not yet safe to translate directly into migrations**. The review found:
- 4 P0 relational/authorization defects in the candidate DDL;
- 4 P1 evidence, inbox and state-integrity gaps;
- 3 unresolved transaction/API contracts;
- a stale source-baseline declaration in SEM-02G.

The issues below are concrete DDL or transaction properties, not stylistic preferences.

## 2. P0 — relational integrity defects

### 2.1 HIR Run FK does not prove that the Run belongs to the HIR Task

SEM-02G currently declares:

```sql
FOREIGN KEY (project_id, run_id)
REFERENCES delivery.task_run(project_id, id);
```

This proves only same Project. It does not prove `human_intervention.task_id = task_run.task_id`. The draft already proposes `uq_task_run_project_task_id`; use it:

```sql
FOREIGN KEY (project_id, task_id, run_id)
REFERENCES delivery.task_run(project_id, task_id, id);
```

The FK is nullable only for action rows; the HIR row-shape CHECK makes all three columns non-null for HIR records.

### 2.2 E6 composite HIR FK has no matching referenced UNIQUE key

SEM-02G references:

```sql
REFERENCES governance.human_intervention(task_id, barrier_id, id)
```

But the HIR draft creates only a partial unique index on `barrier_id`. PostgreSQL foreign keys require a non-partial unique/primary key over the exact referenced column set. Add a non-partial unique constraint:

```sql
ALTER TABLE governance.human_intervention
  ADD CONSTRAINT uq_hir_task_barrier_id
  UNIQUE (task_id, barrier_id, id);
```

Action rows have NULL task/barrier values, so ordinary PostgreSQL UNIQUE NULL semantics allow multiple action rows while providing a valid FK target. Keep the existing partial unique index on `barrier_id` to enforce one HIR per Barrier.

### 2.3 Barrier release CHECK accepts NULL evidence_class

The current expression contains `evidence_class IN ('E1','E2','E3')`. When `evidence_class` is NULL, the expression evaluates to UNKNOWN; PostgreSQL CHECK accepts UNKNOWN. Therefore a released Barrier can pass without an evidence class.

Use explicit non-null checks and require the release actor:

```sql
CHECK (
  (state = 'released'
   AND released_by IS NOT NULL
   AND released_at IS NOT NULL
   AND release_evidence_ref IS NOT NULL
   AND evidence_class IS NOT NULL
   AND evidence_class IN ('E1','E2','E3'))
  OR
  (state <> 'released'
   AND released_by IS NULL
   AND released_at IS NULL
   AND release_evidence_ref IS NULL)
)
```

If the policy intentionally allows system actors, represent the actor as a typed principal/service identity rather than making `released_by` optional.

### 2.4 E6 Barrier state can exist without a formal E6 decision row

The Barrier currently requires `authorized_successor_run_id` for `risk_accepted_unconfirmed`, but it does not require a corresponding `human_consultation` E6 record. The reverse relation is not sufficient: an application bug could set the Barrier state and successor without persisting the formal decision.

Add a nullable `e6_consultation_id` to Barrier and require it whenever state is `risk_accepted_unconfirmed`. Add a deferrable FK to `governance.human_consultation(id)`; keep the E6 consultation's unique Barrier and successor indexes. A deferred constraint trigger (or equivalent single Platform transaction guard) must validate that:
- the referenced consultation has `decision_kind='execution_risk_acceptance'` and `status='decided'`;
- consultation Task, Barrier, HIR and successor match the Barrier;
- the Barrier's authorized successor equals the consultation's successor;
- the E6 consultation and reserved successor commit atomically.

The circular Barrier↔Consultation relation must be created with DEFERRABLE constraints or validated by a deferred constraint trigger. Do not permit a committed `risk_accepted_unconfirmed` Barrier with no E6 record.

## 3. P1 — integrity and evidence model gaps

### 3.1 Task/Project/Tenant scope must be consistent across the entire E6 chain

Current FKs validate pieces of the relation, but the candidate does not yet prove one consistent tuple across:

`tenant → project → task → barrier → HIR → consultation → successor Run`.

Add exact composite candidate keys/FKs where the schema permits. Where a clean FK would require excessive duplicate keys, use one deferred constraint trigger that validates the entire tuple under the Task row lock. Do not rely only on application-side joins for tenant/project isolation.

Also add a composite Task+Run+Interaction FK for optional HIR interaction linkage. The present `(project_id, interaction_id)` proves same Project but not same Task/Run.

### 3.2 Process identity and process-exit evidence are different aggregates

SEM-02G places a single exit tuple (`exit_observed_at`, `exit_code`, `exit_evidence_kind`, `exit_evidence_id`) on `task_run_process` and describes those fields as write-once. This is insufficient for an append-only evidence protocol:
- the API advertises `event_id` idempotency, but the schema does not persist it;
- a later stronger E3 observation cannot be appended after an earlier E1/E2 observation without mutating write-once columns;
- a natural exit, terminate-command result and later reconnect reconciliation are distinct observations that may arrive late or out of order;
- conflicting observations need durable quarantine without overwriting the process identity.

Recommended separation:
- `delivery.task_run_process`: immutable process identity + registration event identity; no mutable single exit evidence tuple.
- `delivery.task_run_process_evidence`: append-only observations with `tenant_id`, `event_id`, `run_id`, `lease_generation`, `process_sequence`, `event_kind`, optional `evidence_class`, optional `command_id`, `observed_at`, `evidence_digest`, evidence reference, and acceptance classification (`accepted`, `diagnostic_only`, `quarantined`).

Required uniqueness: `UNIQUE(tenant_id,event_id)`; duplicate event ID + same digest returns the stored result; same event ID + different digest is an idempotency conflict. Add FK to the exact process identity. Keep late old-generation/old-sequence evidence appendable as diagnostic history, but never let it mutate a newer active pointer or release a Barrier.

### 3.3 Enforce one OS process identity cannot be registered to two Runs

Add a unique identity fence across the registry, e.g. `UNIQUE(device_id, boot_id, process_instance_id)` (or the exact stable OS identity tuple). Otherwise a faulty Runner/SEM retry could bind one live OS process to two Run identities and undermine the single-writer invariant.

### 3.4 HIR lifecycle CHECKs are incomplete

The current CHECKs ensure timestamp pairs in several states, but do not require:
- `status='assigned'` ⇒ `assigned_to IS NOT NULL AND assigned_at IS NOT NULL`;
- HIR `evidence_refs` is a JSON array;
- category/severity values belong to a defined vocabulary;
- state-specific actor/time tuple completeness for every terminal state.

The HIR transition service must also lock the HIR row, validate the single state machine in `state-machines.md`, and append audit/action history in the same transaction. If a DB trigger is chosen, specify how legitimate reopen/supersede operations work. Do not allow an E6 consultation or Barrier to be edited to erase a previously decided risk acceptance.

### 3.5 Notification recipient row mixes Inbox visibility with delivery retry

The current draft gives an in-app Inbox row `delivery_state`, `attempt_count`, `next_attempt_at`, `last_error` and `delivered_at DEFAULT now()`. In V1, the recipient row is created in the same Platform transaction as the notification intent; it is not an external delivery attempt. Calling it delivered and storing retry fields confuses durable Inbox creation with external channel delivery.

V1 recommendation:
- `notification_recipient` is the per-principal Inbox row: notification, recipient (nullable only for explicit unassigned queue), assignment state, `read_at`, created time, assigned-by/time and audit reference.
- Remove delivery retry fields from this row.
- If/when email, push or another channel is introduced, add a separate `notification_delivery_attempt` ledger keyed by recipient row + channel + attempt number, driven from the transactional outbox.
- Add a stable notification event idempotency key (tenant-scoped) so retrying `interaction.created` or HIR state events cannot create duplicate Inbox items.
- Preserve parent `integration.notification.read_at` semantics; do not synchronize it implicitly with per-user reads.

### 3.6 RabbitMQ role

RabbitMQ is already deployed as an independent single-instance service without clustering. Keep the following boundary:
- Platform DB + transactional outbox remain the durable authority for notification/event intent.
- RabbitMQ may be used as an optional asynchronous fan-out transport for non-authoritative downstream consumers, if a concrete consumer requires it.
- A RabbitMQ outage must not lose HIR/Interaction/Inbox state, change Run/Lease/Barrier state, or block Platform–SEM correctness.
- Do not route Claim, Lease Renewal, command delivery, process-exit evidence, Barrier release or E6 authorization through RabbitMQ.
- Consumers must be idempotent and recover from outbox replay; do not assume broker clustering/high availability.

## 4. P0/P1 protocol and transaction blockers

### 4.1 The current API examples do not yet define event identity persistence

All process APIs carry `event_id`, but no authoritative Platform table stores event ID + body digest + committed result for all event types. The process-evidence ledger above should provide this for exit/reconciliation events. Initial registration and continuation consumption must also persist their event identity (or use an explicit event-receipt table) so the API promise "same event ID returns original result" is actually enforceable.

### 4.2 Continue reservation and terminate race

The command CHECK only verifies that a continue command's new sequence is greater than its target. It does not serialize:
- duplicate continue commands for the same Interaction/continuation;
- two competing continuations against the same active sequence;
- terminate of sequence N racing with continue reservation of N+1;
- a late terminate result for N arriving after N+1 is active.

Before implementation, define one Run-row-locked transition:
1. validate current Run/Generation and active process sequence N;
2. reserve exactly one continuation command and N+1;
3. mark the prior process/command relation;
4. on consumed receipt, atomically register N+1 and advance active pointer;
5. late exit evidence for N updates only N's evidence row and cannot clear N+1.

Use unique constraints on continuation identity and a conditional update of the active pointer. Command result and process-exit evidence remain separate.

### 4.3 Lock order is not yet proven globally

SEM-02G proposes Project → Run → Task → Barrier → HIR/Consultation, but Run creation uses Project → Task → Barrier. The document has not demonstrated that every existing claim/recovery/Interaction/E6/sequence path follows a compatible order. Since the Task row is the Barrier serialization point, produce a lock graph for every transaction touching these entities and prove no path acquires Run after Task while another acquires Task after Run. Do not freeze the proposed order until checked against the current application transactions.

## 5. Baseline and migration notes

- SEM-02G labels its source baseline `master@4bc78620...`; the PR base is now `master@d0e72fa...`. The current master migration blobs fetched for this review are listed at the top of this report. Update the baseline declaration and repeat the schema-key audit against the exact merge-base/current master before writing a migration.
- Existing `governance.human_intervention.intervention_type` is NOT NULL and has an action-only CHECK. The discriminator proposal must preserve all action readers/writers and must not leave any query assuming `intervention_type IS NOT NULL` for every row.
- Existing `governance.human_consultation.task_id` uses `ON DELETE SET NULL`; E6-specific non-null checks make deletion fail for decided E6 rows, but this must be made an explicit restrictive FK policy rather than an accidental CHECK failure.
- Existing `integration.notification` has a project Feed `read_at` and a unique nullable `source_proposal_id`; preserve both and add an independent idempotency contract for HIR/Interaction notifications.

## 6. Required next deliverable before migration authoring

Produce SEM-02I with:
1. corrected complete DDL (all referenced unique keys declared before FKs, no SQL CHECK UNKNOWN loopholes, all tenant/project/task/run relations proven);
2. append-only process evidence ledger and idempotent event receipt rules;
3. E6 circular-reference/atomic successor reservation design;
4. Inbox-only recipient schema and optional RabbitMQ fan-out boundary;
5. a transaction lock graph checked against every existing Platform code path;
6. explicit API request/response schemas, auth scopes, event idempotency, conflict behavior and WSS ACK levels.

Until SEM-02I passes review, SEM-02G remains a draft and must not be copied into a migration. No Phase 0 implementation is authorized.


## 7. Source-level transaction lock audit — confirmed findings

A targeted read of current master application code shows that the lock graph is not merely undocumented; it is currently non-uniform:

| Path | Observed order | Source |
|---|---|---|
| Claim | Project → Run → Task | `run_dispatch/claim.rs:417,445-462,522` |
| TaskReady creation | Project → Task → INSERT Run | `pm-infrastructure/outbox_handlers.rs:60-90, 210-250` |
| Interaction report | Run → Interaction → later Task | `interaction.rs:129,197,518` |
| Interaction retry | Interaction → Run | `interaction.rs:783,816` |
| Interaction cancel | Interaction UPDATE → Run UPDATE → Task FOR UPDATE | `interaction.rs:697-740` |
| Interaction consumed | Interaction UPDATE → Task FOR UPDATE | `interaction.rs:431-587` |
| Lost-run recovery | Run → Task | `run_executor.rs:1288-1298` |
| Orphan reconciliation | Run UPDATE → Task UPDATE; no explicit initial FOR UPDATE/Project lock | `run_executor.rs:480-570` |
| Failure retry | Run marker UPDATE (separate autocommit) → Task UPDATE → INSERT successor Run | `review/failure.rs:87,188-214` |
| Project archive | Project → queued Run rows | `archive.rs:65-96` |

### 7.1 Existing Interaction lock inversion

There is a concrete lock-order inversion:
- `report_interaction` locks the Run first, then locks the open Interaction chain row (`interaction.rs:129,197`);
- `retry_interaction` locks the Interaction row first, then locks the Run (`interaction.rs:783,816`);
- `cancel_open_interaction_tx` updates the Interaction row before updating its Run (`interaction.rs:697-740`).

Concurrent report/retry or report/cancel against the same Run/Interaction chain can therefore form a Run↔Interaction wait cycle. This is an existing concurrency defect candidate and must be reproduced with a two-transaction test before claiming it is fixed. SEM's new Barrier/HIR locks must not be layered on top of this inversion.

### 7.2 Orphan reconciliation is not a safe template for the periodic Barrier scanner

Current `reconcile_orphans`:
- selects candidate IDs without row locks;
- appends suspicion audit in a separate transaction;
- updates Run to queued in another transaction;
- then updates Task blocked→ready;
- does not lock Project, Task, or a Barrier and does not atomically create an E4/HIR Barrier.

This confirms the periodic Phase 0 scanner must be a new Platform-only transactional path, not a wrapper around the existing B06-D3 sequence. The new scanner must re-read and lock current state, validate expiry/grace/shield/absence of E1-E3, then create Barrier + HIR + notification + audit atomically. It must never queue/release the Run before the Barrier is committed.

### 7.3 Required lock-graph remediation

Before migration:
1. Choose and document one lock order for every path touching Project, Run, Task, Barrier, Interaction, HIR and Human Consultation.
2. Refactor retry/cancel/report to eliminate Run↔Interaction inversion.
3. Refactor orphan reconciliation into a single transaction with a conditional Run state transition and Barrier/HIR creation; no separate audit transaction before the state mutation.
4. Ensure TaskReady and every Run creation path lock Task and check the active Barrier before inserting a Run.
5. Add deterministic two-connection concurrency tests for the inversion and scanner-vs-claim race.

This source audit does not yet prove the complete lock graph: Lease Renewal, command ACK/continue, task cancellation, all failure/requeue paths and the remaining outbox handlers still require review.
