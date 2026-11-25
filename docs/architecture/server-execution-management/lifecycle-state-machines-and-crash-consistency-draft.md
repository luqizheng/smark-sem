# D-05 — Lifecycle State Machines and Crash Consistency

- Status: **Detailed design draft / review pending**.
- Decision package: D-05 in the Bilateral Documentation Completion Register.
- Scope: AI-PM Run/attempt, SEM Execution/delivery/binding/release, Runner Supervisor process lifecycle, and their durable message journals.
- Authorities: AI-PM owns business Run/attempt and authorization; SEM owns infrastructure execution/delivery/binding/release ledger; Runner Supervisor owns the local Harness process and its positive OS lifecycle evidence.
- This document is a normative-design proposal, not an approved implementation contract. It authorizes no code, schema migration, Phase 0, deployment change, or PR merge.
- Related contracts: [Execution Identity, Lifecycle, Fencing and Delivery](../../protocol/EXECUTION-IDENTITY-LIFECYCLE-FENCING-DELIVERY-CONTRACT-DRAFT.md), [Platform–SEM Message Protocol](../../protocol/PLATFORM-SEM-EXECUTION-MESSAGE-PROTOCOL-DRAFT.md), [Runner–SEM WSS Protocol](../../protocol/RUNNER-SEM-WSS-PROTOCOL-DRAFT.md), [Runner Host Isolation and Permanent-Loss Recovery](../runner-host-isolation-and-permanent-loss-recovery-draft.md), and [AI-PM Harness Identity and Business Fencing Review](https://github.com/luqizheng/ai-pm/blob/docs/sem-02e-architecture-convergence/docs/architecture/server-execution-management/harness-identity-and-business-fencing-review.md).

## 1. Purpose and non-negotiable invariants

D-05 closes the failure window in which SEM has accepted and sent a delivery, but either SEM or Runner restarts before the outcome is durably known. The design must never turn an unknown outcome into permission to launch a second Harness process.

1. **Three authorities, three lifecycles.** AI-PM Run/attempt, SEM Execution and Runner process are distinct state machines. No service writes another authority's state.
2. **Business truth stays in AI-PM.** SEM never stores or derives Task status, Run outcome, retry eligibility, approval, acceptance or business completion.
3. **Local process truth stays with Runner Supervisor.** Only the Supervisor may launch, stop, identify and positively observe exit of its exact process/containment unit.
4. **Durable-before-effect.** A component must durably record an operation and its idempotency identity before acknowledging it or performing an irreversible external effect, except where the OS process-creation boundary itself requires a recoverable intent/observation protocol described below.
5. **Unknown is not failed.** Timeout, disconnect, missing ACK, SEM restart, Runner restart or missing event is an uncertain outcome requiring reconciliation.
6. **No blind duplicate start.** For one execution and binding, a duplicate delivery can return the original durable outcome; it cannot create a second process.
7. **Fencing is independent.** AI-PM `authorization_generation` fences business MCP authority. SEM `binding_epoch` fences infrastructure commands and observations. Neither substitutes for the other.
8. **No false process-exit inference.** WSS disconnect, heartbeat timeout, stop ACK, MCP revocation, process-list absence without trusted identity, or exit code reported by Harness is not positive process-exit evidence.
9. **No false business-success inference.** Process exit code 0, delivery receipt, process-start event, result submission, or SEM release is not Task completion.
10. **At-least-once transport, exactly-once effects by idempotency.** Network delivery may repeat. State-changing handlers must be idempotent and reject same-key/different-payload reuse.
11. **No cross-database transaction.** AI-PM, SEM and Runner local journal each commit locally. Outbox/Inbox, durable journals and reconciliation close gaps.
12. **Workspace is disposable.** Persist process registry, dedupe ledger and event journal; do not introduce workspace/worktree backup.

## 2. Identity tuple and ownership

| Field | Issuer / authority | Purpose |
|---|---|---|
| `task_id`, `run_id`, `attempt_id` | AI-PM | Business identity; never interpreted by SEM |
| `authorization_generation` | AI-PM | Reject stale delegated Harness MCP authority |
| `execution_id` | AI-PM creates; SEM records | Opaque cross-system correlation and infrastructure execution identity |
| `request_id`, `message_id` | Sending system | Stable request/outbox idempotency |
| `delivery_id`, `release_id` | SEM | Stable infrastructure command identity |
| `binding_epoch` | SEM | Monotonic fence for one Runner binding of an execution |
| `runner_id`, key version, `connection_id` | SEM enrollment/session | Authenticated infrastructure endpoint/session |
| `supervisor_instance_id`, `boot_id` | Runner | Supervisor incarnation and OS boot boundary |
| `process_identity` | Runner OS/Supervisor | Exact process identity (PID plus start identity and containment identity; PID alone is insufficient) |
| `event_id`, `event_sequence` | Runner or SEM event producer | Durable event deduplication and per-execution ordering |

SEM may retain `execution_id`, opaque payload bytes, routing metadata and its own identifiers. It must not add Task/Run business state columns or interpret business identifiers embedded in opaque payloads.

## 3. State machines

### 3.1 AI-PM Task, Run/attempt and authorization lifecycles (business authority)

This section is corrected against the AI-PM source baseline reviewed on 2026-11-25:

- Repository: `luqizheng/ai-pm`
- Branch: `master`
- Commit: `d0e72fa6805aebeadf1b282e430deba493072fd6`
- Source files: `crates/pm-domain/src/task.rs`, `crates/pm-domain/src/task_run.rs`, `crates/pm-application/src/run_transition_guard.rs`, `crates/pm-application/src/run_dispatch/port.rs`.

The current AI-PM model has three separate business concepts. They must not be collapsed into one proposed Run state machine.

**Task lifecycle — current source `TaskStatus` (13 states):**

`Draft`, `Ready`, `Claimed`, `Running`, `AwaitingDecision`, `Blocked`, `Submitted`, `Reviewing`, `Completed`, `ChangesRequested`, `Failed`, `Cancelled`, `Superseded`.

Task transition legality is enforced by the AI-PM domain transition validator and application guards. SEM observations never directly set Task status.

**Run lifecycle — current source `RunKind` and `RunStatus`:**

Run kind is `Delivery` or `Review`. Current Run status is one of:

`Queued`, `Claimed`, `Running`, `Succeeded`, `Failed`, `TimedOut`, `Cancelled`.

The currently guarded transition matrix is:

| Run kind | Current status | Allowed next statuses |
|---|---|---|
| Delivery | Queued | Claimed, Failed, Cancelled |
| Delivery | Claimed | Running, Queued, Succeeded, Failed, TimedOut, Cancelled |
| Delivery | Running | Queued, Succeeded, Failed, TimedOut, Cancelled |
| Review | Queued | Running, Cancelled |
| Review | Running | Succeeded, Failed, TimedOut, Cancelled |

Terminal Run statuses are immutable. Delivery lease reacquisition while `Claimed` is a separately validated same-state operation, not a status transition. The matrix above is the current AI-PM source contract, not a SEM-owned state machine.

**Run outcome — current source `RunOutcome`:**

`Succeeded`, `Failed`, `TimedOut`, `Cancelled`.

RunOutcome is outcome data and is not interchangeable with RunStatus or TaskStatus. A process exit observation is evidence supplied to AI-PM; the AI-PM application service applies its own outcome and Task transition rules.

**Attempt identity and executor lease — current source mapping:**

- One created Delivery Run is the durable execution attempt.
- `run_id` is its stable identity; `attempt_no` is the task-local ordinal.
- The current executor lease uses `lease_generation` and a lease token.
- `lease_generation` fences executor lease ownership. It is not delegated business authorization.

**Delegated authorization — proposed separate AI-PM-owned dimension:**

The future `authorization_generation` proposed by the SEM architecture is not a current RunStatus and is not a replacement for `lease_generation`. It must be represented as an independently owned AI-PM authorization/grant generation, correlated to the exact `run_id` (and therefore its `attempt_no`), execution identity, Runner key and allowed MCP operations. Its issue, expiry, revocation and per-call validation semantics belong to D-02/D-06.

| Concept | Current/proposed owner | Must not be confused with |
|---|---|---|
| TaskStatus | AI-PM current domain | RunStatus, process state |
| RunKind / RunStatus | AI-PM current application model | TaskStatus, RunOutcome |
| RunOutcome | AI-PM current domain | RunStatus, exit code alone |
| `run_id` / `attempt_no` | AI-PM current persistence model | SEM delivery ID |
| `lease_generation` | AI-PM current executor lease | delegated `authorization_generation` |
| `authorization_generation` | AI-PM proposed delegated grant | Runner key version, SEM binding_epoch |
| `binding_epoch` | SEM | AI-PM lease or authorization generation |

Rules:

- AI-PM persists a business Run/attempt decision and its corresponding SEM Outbox intent in the same AI-PM database transaction.
- A business retry creates a new Run/attempt identity and new execution identity. It is not a transport retry.
- Re-delivering the same Outbox message preserves `message_id`, `request_id`, `execution_id` and canonical payload.
- A Runner process exit is an infrastructure observation supplied through SEM. AI-PM correlates it to the Run and applies its own RunOutcome/RunStatus and TaskStatus policy.
- `exit_code = 0` cannot directly transition a Run to `Succeeded` or a Task to `Completed`.
- Harness may use only explicitly granted MCP operations, such as exact-scope context read, progress report and result submission. It cannot perform formal review/acceptance or arbitrary status setting.
- The current result-submission operation is an AI-PM application-service operation; valid delivery submission may advance Task `Running → Submitted`, but does not decide final acceptance.
- Task `Submitted → Reviewing` and `Reviewing → Completed` remain guarded by AI-PM; acceptance evidence and human-only gates remain authoritative.
- AI-PM may decide to release infrastructure while Task is submitted/reviewing or awaiting a human decision. Release is not synonymous with business completion.
- This mapping is verified only against the source commit listed above. Re-check the AI-PM source revision before D-05 ratification and update this table if its Run contract changes.

### 3.2 SEM Execution lifecycle (infrastructure authority)

SEM state describes its own infrastructure work only.

| State | Meaning | Entry condition / durable effect |
|---|---|---|
| `accepted` | Platform request durably accepted | Inbox + idempotency key + immutable payload digest committed |
| `queued` | Waiting for eligible Runner | Queue record committed; no reservation implied |
| `reserved` | Capacity reserved for a candidate Runner | Reservation, expiry policy and candidate committed atomically |
| `bound` | Runner binding selected | New `binding_epoch`, `delivery_id`, runner identity committed |
| `delivering` | Delivery send is in progress or outcome is not yet known | Send intent committed before WSS write |
| `delivery_received` | Runner durably journaled delivery and acknowledged receipt | Authenticated ACK matches delivery/execution/epoch |
| `starting` | Runner reports a durable start intent; process may or may not yet exist | Supervisor journal reports launch intent |
| `running` | Exact process start positively observed | Supervisor process identity + started event durably journaled |
| `release_requested` | AI-PM release instruction durably accepted | SEM Inbox and release intent committed |
| `stopping` | Runner accepted stop fence / termination command | Runner durable stop fence ACK; not yet process exit |
| `released` | Process exit/absence and cleanup requirements positively satisfied | Exact process exit evidence + cleanup completion recorded |
| `delivery_failed` | Delivery definitively rejected before Runner durable receipt | Explicit terminal protocol rejection; not timeout |
| `start_failed` | Supervisor proves no process was created for this start intent | Durable Supervisor evidence and reconciliation |
| `infrastructure_uncertain` | Outcome cannot be established safely | Ambiguous send, lost Runner, journal gap, or conflicting evidence |
| `cleanup_failed` | Process may be gone but required cleanup is incomplete/uncertain | Explicit cleanup error and retained resource/quarantine state |

Permitted high-level paths:

- `accepted → queued → reserved → bound → delivering → delivery_received → starting → running`
- Any nonterminal state may receive a release request; it transitions to `release_requested` and then `stopping` / `released` as evidence permits.
- Ambiguous outcomes transition to `infrastructure_uncertain`, not to a guessed failure or release.
- `delivery_failed` is allowed only with explicit evidence that the Runner did not durably accept the delivery.
- `start_failed` is allowed only when the Supervisor can prove no process was created and no late launch can occur.
- `released` is terminal for that binding. A later execution requires a new business authorization and identity; do not reopen a released binding.
- A stale event from an older `binding_epoch` is rejected/audited and cannot mutate current state.

SEM may report these infrastructure facts to AI-PM, but AI-PM decides what they mean for its Run/attempt and Task.

### 3.3 Runner Supervisor process lifecycle (local authority)

| State | Meaning | Durable requirement |
|---|---|---|
| `delivery_recorded` | Delivery and dedupe key stored locally | Journal transaction committed before receipt ACK |
| `start_intent` | Supervisor intends to create the process | Persist exact execution/delivery/epoch and launch nonce before OS create |
| `process_created_unconfirmed` | OS create returned a process handle/identity, but started event is not yet confirmed durable | Persist process identity immediately; recover by reconciling containment unit |
| `running` | Exact process is observed alive | Persist process identity and started event before sending event |
| `stop_fenced` | Durable fence prevents a delayed start for this binding | Persist release ID/epoch fence before stop ACK |
| `termination_requested` | Graceful/forced termination initiated | Persist action intent and policy/deadline |
| `exited` | Exact process exit positively observed (wait/reap or trusted containment evidence) | Persist exit status and evidence before event send |
| `cleanup_pending` | Process exited, but local cleanup/evidence delivery remains | Retain journal and retry cleanup/reporting |
| `cleaned` | Required local cleanup completed | Persist cleanup completion; keep dedupe tombstone for retention window |
| `local_uncertain` | Supervisor cannot prove process state after restart/host issue | Quarantine; no competing start or reservation release |

Rules:

- PID alone is never a process identity. Use PID + process start identity and an OS containment identity (Linux cgroup/container ID; Windows Job Object identity or equivalent).
- Journal must be durable across Supervisor process restart. Host reboot requires boot identity comparison and OS-specific containment reconciliation; absence of a PID after reboot is not sufficient unless the host/process containment evidence proves the old process cannot continue.
- Persist `start_intent` before process creation. After process creation, persist the returned exact process identity before emitting `harness.process_started`.
- If the Supervisor crashes between OS process creation and persisting the process identity, recovery must enumerate the dedicated containment unit using the durable launch nonce/labels and either adopt the exact process or quarantine. It must not launch again merely because the journal lacks a started event.
- Persist `stop_fenced` before acknowledging a release/stop command. A delayed delivery/start for a fenced epoch is rejected.
- Persist process exit evidence before sending `harness.process_exited`. If the event send fails, replay the same `event_id` and sequence after reconnect.
- Harness self-report is never the authoritative process-exit evidence.

**Mandatory launch/containment contract (OS adapter decision still open):**

1. Before any OS create call, persist a unique `launch_id`, immutable containment identity, execution/delivery/epoch tuple and start intent.
2. The OS create operation must place the process inside that pre-identified containment boundary as part of creation, or a durable single-writer launch broker must own and deduplicate the entire create/assign/resume operation. A plain “spawn, then attach to cgroup/job” sequence is not sufficient unless its intermediate crash window is independently recoverable.
3. A duplicate start for the same `launch_id` queries/adopts the original containment unit; it never calls OS create again merely because a PID/process record is missing.
4. The containment boundary must prevent the Harness and descendants from escaping, migrating out, or creating untracked descendants. The exact controls are OS/profile-specific and must be testable.
5. The process identity record is persisted before the process is allowed to execute user workload where the OS supports suspended creation. Where it does not, the durable launch broker/containment owner must provide equivalent discoverability and idempotency.
6. If the OS/profile cannot prove whether creation happened, the Supervisor enters `local_uncertain`, retains the reservation and blocks duplicate launch pending reconciliation/operator action.

**Required OS profile decisions before ratification:**

- Linux must select one supported mechanism and document its crash semantics, such as an OCI/container runtime object with a stable unique ID, a systemd transient unit, or a supported `clone3(CLONE_INTO_CGROUP)` path. It must also define cgroup delegation/escape prevention and how the unit is queried after Supervisor restart.
- Windows must define Job Object ownership and assignment at creation time, including the crash window before assignment/resume. A supported extended startup/job-list mechanism or a durable launch broker is required; a best-effort post-spawn assignment is not enough.
- V1 must name the supported OS/profile set. Unsupported profiles fail closed; they must not silently fall back to PID-only tracking.

**Positive exit proof after Supervisor restart:**

- The design must name the durable process owner (for example, the selected container runtime or host service manager) and the authoritative query used to establish that the exact containment unit is empty and cannot accept late descendants.
- PID absence or a failed process-list lookup is not proof. The containment owner must provide authoritative state for the stable containment identity.
- It is valid for process exit to be positively proven while the numeric exit code is unknown after Supervisor crash. In that case report `process_exited` with `exit_status=unknown` plus the evidence source; do not fabricate an exit code.
- “No longer executing on this host” is distinct from “external side effects rolled back”. The former may release process capacity after required cleanup; the latter is never inferred.
- If the selected host profile cannot provide this proof, retain quarantine and require operator intervention under D-03.

## 4. Transition transaction contract

Every transition below is local to the authority named in the first column. Cross-system side effects are emitted through a durable outbox/journal after the local commit.

| Authority / transition | Preconditions | Durable write before ACK/effect | Event / duplicate behavior |
|---|---|---|---|
| AI-PM create attempt → `created` | Business policy permits new attempt; no active conflicting attempt | Attempt, new execution identity, authorization generation and `execution.requested` Outbox in one transaction | Same outbox ID replays same payload; no second attempt |
| SEM accept → `accepted` | Authenticated Platform identity; supported protocol version; valid idempotency key | Inbox row, payload digest, execution ledger row | Same key + same digest returns original acceptance; same key + different digest returns conflict |
| SEM queue/reserve | Runner eligible by current WSS, app heartbeat, Supervisor health, same-boot telemetry, accepting flag and capacity | Reservation + expiry + candidate selection in one transaction | Unique reservation key prevents double reservation; retry returns existing result |
| SEM bind | Reservation valid; no active conflicting binding | Increment `binding_epoch`, bind runner, create delivery ID | One active binding; stale epoch rejected |
| SEM send delivery | Bound session generation is current; delivery not already terminal | `delivery_send_intent` and immutable envelope committed before WSS send | On retry send same delivery ID/payload; ambiguous outcome → reconcile, never create a new delivery identity |
| Runner receive delivery | Authenticated current session; exact runner/epoch; payload digest valid | Local delivery record + dedupe key + launch metadata committed | Commit then ACK; duplicate returns same receipt; different payload under same ID is rejected |
| Runner create process | Delivery recorded; no stop fence; no process for same delivery | `start_intent` committed before OS process creation | Duplicate start attaches/reconciles existing intent; never launches a second process |
| Runner process started | Exact process/containment identity available | Registry update + started event journal entry committed | Replay same event ID/sequence; duplicates are no-ops |
| Runner process exited | Exact process exit positively observed | Registry state + exit code/signal + evidence + event journal committed | Replay same event; contradictory exit evidence is quarantined |
| SEM ingest Runner event | Authenticated current runner; event ID unseen; binding epoch current | Inbox/dedupe + sequence cursor + execution observation in one transaction | Duplicate event ID returns prior ACK; gap is recorded and reconciled |
| SEM publish Platform event | Infrastructure event committed locally | SEM outbox event committed in same SEM transaction as state change | At-least-once delivery; same event ID on retry |
| AI-PM ingest SEM event | Authenticated SEM identity; schema supported; event ID unseen | AI-PM inbox + correlated Run observation in one transaction | Duplicate is no-op; event cannot directly set Task status |
| AI-PM revoke/release decision | Business policy says runtime no longer needed | Business state/authorization change + release Outbox in same transaction | Same release ID on retry; old authorization generation rejected |
| SEM accept release | Authenticated Platform event; execution and expected binding match | Release Inbox + release intent committed | Duplicate release ID returns original state; stale epoch is rejected or reconcile-only |
| Runner stop/release | Exact binding; release not already applied | Durable stop fence before ACK; termination intent before OS action | Duplicate stop is idempotent; late start for fenced epoch rejected |
| SEM mark released | Exact process exit/absence and cleanup evidence complete | Release outcome and reservation release committed | Duplicate exit/cleanup event does not release twice |

## 5. Crash-consistency and recovery protocol

### 5.1 General recovery algorithm

After restart, each authority must:

1. Load its durable inbox/outbox, execution/process ledger, dedupe keys, event cursors and active reservations.
2. Mark operations whose external outcome was not durably observed as **unknown**, not failed.
3. Reconcile using stable identities: request/message ID, execution ID, delivery ID, release ID, binding epoch, Runner ID, boot ID, process identity, event ID and sequence.
4. Query or replay the authoritative peer's durable journal over the authenticated channel.
5. Apply only idempotent state transitions; reject stale epochs and same-key/different-payload conflicts.
6. Retain reservations/quarantine when process existence or host isolation is uncertain.
7. Emit any pending outbox events with their original IDs and payloads.
8. Never create a replacement attempt or second process as a recovery shortcut.

### 5.2 SEM restart

On SEM startup:

- Restore its database state and pending Platform outbox.
- Re-establish Runner sessions; a new WSS session gets a new `connection_id/session_generation`. The old session is fenced.
- For every `delivering`, `starting`, `running`, `stopping` or `infrastructure_uncertain` execution, reconcile with the Runner's durable journal.
- If Runner confirms `delivery_recorded` for the same delivery, SEM records receipt even if the prior ACK was lost.
- If Runner confirms a process identity and current state, SEM adopts the observation; it does not send another start.
- If the Runner is offline or cannot prove process state, retain reservation and quarantine.
- If SEM committed send intent but cannot know whether the WSS frame reached Runner, resend the same delivery ID only after reconnect/reconciliation; Runner dedupe makes this safe.
- Never infer process exit from the absence of a WSS session.

### 5.3 Runner Supervisor restart / host reboot

On Supervisor startup:

- Load local durable journal before accepting work.
- Verify current OS boot identity. Reconcile every nonterminal process record against its exact containment unit.
- For a `start_intent` with no recorded process identity, inspect the dedicated containment unit/launch nonce. Adopt an existing matching process; if evidence is inconclusive, enter `local_uncertain` and reject a duplicate start.
- For a recorded process identity, verify PID plus start identity and containment membership; never trust PID reuse.
- Replay unacknowledged events using original `event_id` and `event_sequence`.
- Reconnect to SEM and report a snapshot plus journal cursor. SEM compares it with its own cursor and requests missing events or reconciliation.
- A different boot ID means the previous OS process cannot continue on that same boot, but host-level fencing/side effects and cleanup policy must still follow the selected D-03 host profile. Do not equate reboot with successful business completion.
- If journal corruption or missing evidence prevents proving process state, quarantine and require operator intervention; do not auto-relaunch.

### 5.4 Event ordering, replay and sequence gaps

- Each Runner event is immutable and has a unique `event_id`; sequence is monotonically increasing per execution/binding.
- Reconnect snapshot includes `runner_id`, boot ID, Supervisor instance, connection generation, per-execution binding epoch, latest sequence and active process identities.
- SEM acknowledges the highest contiguous sequence it has durably committed. It must not ACK beyond a gap.
- Duplicate event ID with identical canonical content is a no-op. Duplicate ID with changed content is a security/protocol conflict.
- An out-of-order event may be durably buffered, but cannot advance the contiguous cursor until gaps are resolved.
- Stale `binding_epoch` events are retained for audit/reconciliation but cannot mutate current binding state.
- If a process-exit event arrives before an earlier started event, SEM stores the evidence and reconciles sequence; it does not invent or discard the missing start event.

## 6. Critical race resolutions

### 6.1 Release during process start

Runner serializes start and release commands per execution/binding through one durable single-writer command sequencer. The sequencer owns a stable `launch_id`, the OS launch broker call and the release fence.

- **Start linearization point:** the OS/profile-specific launch broker atomically creates or adopts the process inside the pre-identified containment unit for this `launch_id`. The broker must make repeated calls for the same `launch_id` return the same containment/process outcome, never create a second process.
- If release is sequenced before the launch broker crosses that linearization point, the Supervisor durably fences the binding and the broker must reject the launch.
- If release is sequenced after the launch linearization point, the Supervisor resolves the exact containment identity and terminates that process tree.
- If release arrives while the broker operation is in flight and its outcome is not yet known, the Supervisor records the release request but **must not ACK the stop fence as fully effective** until the broker resolves the launch as not-created or created/adopted-and-stoppable. The execution remains uncertain and reserved during this interval.
- The Supervisor must not run an OS create call outside the sequencer/broker and then claim that a later journal fence prevented it.
- If the broker or containment owner is unavailable, enter `local_uncertain`; do not report start_failed, released or safe-to-rebind.
- A stop-fence ACK means later starts are fenced and every earlier/in-flight start has been accounted for. It is not process exit.
- SEM retains the reservation until positive exit evidence and the applicable cleanup requirements are satisfied.

### 6.2 Natural process exit before release

- Runner journals exact process exit and emits the event.
- A later release is accepted idempotently, applies the stop fence and performs remaining cleanup.
- SEM records both natural exit and release request; release converges to `released` only after cleanup policy is satisfied.
- AI-PM separately decides the Run/attempt outcome.

### 6.3 WSS disconnect during delivery

- SEM has a durable send intent and may or may not have transmitted bytes.
- SEM marks delivery outcome uncertain; it does not allocate a new delivery ID or a second binding.
- On reconnect, Runner reports its journal: if delivery exists, receipt is recovered; if absent and the Supervisor proves it never accepted the ID, SEM may resend the same ID.
- If Runner cannot be contacted, retain reservation/quarantine and do not reassign.

### 6.4 SEM restart after send, before ACK

- SEM restarts with `delivering` + send intent.
- It authenticates a new WSS session and asks Runner for delivery status.
- Runner either returns the durable receipt/process state or confirms no durable receipt.
- The same delivery ID is replayed only when safe; no new process can be created for a duplicate ID.

### 6.5 Runner crash after journal write, before ACK

- Runner's durable receipt survives.
- On reconnect, duplicate delivery returns the original receipt and does not create a second process.
- ACK may be regenerated; it does not imply process started.

### 6.6 OS process created before started event is fsynced

- Supervisor had persisted `start_intent` before OS create.
- Recovery inspects the unique containment unit/launch nonce and adopts the matching process if identity is provable.
- If process identity is ambiguous, quarantine; never create a second process.
- Once adopted, persist process identity and started event before reporting it.

### 6.7 Process exits before exit event is fsynced

- The exact child/containment exit must be observed by wait/reap or trusted OS evidence.
- If exit evidence was not persisted, recovery must re-observe the exact containment unit or use a durable OS/supervisor record capable of proving exit.
- If proof is unavailable, remain uncertain; do not infer exit from missing process listing.
- Persist exit event before sending; replay same event after restart.

### 6.8 Stale delivery or release after rebind

- Every command is bound to `execution_id + binding_epoch`.
- Runner and SEM reject stale epoch commands. A release for epoch N cannot stop epoch N+1.
- Rebind is forbidden until the previous process is positively exited or an independently verified isolation/fencing action satisfies D-03.
- New business attempt is a new execution ID and AI-PM authorization generation.

## 7. Cross-system consistency matrix

| Fact | First durable authority | Propagation | What it does NOT prove |
|---|---|---|---|
| Business attempt created | AI-PM DB | Platform Outbox → SEM Inbox | SEM accepted or Runner started |
| SEM request accepted | SEM DB | Internal HTTP response / reconciliation | Runner selected or delivery received |
| Capacity reserved | SEM DB | Internal ledger | Process exists |
| Binding established | SEM DB | SEM event to AI-PM; WSS command to Runner | Business grant active |
| Delegated grant active | AI-PM DB | Opaque one-time bootstrap via SEM | Process is running |
| Delivery durably received | Runner journal | WSS receipt → SEM DB | Harness process started |
| Process start observed | Runner journal / OS | WSS event → SEM → Platform Outbox → AI-PM Inbox | Business success |
| MCP progress/result submitted | AI-PM DB | AI-PM business workflow | Process exited or Task completed |
| Process exit observed | Runner journal / OS | WSS event → SEM → Platform Outbox → AI-PM Inbox | Run succeeded or Task completed |
| Release requested | AI-PM DB + Outbox | Internal HTTP → SEM Inbox → WSS | Process stopped |
| Stop fence accepted | Runner journal | WSS ACK → SEM | Process exited |
| Infrastructure released | SEM DB, based on positive evidence | SEM event → AI-PM | Task completed |
| Task completed | AI-PM DB, guarded acceptance | Business read model | All infrastructure cleanup necessarily finished |

## 8. Reconciliation API responsibilities (logical contract)

Exact internal HTTP paths and WSS schema are D-04, not defined here. Platform↔SEM uses HTTP or HTTPS on the company private network in V1; it has no public ingress. HTTPS is optional and supports enterprise CA or explicitly trusted self-signed certificates, with mandatory certificate/hostname validation and no verification bypass. HTTP is allowed only on a restricted internal network and does not provide confidentiality; authentication, request integrity, timestamp/nonce replay protection, idempotency and audit remain mandatory. Sensitive payload protection, trust-material distribution and certificate lifecycle must be covered by D-09. The following logical operations are required:

**Platform ↔ SEM**
- `execution.requested`: idempotent create/accept using stable request and execution IDs.
- `execution.release_requested`: idempotent release intent with expected binding epoch or explicit reconcile-before-release semantics.
- `execution.get/reconcile`: return SEM infrastructure snapshot by execution ID/request ID; no business state.
- `execution.infrastructure_observed`: SEM event with event ID, execution ID, binding epoch, observation type and evidence reference.
- Platform inbox/outbox status: durable cursor and replay support.

**SEM ↔ Runner**
- `runner.session.resume`: authenticate new session and report boot ID, Supervisor instance and journal cursors.
- `execution.delivery`: stable delivery ID, execution ID, binding epoch and opaque payload.
- `execution.delivery_received`: durable receipt only.
- `execution.reconcile`: Runner returns local delivery/process/release records for exact IDs.
- `harness.process_started` / `harness.process_exited`: positive process observations with exact process identity and event sequence.
- `execution.stop`: stable release ID and epoch; ACK means durable stop fence accepted, not exited.
- `runner.events.ack`: highest contiguous sequence durably committed by SEM.

All messages must be authenticated, versioned, bounded, schema validated, deduplicated and audited. Machine-readable OpenAPI/JSON Schema and canonical serialization remain D-04 deliverables.

## 9. Security and observability requirements

- Never log prompt body, bootstrap ticket, MCP bearer token, private key or credential material.
- Audit state transitions with authority, stable identity tuple, prior/new state, reason code, event ID, binding epoch, authorization generation where applicable, and timestamp.
- Do not place Task/Run business semantics in SEM metric labels or log payload interpretation.
- Resource reservation remains held while process state is uncertain. Capacity telemetry does not override quarantine.
- Runner event authenticity is tied to the authenticated enrolled key/session and key version; key rotation/revocation must not make old events silently current.
- Local journal must be access-controlled and tamper-evident to the extent supported by the host profile. Host compromise is handled by D-03 trust and isolation policy, not by assuming the journal is infallible.
- Clock timestamps are diagnostic; ordering and fencing use stable IDs, epochs and sequence numbers, not wall-clock ordering alone.

## 10. Acceptance matrix (minimum 40 cases)

| ID | Scenario | Required result |
|---|---|---|
| D05-01 | Platform retries identical execution request | One SEM execution; original acceptance returned |
| D05-02 | Same idempotency key, changed payload | Conflict; no mutation |
| D05-03 | SEM crashes after Inbox commit before internal HTTP response | Retry returns original accepted result |
| D05-04 | SEM crashes after reservation commit | Reservation restored; no double allocation |
| D05-05 | SEM crashes after binding commit before WSS send | Same binding/delivery identity resumed |
| D05-06 | SEM sends WSS frame then crashes before recording receipt | Reconcile; no new delivery identity |
| D05-07 | Runner receives delivery, crashes before journal commit | No receipt ACK; after restart safe resend same ID |
| D05-08 | Runner commits delivery journal then crashes before ACK | Duplicate returns durable receipt; no duplicate process |
| D05-09 | Runner receives duplicate delivery concurrently | One local delivery record and at most one process intent |
| D05-10 | Duplicate delivery ID carries different payload | Reject and audit protocol conflict |
| D05-11 | Runner start command arrives after durable stop fence | Reject; no process creation |
| D05-12 | Supervisor crashes after start intent before OS create | Recover intent; create at most one process |
| D05-13 | OS process created before process identity journal commit | Discover/adopt exact containment process or quarantine; never relaunch blindly |
| D05-14 | Process started event journaled before WSS send | Replay same event ID/sequence |
| D05-15 | Process exits before exit event journal commit | Re-observe exact process/containment; otherwise uncertain |
| D05-16 | Exit event journaled before WSS send | Replay same event; SEM dedupes |
| D05-17 | WSS disconnect while Harness remains alive | Mark uncertain; retain reservation; no reassignment |
| D05-18 | Heartbeat timeout with no exit evidence | Never mark process exited/released |
| D05-19 | Runner restarts with same boot ID and live process | Reattach exact process identity; no duplicate start |
| D05-20 | Runner host reboot changes boot ID | Apply D-03 host profile; no false business success |
| D05-21 | Runner journal missing/corrupt | Quarantine and operator escalation |
| D05-22 | SEM restarts while process is running | Reconcile from Runner journal; retain same binding |
| D05-23 | Runner reconnects with new connection generation | Old session messages fenced |
| D05-24 | Runner event sequence has a gap | Do not advance contiguous cursor; request replay/reconcile |
| D05-25 | Out-of-order process-exited before process-started | Store and reconcile; no fabricated sequence |
| D05-26 | Duplicate event ID, identical body | Idempotent no-op |
| D05-27 | Duplicate event ID, changed body | Reject/audit conflict |
| D05-28 | Event from stale binding epoch | Reject state mutation |
| D05-29 | Release arrives during process start before OS create | Durable stop fence prevents late launch |
| D05-30 | Release races after OS create | Adopt exact process then terminate; retain reservation until exit |
| D05-31 | Natural process exit precedes release | Preserve exit; release cleanup is idempotent |
| D05-32 | Duplicate release ID | One stop effect; original outcome returned |
| D05-33 | Release for epoch N arrives after epoch N+1 bind | Reject; must not stop new process |
| D05-34 | Stop ACK received but process remains alive | Remain stopping; no release |
| D05-35 | Process exit code is zero | Infrastructure observation only; no Task completion |
| D05-36 | Harness submits valid result | AI-PM validates/submits; no automatic acceptance |
| D05-37 | Harness attempts formal review or Task completed mutation | AI-PM rejects; human-only guard remains |
| D05-38 | AI-PM commits cancellation/revocation and release Outbox | Both are atomic in one AI-PM transaction |
| D05-39 | AI-PM crashes after business commit before SEM delivery | Outbox replays same release ID |
| D05-40 | SEM release event delivered twice to AI-PM | Inbox dedupes; no duplicate business transition |
| D05-41 | SEM reports released while Task awaits review | Task state unchanged by infrastructure event |
| D05-42 | AI-PM retries business work after old process uncertain | Old attempt remains fenced/quarantined; no overlapping Harness |
| D05-43 | Capacity reservation expires while process uncertain | Expiry cannot free capacity without reconciliation evidence |
| D05-44 | Old authorization generation calls MCP after retry | AI-PM rejects every stale business operation |
| D05-45 | WSS ping/pong succeeds but app heartbeat is stale | Runner is not dispatch-ready |
| D05-46 | Resource telemetry is from a different boot ID | Telemetry rejected as stale; no admission based on it |

## 11. Open decisions required before ratification

1. Exact AI-PM Run/attempt state names and their mapping to current source model.
2. Whether SEM persists a single execution aggregate with transition history or separate delivery/binding/release tables; uniqueness constraints and retention.
3. Runner journal storage engine, fsync policy, corruption recovery and disk-full behavior.
4. OS-specific process containment and durable discovery mechanism for the process-create-before-journal window (Linux cgroup/container; Windows Job Object or equivalent).
5. How the Supervisor can prove exit after its own crash or host reboot, including limits of OS wait/reap evidence.
6. Event sequence scope: per execution or per execution + binding epoch; this draft recommends per execution with epoch carried on each event, but requires protocol agreement.
7. Snapshot/replay API exact schemas, cursor semantics and maximum journal retention.
8. Reservation expiry/recovery rules and whether quarantined capacity can ever be manually released under each D-03 host profile.
9. Whether a process exit event must carry signed evidence in addition to authenticated WSS provenance.
10. Exact reconciliation deadlines are operational SLOs, not correctness shortcuts; timeout must never resolve uncertainty by assumption.

## 12. Readiness conclusion

D-05 now has a detailed lifecycle, transaction, crash-recovery and acceptance proposal. It is **not ratified** until the open decisions above are resolved, the AI-PM Run/attempt vocabulary is checked against the exact source revision, and D-04 schemas encode the required identities and replay behavior.

**D-05 status: DRAFT / REVIEW — NOT READY FOR DEVELOPMENT.**

No runtime implementation, migration, deployment change, Phase 0 or merge is authorized by this document.
