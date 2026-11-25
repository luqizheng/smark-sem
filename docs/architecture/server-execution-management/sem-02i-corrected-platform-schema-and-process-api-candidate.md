# SEM-02I — Corrected Platform Schema and Process API Candidate

- Status: **Review Pending / Not migration-ready**.
- Supersedes the affected SQL-shaped fragments in SEM-02G; read with [SEM-02H](./sem-02h-ddl-integrity-and-transaction-review.md).
- Schema evidence baseline: GitHub `master@d0e72fa6805aebeadf1b282e430deba493072fd6`.
- No code or migration has been changed. This document is a candidate design, not an approved schema contract.

## 1. Design rules

1. Platform PostgreSQL remains authoritative for Task, Run, Lease, Generation, Interaction, HIR, Human Consultation, Notification, Task Execution Barrier and process identity acceptance.
2. SEM PostgreSQL remains authoritative only for Runner connection/ticket/dispatch/delivery/process-observation facts. Platform never reads SEM DB.
3. A Task Barrier is the serialization point for all Run creation/claim/requeue/recovery paths for that Task.
4. A process identity is immutable. Process observations are append-only events, not mutable columns on the process identity row.
5. E6 is a formal Human Consultation decision. It authorizes one pre-bound successor and never creates E1/E2/E3 evidence or releases the Barrier.
6. An in-app Inbox item is committed in Platform DB. RabbitMQ is optional downstream fan-out, never the authority or a safety-critical transport.

## 2. Candidate Platform schema

The fragments below specify relationships and constraints. Existing key names/types must be confirmed against the current migration baseline before producing a numbered migration.

### 2.1 Required candidate keys on existing tables

```sql
-- Task Run must be addressable by the exact Task relationship.
ALTER TABLE delivery.task_run
  ADD CONSTRAINT uq_task_run_project_task_id
  UNIQUE (project_id, task_id, id);

ALTER TABLE delivery.task_run
  ADD CONSTRAINT uq_task_run_tenant_task_id
  UNIQUE (tenant_id, task_id, id);

-- Interaction linkage must prove same Project + Task + Run.
ALTER TABLE delivery.task_interaction
  ADD CONSTRAINT uq_task_interaction_project_task_run_id
  UNIQUE (project_id, task_id, run_id, id);
```

Do not add duplicate candidate keys if an equivalent key already exists. Before migration authoring, compare the exact ordered key columns and NULLability against master.

### 2.2 HIR reuses the existing intervention table without conflating action history

Keep `governance.human_intervention` as the physical carrier, but add a discriminator:

- `record_kind='action'`: existing veto/rollback/freeze/unfreeze/mode_switch/policy_change/rollback_failed rows; preserve `intervention_type`, actor, target and audit semantics.
- `record_kind='hir'`: open execution-intervention work item; `intervention_type` is NULL and HIR lifecycle columns are populated.

Candidate new HIR columns:
- `task_id`, `run_id`, `barrier_id`, optional `interaction_id`;
- `hir_status`, `category`, `severity`;
- `assigned_to`, `assigned_at`;
- `resolved_by`, `resolved_at`, `closed_by`, `closed_at`;
- `evidence_refs JSONB NOT NULL DEFAULT '[]'`, `disposition`.

Required constraints:

```sql
ALTER TABLE governance.human_intervention
  ADD CONSTRAINT ck_human_intervention_record_shape CHECK (
    (record_kind = 'action' AND intervention_type IS NOT NULL
      AND task_id IS NULL AND run_id IS NULL AND barrier_id IS NULL)
    OR
    (record_kind = 'hir' AND intervention_type IS NULL
      AND task_id IS NOT NULL AND run_id IS NOT NULL AND barrier_id IS NOT NULL
      AND hir_status IS NOT NULL AND category IS NOT NULL AND severity IS NOT NULL
      AND jsonb_typeof(evidence_refs) = 'array')
  );

ALTER TABLE governance.human_intervention
  ADD CONSTRAINT fk_hir_run_same_task
  FOREIGN KEY (project_id, task_id, run_id)
  REFERENCES delivery.task_run(project_id, task_id, id);

ALTER TABLE governance.human_intervention
  ADD CONSTRAINT uq_hir_task_barrier_id
  UNIQUE (task_id, barrier_id, id);

CREATE UNIQUE INDEX uq_hir_one_per_barrier
  ON governance.human_intervention(barrier_id)
  WHERE record_kind = 'hir';
```

The action/HIR CHECK must be adapted to all pre-existing non-null columns and current CHECK constraints. The sample is a relationship contract, not a copy/paste migration.

If HIR references an Interaction, use the exact four-column FK:

```sql
FOREIGN KEY (project_id, task_id, run_id, interaction_id)
REFERENCES delivery.task_interaction(project_id, task_id, run_id, id);
```

HIR state CHECKs must require `assigned_to + assigned_at` for assigned, evidence array shape, and complete actor/time tuples for resolved/closed/cancelled. State transitions are validated by one application command under row lock and audited in the same transaction. Existing action rows remain immutable action history; HIR transitions must not rewrite them.

### 2.3 Task Execution Barrier

New Platform table: `delivery.task_execution_barrier`.

Core columns:
- `id, tenant_id, project_id, task_id`;
- `origin_run_id, origin_generation`;
- `state`: `active | risk_accepted_unconfirmed | released`;
- `origin_evidence_class`: E4/E5 (the uncertainty that created the Barrier);
- `hir_id`;
- `e6_consultation_id`, `authorized_successor_run_id` (both nullable except E6 accepted);
- `release_evidence_class`, `release_evidence_ref`, `released_by`, `released_at`;
- `created_by, created_at, updated_at`.

Required properties:
- `UNIQUE(tenant_id, project_id, task_id, id)` for exact composite references.
- `UNIQUE(task_id) WHERE state <> 'released'`: at most one unreleased Barrier per Task; risk-accepted remains unreleased.
- origin Run FK proves same Project and Task; `origin_generation` is checked against the Run generation in the creation transaction and remains immutable.
- Barrier ↔ HIR and Barrier ↔ E6 consultation references use deferred constraints because both sides carry the relation.
- E6 successor FK proves same tenant and Task.
- The dispatch predicate blocks every Run for the Task unless the Barrier is `risk_accepted_unconfirmed` and the candidate Run is exactly `authorized_successor_run_id`.
- E6 authorization does not release the Barrier. Only E1/E2/E3 release evidence can move it to `released`.

The release CHECK must avoid SQL UNKNOWN:

```sql
CHECK (
  (state = 'released'
   AND released_by IS NOT NULL
   AND released_at IS NOT NULL
   AND release_evidence_ref IS NOT NULL
   AND release_evidence_class IS NOT NULL
   AND release_evidence_class IN ('E1','E2','E3'))
  OR
  (state <> 'released'
   AND released_by IS NULL
   AND released_at IS NULL
   AND release_evidence_ref IS NULL
   AND release_evidence_class IS NULL)
);
```

When a previously E6-authorized Barrier later receives valid E1/E2/E3 evidence, retain `e6_consultation_id` and `authorized_successor_run_id` as historical authorization facts while setting release fields. Do not erase the E6 decision.

### 2.4 Human Consultation as E6 authority

Extend `governance.human_consultation`; do not create a parallel E6 decision table.

E6-specific columns:
- `decision_kind` (ordinary consultation vs `execution_risk_acceptance`);
- `barrier_id`, `hir_id`, `successor_run_id`;
- `residual_risk_summary`, `mitigation_plan`;
- `risk_confirmed_by`, `risk_confirmed_at`.

For E6, Task/Barrier/HIR are bound when the consultation is created. The successor is allocated and linked in the same transaction that changes the consultation to `decided` and Barrier to `risk_accepted_unconfirmed`.

Required constraints:
- at most one E6 consultation per Barrier;
- a successor Run may be authorized by at most one E6 consultation;
- E6 `decided` requires decision content, decided actor/time, residual risk, mitigation, explicit risk confirmation actor/time and successor;
- E6 row's Task, Barrier, HIR and successor must all identify the same Task/tenant/project;
- a decided E6 record is immutable; corrections require a superseding consultation/audit event, not editing the original decision;
- deleting/nullifying the Task/Barrier/HIR/Run anchors of a decided E6 record is prohibited.

The Barrier's `e6_consultation_id` FK is DEFERRABLE INITIALLY DEFERRED. A deferred constraint trigger validates that the E6 consultation is actually `decision_kind='execution_risk_acceptance'`, `status='decided'`, and its Task/HIR/Barrier/successor match the Barrier row. This closes the otherwise possible state where a Barrier claims risk acceptance without a formal decision.

**Policy question still open:** does “second confirmation” require a different human from `decided_by`, or merely a separate explicit confirmation action by the same authorized human? Do not silently impose or omit four-eyes policy.

### 2.5 Process identity registry and append-only evidence ledger

Use two distinct Platform records:

**A. `delivery.task_run_process` — immutable process identity**

- `id, tenant_id, run_id, lease_generation, process_sequence`;
- `device_id, runner_connection_epoch, boot_id`;
- `pid, process_start_identity, process_instance_id`;
- `harness_kind, launch_reason`;
- `registration_event_id, registered_at`;
- optional `originating_command_id`.

Constraints:
- unique `(run_id, lease_generation, process_sequence)`;
- unique `(device_id, boot_id, process_instance_id)` to prevent one OS process being bound to two Runs;
- unique `(tenant_id, registration_event_id)`;
- FK to the Run and device under tenant scope;
- identity columns are immutable after registration.

**B. `delivery.task_run_process_evidence` — append-only event/evidence ledger**

- `id, tenant_id, event_id, run_id, lease_generation, process_sequence`;
- reported device/epoch/boot/PID/process identity;
- `event_kind`: process exit, process reconciled, terminate result, or other explicitly enumerated observation;
- optional `evidence_class` E1/E2/E3 and optional `command_id`;
- `observed_at, received_at, evidence_digest, evidence_ref`;
- `acceptance`: accepted / diagnostic_only / quarantined;
- validation reason.

Constraints and behavior:
- `UNIQUE(tenant_id,event_id)`;
- add a nullable `process_identity_id` FK for quarantined/unknown observations; for accepted observations require it non-null and enforce the exact composite identity `(process_identity_id, run_id, lease_generation, process_sequence)` against a unique key on the process registry;
- same event ID + same digest returns the stored result; same event ID + different digest is an idempotency conflict;
- evidence is append-only; never overwrite a prior observation to upgrade E1/E2 to E3;
- natural exit has no command_id; command-triggered exit must correlate to the command;
- accepted evidence must match the exact registered process identity;
- mismatched or unknown identity is still durably recorded as quarantined/diagnostic evidence but cannot release a Barrier;
- late evidence for process sequence N may close only N; it cannot clear the active pointer for N+1;
- only accepted E1/E2/E3 evidence satisfying the Task Barrier's origin Run+Generation and process identity requirements may release the Barrier.

The active pointer on `delivery.task_run` remains `active_process_sequence` with a deferred FK to the process registry for the current `lease_generation`. On Generation advance, reset the pointer in the same transaction. SEM's seven tables do not replace this Platform-side identity fence.

### 2.6 Notification Inbox

Keep `integration.notification` as the project-level feed and preserve its existing `read_at` semantics.

V1 per-principal inbox table: `integration.notification_recipient`:
- `notification_id`, `tenant_id`, `project_id`;
- nullable `recipient_principal_id` only for explicit unassigned queue;
- `assignment_state` = assigned/unassigned;
- `read_at`, `created_at`, `assigned_by`, `assigned_at`.

CHECK:
- assigned ⇒ recipient principal and assigned actor/time are present;
- unassigned ⇒ recipient principal is NULL and the row is visible in the project-level unassigned queue.

Add a tenant-scoped notification event idempotency key to the parent notification so HIR/Interaction event retries cannot duplicate Inbox items. Create notification + recipient rows in the same Platform transaction as the HIR/Interaction event. Do not put delivery attempts/retry state on the Inbox row.

If external email/push delivery is later required, add a separate channel-attempt ledger. RabbitMQ may carry optional outbox fan-out messages, but the Platform DB/outbox remains authoritative; broker outage cannot lose Inbox items or affect execution safety.

## 3. Process API contract candidate

All endpoints are Platform service APIs called by SEM over authenticated HTTPS. The Platform validates service JWT scope, SEM identity, Run/Generation, current lease/device binding and idempotency. The exact JWT scopes must be added to the service-auth contract; do not reuse human principal identity.

Base path: `/internal/sem/v1`.

### 3.1 Register initial process

`POST /runs/{run_id}/processes/register`

Required body:
- `event_id`, `lease_generation`, `process_sequence`;
- `device_id`, `runner_connection_epoch`, `boot_id`;
- `pid`, `process_start_identity`, `process_instance_id`;
- `harness_kind`, `launch_reason=initial_start`.

Rules:
- sequence is the first unused sequence for the Run+Generation (normally 1);
- the Run must have a current valid Lease bound to this device/Runner;
- registration is idempotent by event ID and process identity;
- conflicting registration for an already-bound sequence or OS process identity is quarantined and cannot renew the Lease.

### 3.2 Record Interaction continuation consumed

`POST /runs/{run_id}/processes/continuation-consumed`

Required body:
- `event_id`, `lease_generation`, `command_id`;
- `interaction_id`, `continuation_id`;
- `previous_process_sequence`, `new_process_sequence`;
- complete new process identity tuple (device/epoch/boot/PID/start identity/process instance).

Rules:
- Platform locks the Run and validates current Lease/Generation, Interaction state and command identity;
- exactly one continuation command may reserve the next sequence for a continuation;
- `new_process_sequence = previous_process_sequence + 1`;
- the command must be the current authorized continue command;
- Platform inserts the new process identity and advances `active_process_sequence` atomically;
- retry with same event ID/body returns original result; same ID/different body is conflict;
- late terminate/exit for previous sequence only appends evidence for that sequence and cannot clear the new pointer.

### 3.3 Submit process observation / exit evidence

`POST /runs/{run_id}/process-evidence`

Required body:
- `event_id`, `lease_generation`, `process_sequence`;
- reported `device_id`, `runner_connection_epoch`, `boot_id`, `pid`, `process_start_identity`, `process_instance_id`;
- `event_kind`, `observed_at`, `evidence_digest`, `evidence_ref`;
- optional `evidence_class`, optional `command_id`, optional exit code.

Rules:
- process evidence may be appended after Lease expiry/revocation; this endpoint never changes Run/Lease/Task state by itself;
- SEM connection epoch and device identity are checked; an old epoch may submit evidence for a process it previously supervised, but cannot issue new control commands;
- identity mismatch is persisted as diagnostic/quarantined evidence and cannot be E3;
- E3 requires OS wait/handle exit or equivalent strong observation by Runner Supervisor;
- natural exit command_id is NULL; command-triggered exit includes command_id;
- Barrier release is a separate Platform transaction after evidence validation.

### 3.4 Renew Lease

`POST /runs/{run_id}/lease/renew`

Required body:
- `request_id`, `lease_generation`, `lease_proof`;
- `device_id`, `runner_connection_epoch`;
- `process_sequence`, `process_instance_id`, `boot_id`.

Rules:
- Platform validates current Lease token/proof, device binding, Generation and exact current active process identity;
- only current accepted process sequence can renew;
- superseded process sequence cannot renew;
- a Task Barrier blocks new Run dispatch, but a currently authorized process's renewal policy must be explicit (do not accidentally expire an active uncertain process merely because HIR exists);
- WSS heartbeat and Agent Activity are not Lease Renewal.

## 4. WSS event/ACK vocabulary

Canonical event names:
- `runner.process.registered`
- `continuation.consumed`
- `runner.process.exit`
- `runner.process.reconciled`
- `command.received`
- `command.result`

Semantics:
- received ACK = command durably accepted by Runner Supervisor;
- command result = command execution outcome;
- process exit evidence = OS-level observation, not a generic ACK;
- continuation consumed = new process identity registered and accepted by Platform;
- transport ACK, command result and process exit evidence are separate events and cannot substitute for one another.

## 5. API error and idempotency contract

All responses use a stable envelope:
- success: `request_id`, `event_id` (if applicable), `result`, `replayed`;
- error: `code`, `message`, `retryable`, `correlation_id`, optional `current_generation` / `current_process_sequence`.

Minimum HTTP behavior:
- 400 malformed/unsupported schema;
- 401 invalid/expired service token;
- 403 valid identity but missing scope/device authorization;
- 404 unknown Run or deliberately non-disclosing unauthorized resource;
- 409 stale Generation, sequence conflict, idempotency key reused with different digest, competing continuation;
- 422 semantically invalid transition;
- 429 bounded rate limit;
- 5xx retryable Platform/SEM transient failure.

A retry must reuse the same `event_id` or `request_id`; a new key represents a new logical event. The Platform stores idempotency result with the authoritative transaction, not in SEM memory.

## 6. Transaction lock graph — not yet approved

Candidate lock order for new design is:

`Project → Task → TaskExecutionBarrier → Run → Interaction/HIR/HumanConsultation → worker_command → process identity/evidence`.

However, existing claim/recovery/interaction transactions must be audited against this order before it can be frozen. SEM-02G's `Project → Run → Task → Barrier` order conflicts with this candidate if any transaction later locks Task after Run while another locks Run after Task.

Required audit matrix:
- claim (ordinary queued and expired claimed);
- lease renew;
- Interaction create / respond / continue;
- HIR create / assign / resolve / close;
- orphan scanner;
- E1/E2/E3 evidence acceptance and Barrier release;
- E6 consultation + successor reservation;
- B06-D3 / retry / requeue;
- Run creation by failure/outbox handlers.

For each transaction record the exact rows locked, lock mode, order, and conditional update. The Task row must serialize Barrier creation and Run dispatch. If existing code cannot follow one global order, refactor the transaction boundaries before schema migration. This section is deliberately OPEN pending source-level proof.

## 7. RabbitMQ deployment boundary

RabbitMQ remains the existing separate single-instance service (no cluster). SEM does not use it for Runner WSS, Claim, Lease, command ACK, process evidence, HIR state, Barrier or E6. Platform may publish non-authoritative notification fan-out events from its transactional outbox; consumers must be idempotent and broker outage must not affect the durable Inbox or execution state. No cluster/HA assumption is made.

## 8. Exit criteria before migration

SEM-02I is not ready for migration until:
1. every referenced composite FK has an exact UNIQUE/PK target in the final DDL;
2. SQL CHECK expressions have explicit NULL handling;
3. E6 circular references and successor reservation are transactionally proven;
4. HIR action-history readers/writers have been audited against the discriminator;
5. process event idempotency and append-only evidence are implemented in the Platform schema contract;
6. API scopes and request/response schemas are made machine-verifiable (OpenAPI or equivalent);
7. the lock graph is proven against every listed source transaction;
8. current master is merged/rebased into the review branch and the entire document set is re-audited.

No migration, API implementation, WSS implementation or Phase 0 work is authorized by this candidate.


### 6.1 Confirmed source-level lock inversion and scanner race

- `interaction.rs:129,197` report path locks Run then Interaction.
- `interaction.rs:783,816` retry path locks Interaction then Run.
- `interaction.rs:697-740` cancel path updates Interaction then Run then locks Task.
- `run_executor.rs:480-570` orphan reconciliation has no single transactional lock/Barrier path; it updates Run and then Task in separate logical steps.

These are blockers for the Task Barrier implementation. The code lock inversion must be reproduced and corrected, and the orphan scanner must atomically write Barrier + HIR + notification + audit before any requeue.
