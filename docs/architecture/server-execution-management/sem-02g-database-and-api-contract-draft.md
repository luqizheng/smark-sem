# SEM-02G — Database DDL and Service API Contract Draft

- Status: **Draft / Review Pending / Not an approved ADR**.
- Code/schema baseline used for the original draft: GitHub `master@4bc78620f54440a21a113cf7cdb14964d1a14dcb` (stale). Current review baseline: `master@d0e72fa6805aebeadf1b282e430deba493072fd6`; current schema blobs are recorded in [SEM-02H](./sem-02h-ddl-integrity-and-transaction-review.md).
- Parent specification: [SEM-02F](./sem-02f-executable-physical-and-protocol-contracts.md).
- Purpose: turn SEM-02F candidate entities into concrete PostgreSQL and Platform–SEM/Runner message contracts.
- This document contains SQL-shaped draft material for review only. It is not a migration file and must not be applied.
- **SEM-02H found concrete DDL defects and integrity gaps. Read SEM-02H before relying on any SQL below. The affected fragments are not approved or executable.**

## 1. Verified existing relational keys used by this draft

The current baseline provides the following relevant keys:

- `delivery.task`: PK `id`, unique `(project_id,id)`.
- `delivery.task_run`: PK `id`, unique `(project_id,id)` and `(tenant_id,id)`; FK `(project_id,task_id)` → `delivery.task(project_id,id)`.
- `core.project`: unique `(tenant_id,id)`.
- `core.project_member`: PK `(project_id,principal_id)`.
- `devenv.device`: unique `(tenant_id,id)`.
- `integration.notification`: PK `id`, unique `source_proposal_id`, FK `(tenant_id,project_id)` → `core.project(tenant_id,id)`.
- `governance.human_intervention`: PK `id`, FK `(tenant_id,project_id)` → Project, current `intervention_type NOT NULL` and action-only CHECK.
- `governance.human_consultation`: four-state CHECK, decided-completeness CHECK and Task FK `ON DELETE SET NULL`.

This draft uses these existing keys rather than inventing composite keys that are not present.

## 2. Candidate migration DDL — Task Execution Barrier

```sql
-- Additional candidate keys make cross-Task relationships enforceable by FKs.
ALTER TABLE delivery.task_run
    ADD CONSTRAINT uq_task_run_task_id UNIQUE (task_id, id),
    ADD CONSTRAINT uq_task_run_tenant_task_id UNIQUE (tenant_id, task_id, id),
    ADD CONSTRAINT uq_task_run_project_task_id UNIQUE (project_id, task_id, id);

CREATE TABLE delivery.task_execution_barrier (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    task_id uuid NOT NULL,
    origin_run_id uuid NOT NULL,
    origin_generation integer NOT NULL CHECK (origin_generation >= 0),
    state text NOT NULL CHECK (
        state IN ('active', 'risk_accepted_unconfirmed', 'released')
    ),
    evidence_class text CHECK (
        evidence_class IS NULL OR evidence_class IN ('E1', 'E2', 'E3', 'E4', 'E5')
    ),
    evidence_ref jsonb,
    authorized_successor_run_id uuid,
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    released_by uuid,
    released_at timestamptz,
    release_evidence_ref jsonb,

    CONSTRAINT fk_task_execution_barrier_project
        FOREIGN KEY (tenant_id, project_id)
        REFERENCES core.project(tenant_id, id),
    CONSTRAINT fk_task_execution_barrier_task
        FOREIGN KEY (project_id, task_id)
        REFERENCES delivery.task(project_id, id),
    CONSTRAINT uq_task_execution_barrier_task_id UNIQUE (task_id, id),
    CONSTRAINT fk_task_execution_barrier_origin_run
        FOREIGN KEY (project_id, task_id, origin_run_id)
        REFERENCES delivery.task_run(project_id, task_id, id),
    CONSTRAINT fk_task_execution_barrier_successor_run
        FOREIGN KEY (tenant_id, task_id, authorized_successor_run_id)
        REFERENCES delivery.task_run(tenant_id, task_id, id),
    CONSTRAINT fk_task_execution_barrier_created_by
        FOREIGN KEY (created_by) REFERENCES core.principal(id),
    CONSTRAINT fk_task_execution_barrier_released_by
        FOREIGN KEY (released_by) REFERENCES core.principal(id),
    CONSTRAINT ck_task_execution_barrier_release
        CHECK (
            (state = 'released' AND released_at IS NOT NULL
                AND release_evidence_ref IS NOT NULL
                AND evidence_class IN ('E1', 'E2', 'E3'))
            OR
            (state <> 'released' AND released_at IS NULL
                AND released_by IS NULL AND release_evidence_ref IS NULL)
        ),
    CONSTRAINT ck_task_execution_barrier_e6
        CHECK (
            state <> 'risk_accepted_unconfirmed'
            OR authorized_successor_run_id IS NOT NULL
        )
);

CREATE UNIQUE INDEX uq_task_execution_barrier_one_unreleased_per_task
    ON delivery.task_execution_barrier(task_id)
    WHERE state IN ('active', 'risk_accepted_unconfirmed');

CREATE UNIQUE INDEX uq_task_execution_barrier_successor
    ON delivery.task_execution_barrier(authorized_successor_run_id)
    WHERE authorized_successor_run_id IS NOT NULL;
```

Review notes:
- E6 is not an `evidence_class`; the CHECK deliberately excludes it.
- The release CHECK forces E1/E2/E3 evidence. A trigger/service guard must additionally verify that the evidence references all registered process identities for the origin Run+Generation.
- If a Task can be moved between Projects (current product policy should prohibit this), FK and unique-index scope must be revisited.
- Barrier rows are retained after release; no normal delete path.

## 3. Candidate HIR discriminator extension

```sql
ALTER TABLE governance.human_intervention
    ADD COLUMN record_kind text NOT NULL DEFAULT 'action',
    ADD COLUMN task_id uuid,
    ADD COLUMN run_id uuid,
    ADD COLUMN lease_generation integer,
    ADD COLUMN barrier_id uuid,
    ADD COLUMN interaction_id uuid,
    ADD COLUMN category text,
    ADD COLUMN severity text,
    ADD COLUMN status text,
    ADD COLUMN assigned_to uuid,
    ADD COLUMN assigned_at timestamptz,
    ADD COLUMN resolved_by uuid,
    ADD COLUMN resolved_at timestamptz,
    ADD COLUMN closed_by uuid,
    ADD COLUMN closed_at timestamptz,
    ADD COLUMN cancelled_by uuid,
    ADD COLUMN cancelled_at timestamptz,
    ADD COLUMN updated_by uuid,
    ADD COLUMN disposition text,
    ADD COLUMN evidence_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE governance.human_intervention
    ALTER COLUMN intervention_type DROP NOT NULL;

ALTER TABLE governance.human_intervention
    ADD CONSTRAINT ck_human_intervention_record_kind
    CHECK (record_kind IN ('action', 'hir'));

ALTER TABLE governance.human_intervention
    ADD CONSTRAINT ck_human_intervention_record_shape
    CHECK (
        (
            record_kind = 'action'
            AND intervention_type IS NOT NULL
            AND task_id IS NULL AND run_id IS NULL
            AND lease_generation IS NULL AND barrier_id IS NULL
            AND interaction_id IS NULL AND category IS NULL
            AND severity IS NULL AND status IS NULL
            AND assigned_to IS NULL AND assigned_at IS NULL
            AND resolved_by IS NULL AND resolved_at IS NULL
            AND closed_by IS NULL AND closed_at IS NULL
            AND cancelled_by IS NULL AND cancelled_at IS NULL
            AND updated_by IS NULL AND disposition IS NULL
            AND evidence_refs = '[]'::jsonb
        )
        OR
        (
            record_kind = 'hir'
            AND intervention_type IS NULL
            AND task_id IS NOT NULL AND run_id IS NOT NULL
            AND lease_generation IS NOT NULL AND barrier_id IS NOT NULL
            AND category IS NOT NULL AND severity IS NOT NULL
            AND status IS NOT NULL
            AND target_proposal_id IS NULL AND target_command_id IS NULL
            AND executed_at IS NULL
        )
    );

ALTER TABLE governance.human_intervention
    ADD CONSTRAINT ck_human_intervention_hir_status
    CHECK (
        status IS NULL OR status IN (
            'open', 'assigned', 'awaiting_user', 'in_progress',
            'resolved', 'closed', 'cancelled'
        )
    );

ALTER TABLE governance.human_intervention
    ADD CONSTRAINT fk_human_intervention_hir_task
    FOREIGN KEY (project_id, task_id)
    REFERENCES delivery.task(project_id, id);

ALTER TABLE governance.human_intervention
    ADD CONSTRAINT fk_human_intervention_hir_run
    FOREIGN KEY (project_id, run_id)
    REFERENCES delivery.task_run(project_id, id);

ALTER TABLE governance.human_intervention
    ADD CONSTRAINT fk_human_intervention_hir_barrier
    FOREIGN KEY (task_id, barrier_id)
    REFERENCES delivery.task_execution_barrier(task_id, id);

ALTER TABLE governance.human_intervention
    ADD CONSTRAINT fk_human_intervention_hir_interaction
    FOREIGN KEY (project_id, interaction_id)
    REFERENCES delivery.task_interaction(project_id, id);

ALTER TABLE governance.human_intervention
    ADD CONSTRAINT fk_human_intervention_hir_assignee
    FOREIGN KEY (assigned_to) REFERENCES core.principal(id);

ALTER TABLE governance.human_intervention
    ADD CONSTRAINT fk_human_intervention_hir_resolver
    FOREIGN KEY (resolved_by) REFERENCES core.principal(id);

ALTER TABLE governance.human_intervention
    ADD CONSTRAINT fk_human_intervention_hir_closer
    FOREIGN KEY (closed_by) REFERENCES core.principal(id);

ALTER TABLE governance.human_intervention
    ADD CONSTRAINT fk_human_intervention_hir_canceller
    FOREIGN KEY (cancelled_by) REFERENCES core.principal(id);

ALTER TABLE governance.human_intervention
    ADD CONSTRAINT fk_human_intervention_hir_updater
    FOREIGN KEY (updated_by) REFERENCES core.principal(id);

ALTER TABLE governance.human_intervention
    ADD CONSTRAINT fk_human_intervention_hir_assignee_member
    FOREIGN KEY (project_id, assigned_to)
    REFERENCES core.project_member(project_id, principal_id);

ALTER TABLE governance.human_intervention
    ADD CONSTRAINT ck_human_intervention_hir_lifecycle_timestamps
    CHECK (
        record_kind = 'action'
        OR (
            (assigned_to IS NULL AND assigned_at IS NULL)
            OR
            (assigned_to IS NOT NULL AND assigned_at IS NOT NULL)
        )
    );

ALTER TABLE governance.human_intervention
    ADD CONSTRAINT ck_human_intervention_hir_resolved
    CHECK (
        record_kind = 'action'
        OR status NOT IN ('resolved', 'closed')
        OR (resolved_by IS NOT NULL AND resolved_at IS NOT NULL)
    );

ALTER TABLE governance.human_intervention
    ADD CONSTRAINT ck_human_intervention_hir_closed
    CHECK (
        record_kind = 'action'
        OR status <> 'closed'
        OR (closed_by IS NOT NULL AND closed_at IS NOT NULL)
    );

ALTER TABLE governance.human_intervention
    ADD CONSTRAINT ck_human_intervention_hir_cancelled
    CHECK (
        record_kind = 'action'
        OR status <> 'cancelled'
        OR (cancelled_by IS NOT NULL AND cancelled_at IS NOT NULL)
    );

CREATE UNIQUE INDEX uq_human_intervention_one_hir_per_barrier
    ON governance.human_intervention(barrier_id)
    WHERE record_kind = 'hir';
```

HIR status transitions remain enforced by the application transition service and audit trail; a database trigger is recommended to reject illegal transitions and mutation of closed/cancelled records except explicit reopen. Existing action rows continue to insert without specifying `record_kind` because the default is `action`.

## 4. Candidate E6 columns and constraints

```sql
ALTER TABLE governance.human_consultation
    ADD COLUMN decision_kind text NOT NULL DEFAULT 'general',
    ADD COLUMN hir_id uuid,
    ADD COLUMN barrier_id uuid,
    ADD COLUMN successor_run_id uuid,
    ADD COLUMN residual_risk_summary text,
    ADD COLUMN mitigations jsonb,
    ADD COLUMN risk_confirmed_by uuid,
    ADD COLUMN risk_confirmed_at timestamptz;

ALTER TABLE governance.human_consultation
    ADD CONSTRAINT ck_human_consultation_decision_kind
    CHECK (decision_kind IN ('general', 'execution_risk_acceptance'));

ALTER TABLE governance.human_consultation
    ADD CONSTRAINT ck_human_consultation_e6_complete
    CHECK (
        decision_kind <> 'execution_risk_acceptance'
        OR (
            status = 'decided'
            AND task_id IS NOT NULL
            AND hir_id IS NOT NULL
            AND barrier_id IS NOT NULL
            AND successor_run_id IS NOT NULL
            AND decision_content IS NOT NULL
            AND decided_by IS NOT NULL
            AND decided_at IS NOT NULL
            AND residual_risk_summary IS NOT NULL
            AND mitigations IS NOT NULL
            AND risk_confirmed_by IS NOT NULL
            AND risk_confirmed_at IS NOT NULL
        )
    );

ALTER TABLE governance.human_consultation
    ADD CONSTRAINT fk_hc_e6_hir
    FOREIGN KEY (hir_id) REFERENCES governance.human_intervention(id)
    ON DELETE RESTRICT;

ALTER TABLE governance.human_consultation
    ADD CONSTRAINT fk_hc_e6_barrier
    FOREIGN KEY (task_id, barrier_id)
    REFERENCES delivery.task_execution_barrier(task_id, id)
    ON DELETE RESTRICT;

ALTER TABLE governance.human_consultation
    ADD CONSTRAINT fk_hc_e6_hir_same_barrier
    FOREIGN KEY (task_id, barrier_id, hir_id)
    REFERENCES governance.human_intervention(task_id, barrier_id, id)
    ON DELETE RESTRICT;

ALTER TABLE governance.human_consultation
    ADD CONSTRAINT fk_hc_e6_successor_same_task
    FOREIGN KEY (tenant_id, task_id, successor_run_id)
    REFERENCES delivery.task_run(tenant_id, task_id, id)
    ON DELETE RESTRICT;

ALTER TABLE governance.human_consultation
    ADD CONSTRAINT fk_hc_e6_risk_confirmer
    FOREIGN KEY (risk_confirmed_by) REFERENCES core.principal(id);

CREATE UNIQUE INDEX uq_hc_e6_one_per_barrier
    ON governance.human_consultation(barrier_id)
    WHERE decision_kind = 'execution_risk_acceptance';

CREATE UNIQUE INDEX uq_hc_e6_successor
    ON governance.human_consultation(successor_run_id)
    WHERE decision_kind = 'execution_risk_acceptance';
```

Additional service/trigger invariants:
- E6 row must match Task ↔ Barrier ↔ HIR ↔ successor Task/Project.
- The E6 decision and successor reservation must commit atomically.
- The successor Run must not be claimable before the E6 transaction commits.
- The Barrier's `authorized_successor_run_id` must equal the E6 `successor_run_id`.
- Existing ordinary Human Consultation behavior remains unchanged.
- Existing `fk_hc_task ON DELETE SET NULL` cannot nullify an E6 Task anchor because the E6 CHECK rejects NULL; test this explicitly.

## 5. Candidate Notification Recipient table

```sql
ALTER TABLE integration.notification
    ADD CONSTRAINT uq_notification_tenant_project_id
    UNIQUE (tenant_id, project_id, id);

CREATE TABLE integration.notification_recipient (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    notification_id uuid NOT NULL,
    recipient_principal_id uuid,
    assignment_state text NOT NULL CHECK (
        assignment_state IN ('assigned', 'unassigned')
    ),
    delivery_state text NOT NULL DEFAULT 'available' CHECK (
        delivery_state IN ('available', 'failed')
    ),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at timestamptz,
    last_error text,
    delivered_at timestamptz NOT NULL DEFAULT now(),
    read_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT fk_notification_recipient_parent
        FOREIGN KEY (tenant_id, project_id, notification_id)
        REFERENCES integration.notification(tenant_id, project_id, id)
        ON DELETE CASCADE,
    CONSTRAINT fk_notification_recipient_member
        FOREIGN KEY (project_id, recipient_principal_id)
        REFERENCES core.project_member(project_id, principal_id),
    CONSTRAINT ck_notification_recipient_assignment
        CHECK (
            (assignment_state = 'assigned' AND recipient_principal_id IS NOT NULL)
            OR
            (assignment_state = 'unassigned' AND recipient_principal_id IS NULL)
        )
);

CREATE UNIQUE INDEX uq_notification_recipient_principal
    ON integration.notification_recipient(notification_id, recipient_principal_id)
    WHERE recipient_principal_id IS NOT NULL;

CREATE UNIQUE INDEX uq_notification_recipient_unassigned
    ON integration.notification_recipient(notification_id)
    WHERE recipient_principal_id IS NULL;

CREATE INDEX idx_notification_recipient_inbox
    ON integration.notification_recipient(recipient_principal_id, created_at DESC)
    WHERE recipient_principal_id IS NOT NULL;

CREATE INDEX idx_notification_recipient_unassigned_queue
    ON integration.notification_recipient(project_id, created_at DESC)
    WHERE assignment_state = 'unassigned';
```

V1 in-app notification rows are immediately available on transaction commit. `attempt_count/next_attempt_at/last_error` are reserved for a separately approved external-channel adapter; they are not needed to make the in-app Inbox durable. Existing parent `read_at` remains untouched.

## 6. Candidate Process Identity registry and active pointer

```sql
ALTER TABLE delivery.task_run
    ADD COLUMN active_process_sequence integer
    CHECK (active_process_sequence IS NULL OR active_process_sequence >= 1);

CREATE TABLE delivery.task_run_process (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    run_id uuid NOT NULL,
    lease_generation integer NOT NULL CHECK (lease_generation >= 0),
    process_sequence integer NOT NULL CHECK (process_sequence >= 1),
    device_id uuid NOT NULL,
    boot_id text NOT NULL,
    process_instance_id uuid NOT NULL,
    os_pid bigint NOT NULL CHECK (os_pid > 0),
    os_process_start_identity text NOT NULL,
    harness_kind text NOT NULL,
    launch_reason text NOT NULL CHECK (
        launch_reason IN ('initial_start', 'interaction_continue', 'recovery_restart')
    ),
    registered_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    exit_observed_at timestamptz,
    exit_code integer,
    exit_evidence_kind text CHECK (
        exit_evidence_kind IS NULL OR exit_evidence_kind IN ('E1', 'E2', 'E3')
    ),
    exit_evidence_id text,
    exit_command_id uuid,

    CONSTRAINT uq_task_run_process_sequence
        UNIQUE (run_id, lease_generation, process_sequence),
    CONSTRAINT uq_task_run_process_instance
        UNIQUE (run_id, lease_generation, process_instance_id),
    CONSTRAINT fk_task_run_process_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES delivery.task_run(tenant_id, id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_task_run_process_device
        FOREIGN KEY (tenant_id, device_id)
        REFERENCES devenv.device(tenant_id, id),
    CONSTRAINT ck_task_run_process_exit_tuple
        CHECK (
            (exit_observed_at IS NULL AND exit_evidence_kind IS NULL
                AND exit_evidence_id IS NULL)
            OR
            (exit_observed_at IS NOT NULL AND exit_evidence_kind IS NOT NULL
                AND exit_evidence_id IS NOT NULL)
        )
);

ALTER TABLE delivery.task_run
    ADD CONSTRAINT fk_task_run_active_process_sequence
    FOREIGN KEY (id, lease_generation, active_process_sequence)
    REFERENCES delivery.task_run_process(run_id, lease_generation, process_sequence)
    DEFERRABLE INITIALLY DEFERRED;
```

Important notes:
- The active pointer FK is deferred because process registration inserts the process row and advances the Run pointer in one transaction.
- On a new Lease Generation, `active_process_sequence` must reset to NULL.
- On Interaction continue, reserve `new_process_sequence = active_process_sequence + 1`; after successful spawn, insert the process row and advance the pointer atomically.
- When the current process exits, clear the pointer only with `WHERE active_process_sequence = :exited_sequence`; late old-sequence evidence must not clear a newer pointer.
- Identity columns are immutable. Exit fields are write-once; exact duplicate evidence is idempotent; conflicting evidence is quarantined.
- If Postgres cannot validate the deferred FK under the chosen migration order, retain the pointer as an application-enforced invariant plus a periodic integrity query. Do not weaken process identity matching.

## 7. Command sequence reservation

Add typed columns to `delivery.worker_command`:

```sql
ALTER TABLE delivery.worker_command
    ADD COLUMN target_process_sequence integer,
    ADD COLUMN new_process_sequence integer;

ALTER TABLE delivery.worker_command
    ADD CONSTRAINT ck_worker_command_process_sequence
    CHECK (
        (
            command_type = 'agent.process.terminate'
            AND target_process_sequence IS NOT NULL
            AND new_process_sequence IS NULL
        )
        OR
        (
            command_type = 'agent.task.continue'
            AND target_process_sequence IS NOT NULL
            AND new_process_sequence IS NOT NULL
            AND new_process_sequence > target_process_sequence
        )
    ) NOT VALID;
```

The exact legacy command backfill is not needed for production history under the Greenfield policy, but all test fixtures and seed rows must be updated. The application must reserve `new_process_sequence` while holding the Run row lock and reject two competing continuation reservations.

## 8. Platform notification Inbox API draft

The existing project Feed endpoint remains unchanged. Add separate authenticated Platform endpoints for per-principal Inbox operations:

- `GET /api/v1/projects/{project_id}/inbox?cursor=...`: only recipient rows where `recipient_principal_id = authenticated_principal`; never infer recipient from client-supplied principal IDs.
- `GET /api/v1/projects/{project_id}/inbox/unassigned?cursor=...`: only project operators with explicit HIR assignment permission.
- `POST /api/v1/projects/{project_id}/inbox/{recipient_row_id}/read`: updates only that principal's recipient `read_at`.
- `POST /api/v1/projects/{project_id}/inbox/unassigned/{recipient_row_id}/assign`: assigns to an active project member, writes audit, and updates HIR assignment only when the parent notification is HIR-related.

The project Feed's existing parent `read_at` endpoint/semantics are not changed by these routes.

## 9. Platform–SEM HTTPS API draft

Base path: `/internal/sem/v1`. All endpoints require the short-lived service JWT from ADR-SEM-22; each operation also validates its domain-level device/Run/Generation binding. Idempotency keys are independent from JWT `jti`.

### 9.1 Register initial process

`POST /internal/sem/v1/runs/{run_id}/processes`

```json
{
  "schema_version": "sem.process.register.v1",
  "event_id": "uuid",
  "task_id": "uuid",
  "lease_generation": 12,
  "process_sequence": 1,
  "device_id": "uuid",
  "boot_id": "device-boot-uuid",
  "process_instance_id": "uuid",
  "os_pid": 4512,
  "os_process_start_identity": "platform-specific-start-token",
  "harness_kind": "codex",
  "launch_reason": "initial_start",
  "observed_at": "2026-11-25T00:00:00Z"
}
```

Platform verifies current Run/Generation/Lease and device binding, inserts the identity idempotently, and sets `active_process_sequence`. A conflicting identity for the same sequence returns `409 process_sequence_conflict`.

### 9.2 Continue consumed

`POST /internal/sem/v1/continuations/consumed`

```json
{
  "schema_version": "sem.continuation.consumed.v1",
  "event_id": "uuid",
  "command_id": "uuid",
  "interaction_id": "uuid",
  "continuation_id": "uuid",
  "run_id": "uuid",
  "task_id": "uuid",
  "lease_generation": 12,
  "expected_previous_process_sequence": 1,
  "new_process_sequence": 2,
  "device_id": "uuid",
  "boot_id": "device-boot-uuid",
  "process_instance_id": "uuid",
  "os_pid": 4630,
  "os_process_start_identity": "platform-specific-start-token",
  "harness_kind": "codex",
  "observed_at": "2026-11-25T00:00:12Z"
}
```

Platform validates the issued continue command, Interaction response persistence, exact reserved sequence and current Run/Generation. In one transaction it inserts sequence 2, advances the active pointer, records consumption and audits. Duplicate same `event_id` returns the original result. A stale sequence or conflicting process identity returns 409 and must not renew the Lease.

### 9.3 Process exit evidence

`POST /internal/sem/v1/runs/{run_id}/process-exits`

```json
{
  "schema_version": "sem.process.exit.v1",
  "event_id": "uuid",
  "lease_generation": 12,
  "process_sequence": 1,
  "device_id": "uuid",
  "boot_id": "device-boot-uuid",
  "process_instance_id": "uuid",
  "os_pid": 4512,
  "os_process_start_identity": "platform-specific-start-token",
  "exit_evidence_kind": "E3",
  "exit_code": 0,
  "command_id": null,
  "observed_at": "2026-11-25T00:00:13Z",
  "evidence_digest": "sha256:..."
}
```

Natural exit may omit `command_id`. If the evidence claims to satisfy a terminate command, `command_id` is mandatory and must target this exact process sequence. Lease expiry or Generation change does not prevent appending valid historical evidence for a registered process identity; it prevents that evidence from mutating a newer Run/Generation. Platform accepts exact duplicates idempotently and quarantines identity conflicts.

### 9.4 Process-bound Lease Renewal

`POST /internal/sem/v1/leases/renew`

```json
{
  "schema_version": "sem.lease.renew.v1",
  "request_id": "uuid",
  "run_id": "uuid",
  "lease_generation": 12,
  "device_id": "uuid",
  "process_sequence": 2,
  "process_instance_id": "uuid",
  "lease_proof": "opaque-short-lived-lease-proof",
  "requested_lease_seconds": 300
}
```

Platform verifies:
- current Run status, lease owner, token/proof, generation and unexpired deadline;
- device identity and current project binding;
- `process_sequence = task_run.active_process_sequence`;
- `process_instance_id` matches the active process registry row;
- Task Barrier/Interaction conditions do not prohibit renewal under the agreed policy.

SEM forwards `lease_proof` ephemerally and must not persist or log it. `request_id` is idempotent; retries use the same key. WSS heartbeat and Agent Activity are not renewals.

## 10. Runner–SEM WSS event draft

All messages carry `schema_version`, `event_id`, `connection_epoch`, `device_id`, `run_id`, `lease_generation` where applicable.

| Message | Direction | Meaning |
|---|---|---|
| `runner.process.started` | Runner → SEM | OS process was spawned; SEM persists observation then forwards registration |
| `runner.process.exit` | Runner → SEM | OS wait/handle observed exact process exit; natural exit has no command_id |
| `runner.process.reconciled` | Runner → SEM | Reconnect reconciliation for a previously registered process |
| `runner.reconnect_sync` | Runner → SEM | Boot ID, active process inventory, spool cursor and connection epoch |
| `continuation.consumed` | Runner → SEM → Platform | Reply injected and new process spawned; register reserved sequence |
| `command.received` | Runner → SEM | Durable receipt only; not process termination |
| `command.result` | Runner → SEM | Command operation success/failure; not E3 unless paired with process-exit evidence |
| `lease.renew` | Runner → SEM → Platform | Dedicated process-bound lease renewal |

SEM must persist each incoming process evidence event before acknowledging it. Runner retains its local spool until SEM returns durable evidence ACK. SEM then forwards to Platform with idempotency; Platform's acknowledgement does not mean the Run is terminal unless the relevant state transition commits.

## 11. Error contract

| HTTP / code | Meaning | Required behavior |
|---|---|---|
| 400 `invalid_process_identity` | Missing or malformed identity fields | Reject; no state mutation |
| 401/403 `service_or_device_not_authorized` | Service/device scope invalid | Fail closed; audit security event |
| 404 `run_not_found` | Run not visible in tenant/project | Do not leak cross-project existence |
| 409 `stale_generation` | Generation no longer current | Retain as diagnostic evidence only; no Run mutation |
| 409 `process_sequence_conflict` | Same sequence bound to different process identity | Quarantine; no Lease renewal |
| 409 `stale_process_sequence` | Renewal/continue from superseded sequence | Reject; do not revive old process |
| 409 `barrier_active` | New Run is not the exact E6-authorized successor | Do not dispatch |
| 409 `continuation_not_ready` | Reply/command/Interaction prerequisites missing | Keep shield; do not advance process sequence |
| 503 `platform_temporarily_unavailable` | Platform API unavailable | SEM retains durable delivery; retry idempotently |

## 12. Transaction and idempotency rules

- Lock order for operations touching execution safety: Project → existing Run → Task → Task Barrier → HIR/Consultation. Run creation without an existing Run locks Project → Task → Barrier. Do not introduce a later lock on an earlier entity.
- The Platform Task row is the serialization point for Barrier creation, E6, new Run creation and dispatchability.
- Process registration/sequence advance locks the Run row and verifies current generation before updating `active_process_sequence`.
- Exact duplicate event ID + identical body returns the original outcome; same event ID with different body is an idempotency conflict.
- JWT `jti` replay protection is separate from business `event_id/request_id`.
- SEM durable receipt ACK, Platform API acceptance and committed business state are distinct acknowledgements.
- No distributed transaction between Platform DB, SEM DB, Runner spool or RabbitMQ.

## 13. Open review items

1. Confirm the HIR discriminator DDL does not conflict with any unseen reader that assumes `intervention_type NOT NULL`.
2. Confirm the deferred composite FK for `task_run.active_process_sequence` is valid under the actual migration order and does not create an update deadlock.
3. Confirm the new `task_run` composite unique keys are acceptable and do not duplicate an existing key under another name.
4. Confirm `worker_command` process-sequence reservation semantics for terminate and continue, including the terminate-before-continue race.
5. Decide whether Platform process-exit evidence needs a separate append-only evidence table instead of write-once exit columns on `task_run_process`.
6. Finalize lease proof transport format and exact service API authentication middleware.
7. Confirm Task status projection when Barrier is created (Blocked vs keeping the last Task status) without using `task_waiting` as a substitute for HIR.
8. Complete full repository search for every notification reader/writer, every human_intervention writer/reader and every direct Run INSERT.
9. Re-run all schema/code checks against the latest master immediately before executable Migration authoring.
10. Close all P0/P1 findings in [SEM-02H](./sem-02h-ddl-integrity-and-transaction-review.md), including the missing HIR composite FK target, Task/Run mismatch, nullable release-evidence CHECK, E6-to-Barrier authorization link and append-only process evidence ledger.

No SQL in this document is executable as-is. No Migration/API/WSS implementation or Phase 0 work is authorized.
