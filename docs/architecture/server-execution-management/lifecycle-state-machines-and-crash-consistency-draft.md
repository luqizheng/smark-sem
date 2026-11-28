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
| `task_id`, `run_id`, `attempt_no` | AI-PM | Business identity; run_id identifies the Run/attempt and attempt_no is its task-local ordinal; never interpreted by SEM |
| `authorization_generation` | AI-PM | Reject stale delegated Harness MCP authority |
| `execution_id` | AI-PM creates; SEM records | Opaque cross-system correlation and infrastructure execution identity |
| `request_id`, `message_id` | Sending system | Stable request/outbox idempotency |
| `delivery_id`, `release_id` | SEM | Stable infrastructure command identity |
| `binding_epoch` | SEM | Monotonic fence for one Runner binding of an execution |
| `runner_id`, key version, `connection_id` | SEM enrollment/session | Authenticated infrastructure endpoint/session |
| `supervisor_instance_id`, `boot_id`, `journal_id` | Runner | Supervisor incarnation, OS boot boundary and durable event-stream identity |
| `launch_id`, `containment_id` | Runner launch broker / OS profile | Stable idempotent launch operation and pre-created process containment boundary |
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

The current AI-PM domain source defines the following exact 31 TaskStatus edges. This is the edge allow-list only; guards in the right-hand column remain mandatory and are evaluated by AI-PM.

| From | To | Additional AI-PM guard |
|---|---|---|
| Draft | Ready | Normal readiness validation |
| Draft | Cancelled | Authorized cancellation |
| Draft | Superseded | Replacement task exists; non-empty reason and actor; no self-supersession |
| Ready | Claimed | Valid claim/dispatch policy |
| Ready | Cancelled | Authorized cancellation |
| Ready | Superseded | Replacement task exists; non-empty reason and actor; no self-supersession |
| Ready | Completed | Manual-task path only; human principal, manual_completion flag and reason |
| Claimed | Running | Valid claim/lease and execution start policy |
| Claimed | Ready | Claim release/requeue policy |
| Claimed | Cancelled | Authorized cancellation |
| Running | Submitted | Delivery manifest submitted and readable (E1) |
| Running | AwaitingDecision | At least one open question; waiting context recorded |
| Running | Blocked | Blocking reason/evidence recorded |
| Running | Cancelled | Authorized cancellation/release policy |
| Running | Failed | Terminal failure evidence: retry exhausted, total deadline exhausted, or terminating Permission/PolicyViolation/MissingDependency failure |
| Running | Superseded | Replacement exists; reason/actor valid; active Run positively stopped before finalization |
| AwaitingDecision | Ready | All waiting questions resolved |
| AwaitingDecision | Running | All waiting questions resolved |
| AwaitingDecision | Cancelled | Authorized cancellation; waiting resolution is not required |
| Blocked | Ready | Blocking condition resolved |
| Blocked | Cancelled | Authorized cancellation |
| Blocked | Superseded | Replacement exists; reason and actor valid |
| Submitted | Reviewing | Review may begin under AI-PM review policy |
| Submitted | Cancelled | Authorized cancellation |
| Submitted | Superseded | Replacement exists; reason and actor valid |
| Reviewing | Completed | Acceptance evidence complete (E2) and review policy satisfied |
| Reviewing | ChangesRequested | Review records actionable changes |
| Reviewing | Cancelled | Authorized cancellation |
| Reviewing | Superseded | Replacement exists; reason and actor valid |
| ChangesRequested | Ready | Rework scope accepted and task re-readied |
| ChangesRequested | Cancelled | Authorized cancellation |

The four terminal Task statuses are Completed, Cancelled, Failed and Superseded; none has an outgoing edge. Claimed, AwaitingDecision and ChangesRequested deliberately do not transition to Superseded. Entering Superseded always requires a distinct existing replacement task, a non-empty reason and actor; Running → Superseded additionally requires the active Run to be stopped first.

The edge matrix and guards are sourced from AI-PM commit d0e72fa6805aebeadf1b282e430deba493072fd6, especially pm-domain/src/task_transition.rs. Re-check this pinned source before ratification.

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
| `released_unbound` | P0-07: an `expected_binding=unbound` release won the per-execution dispatch/release sequencer before any Runner binding existed; dispatch is permanently fenced for this execution_id | Immutable dispatch-fence/tombstone record (`dispatch_fence_id`) committed with the release intent; emits exactly one `execution.unbound_release_applied`; carries no Runner, binding_epoch, stop_fence_id or process-exit evidence |
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

- PID alone is never a process identity. Use PID + process start identity together with the V1 Linux systemd transient-unit invocation identity and exact cgroup v2 containment path. PID alone is never an identity.
- Journal must be durable across Supervisor process restart. Host reboot requires boot identity comparison and OS-specific containment reconciliation; absence of a PID after reboot is not sufficient unless the host/process containment evidence proves the old process cannot continue.
- Persist `start_intent` before process creation. After process creation, persist the returned exact process identity before emitting `harness.process_started`.
- If the Supervisor crashes between OS process creation and persisting the process identity, recovery must enumerate the dedicated containment unit using the durable launch nonce/labels and either adopt the exact process or quarantine. It must not launch again merely because the journal lacks a started event.
- Persist `stop_fenced` before acknowledging a release/stop command. A delayed delivery/start for a fenced epoch is rejected.
- Persist process exit evidence before sending `harness.process_exited`. If the event send fails, replay the same `event_id` and sequence after reconnect.
- Harness self-report is never the authoritative process-exit evidence.

**Mandatory V1 Linux launch/containment contract (selected architecture; integration proof still open):**

1. Before any OS create call, persist a unique `launch_id`, immutable containment identity, execution/delivery/epoch tuple and start intent.
2. The OS create operation must place the process inside that pre-identified containment boundary as part of creation, or a durable single-writer launch broker must own and deduplicate the entire create/assign/resume operation. A plain “spawn, then attach to cgroup/job” sequence is not sufficient unless its intermediate crash window is independently recoverable.
3. A duplicate start for the same `launch_id` queries/adopts the original containment unit; it never calls OS create again merely because a PID/process record is missing.
4. The V1 systemd-owned cgroup v2 containment boundary must prevent the Harness and descendants from escaping, migrating out, or creating untracked descendants. The exact systemd unit properties, cgroup permissions and hostile-descendant tests are Linux systemd integration acceptance requirements.
5. The selected systemd launch broker must provide durable discoverability and idempotency across the StartTransientUnit request/job/process-create crash windows; no unsupported spawn-then-attach fallback is allowed.
6. If the OS/profile cannot prove whether creation happened, the Supervisor enters `local_uncertain`, retains the reservation and blocks duplicate launch pending reconciliation/operator action.

**V1 OS profile decision (user approved 2026-11-25):**

- V1 supports Linux only: systemd 250 or later as PID 1, unified cgroup v2, host systemd manager, and a systemd transient service/cgroup per execution binding.
- Windows, cgroup v1, non-systemd Linux and Runner containers without a trusted host-side systemd broker are out of scope and MUST NOT become dispatch-ready.
- The exact StartTransientUnit/GetUnit/GetJob request/response sequence, unit property serialization, job cancellation/fencing and cgroup escape-prevention behavior remain integration-proof requirements, not open OS-profile choices.

**Positive exit proof after Supervisor restart:**

- The design must name the durable process owner (for example, the selected container runtime or host service manager) and the authoritative query used to establish that the exact containment unit is empty and cannot accept late descendants.
- PID absence or a failed process-list lookup is not proof. The containment owner must provide authoritative state for the stable containment identity.
- It is valid for process exit to be positively proven while the numeric exit code is unknown after Supervisor crash. In that case report `process_exited` with `exit_status=unknown` plus the evidence source; do not fabricate an exit code.
- “No longer executing on this host” is distinct from “external side effects rolled back”. The former may release process capacity after required cleanup; the latter is never inferred.
- If the selected host profile cannot provide this proof, retain quarantine and require operator intervention under D-03.

### 3.4 Normative transition tables and recovery edges

The tables in this section define the allowed state edges. They are normative design requirements for review, not evidence that the selected OS adapters or runtime code already implement them. An event not listed as an allowed edge is rejected as a state mutation and retained for audit/reconciliation. A duplicate means the same stable command/event identity and identical canonical payload; same identity with changed payload is a conflict.

#### 3.4.1 SEM Execution transitions

| From | To | Initiator / evidence | Preconditions and durable commit | Duplicate, stale or recovery behavior |
|---|---|---|---|---|
| (new) | accepted | Platform request | Authenticated Platform; supported schema; idempotency key and payload digest committed with Inbox and Execution | Same key/digest returns original; same key/different digest conflicts |
| accepted | queued | SEM scheduler | Queue intent committed; no capacity reservation implied | Idempotent scheduler replay |
| queued | reserved | SEM admission controller | Fresh authenticated session, fresh app heartbeat, healthy Supervisor, same-boot telemetry, accepting=true, no drain/quarantine, capacity and fairness checks; reservation committed atomically | Existing reservation reused; expired reservation is not silently reused |
| reserved | queued | SEM admission controller | Reservation safely released and no delivery/binding side effect occurred | Re-evaluate admission; preserve execution identity |
| reserved | bound | SEM dispatcher | Reservation valid; unique active binding constraint; new binding epoch and delivery ID committed | Same binding request returns original epoch/ID |
| bound | delivering | SEM WSS sender | Current connection/session generation; durable send intent and immutable envelope committed before write | Resend only same delivery ID after reconciliation |
| delivering | delivery_received | Runner durable receipt ACK | Authenticated current session; exact runner, delivery, execution, epoch and payload digest; Runner journal commit proven | Duplicate receipt no-op; old session/epoch rejected |
| delivering | delivery_failed | Runner explicit terminal rejection | Protocol-level rejection proves no durable receipt and no launch intent exists | Timeout/disconnect is not sufficient; terminal for this delivery |
| delivery_received | starting | Runner start-intent event | Authenticated event from current binding; event stream cursor valid; Runner durable start intent/launch ID reported | Duplicate event no-op; event gap buffered |
| starting | running | Runner process-started event | Exact process identity and containment identity; launch broker evidence; event durably committed | Duplicate event no-op; stale epoch rejected |
| delivery_received | start_failed | Runner no-create proof | Launch broker proves no process was created for launch ID and no in-flight create exists | Missing PID/journal record is insufficient |
| starting | start_failed | Runner no-create proof | Same as above, including resolved in-flight broker operation and durable stop fence if release raced | If ambiguous, remain uncertain |
| Any nonterminal state except released | release_requested | AI-PM release command | Authenticated Platform request; expected execution and binding fence; release Inbox and intent committed | Same release ID returns original; stale epoch rejected or reconcile-only |
| accepted / queued / reserved | released_unbound | AI-PM `expected_binding=unbound` release wins the dispatch/release sequencer | Single per-execution sequencer transaction: release intent + immutable dispatch-fence tombstone committed atomically before 202; exactly one `execution.unbound_release_applied` emitted; reservation released only per capacity policy | Duplicate release_id + identical body returns the original tombstone disposition; dispatch-wins against unbound release returns 409 `BINDING_ALREADY_ESTABLISHED` with the actual epoch; a `released_unbound` tombstone is terminal for the execution_id — no later assignment, requeue, rebind or epoch may resurrect it; a new AI-PM attempt uses a new execution_id |
| release_requested | stopping | Runner stop-fence ACK | ACK proves later starts fenced and every earlier/in-flight start accounted for; it does not prove exit | Duplicate ACK no-op; retain reservation |
| release_requested | released | SEM + Runner evidence | No process was ever created and launch broker confirms no in-flight create; cleanup requirements satisfied | Requires positive no-create proof; otherwise remain pending/uncertain |
| stopping | released | Runner exit + cleanup evidence | Exact containment positively empty/cannot accept descendants; cleanup requirements complete | Duplicate exit/cleanup evidence no-op |
| stopping | cleanup_failed | Cleanup subsystem | Process exit may be proven, but required cleanup failed or remains uncertain | Keep cleanup/quarantine accounting; do not claim full release |
| cleanup_failed | released | Cleanup retry/operator action | Required cleanup subsequently proven complete; process exit remains positively proven | Idempotent completion |
| Any nonterminal state | infrastructure_uncertain | SEM reconciliation controller | Conflicting, missing, ambiguous or unavailable evidence; preserve last known state in history | Never infer failure/release; keep reservation/quarantine |
| infrastructure_uncertain | Last proven nonterminal state | Reconciliation | Authoritative evidence resolves ambiguity without changing binding identity; commit evidence and transition history | Only if no contradictory evidence exists |
| infrastructure_uncertain | delivery_received / starting / running | Runner journal replay | Exact durable receipt/start/process evidence reconciles against same delivery and binding epoch | Apply only in event order; stale epoch is audit-only |
| infrastructure_uncertain | delivery_failed / start_failed | Runner launch/receipt authority | Positive proof of no receipt/no process and no in-flight create; no late effect possible | Never use timeout, disconnect or absence of PID |
| infrastructure_uncertain | release_requested / stopping / released | Release reconciliation | Release command and exact process/containment evidence resolved; follow normal release prerequisites | No direct jump to released without positive exit/no-create and cleanup proof |

Additional SEM invariants:

- released, delivery_failed and start_failed are terminal for the corresponding binding/delivery identity. A later business attempt uses a new execution identity; a transport retry preserves the old identity.
- released_unbound is terminal for the entire execution_id (P0-07 dispatch fence). Dispatch and release linearize on one per-execution sequencer; SEM never judges dispatch permission in two services or two separate transactions.
- A release command can be accepted from any nonterminal SEM state, but it cannot skip the Runner launch-broker resolution or process-exit evidence needed for safe release.
- infrastructure_uncertain is a reconciliation state, not permission to allocate a replacement Runner. The previous known state and all outstanding reservations remain queryable.
- A newer binding epoch is not created while the old process may still exist, unless D-03 provides independent, verifiable isolation/fencing evidence that explicitly permits it.
- Event arrival order does not override event-stream sequence, binding epoch or the evidence authority.

#### 3.4.2 Runner Supervisor transitions

| From | To | Initiator / evidence | Preconditions and durable commit | Duplicate, stale or recovery behavior |
|---|---|---|---|---|
| (new) | delivery_recorded | SEM delivery | Authenticated current session; exact Runner and binding epoch; payload digest verified; delivery and dedupe record committed before receipt ACK | Same delivery/digest returns original receipt; changed digest conflicts |
| delivery_recorded | start_intent | Supervisor sequencer | No stop fence; unique launch ID and containment identity allocated and journaled before OS create | Duplicate start reuses same launch ID and asks broker to adopt/query |
| start_intent | process_created_unconfirmed | OS launch broker | Broker proves process created/adopted within exact containment identity; process handle/identity returned | Crash recovery queries same launch ID; never issues a second create |
| process_created_unconfirmed | running | Supervisor | Exact process identity and started event durably journaled; containment membership verified | Replay same event ID/sequence; repeated observation no-op |
| delivery_recorded | stop_fenced | SEM release command | Sequencer persists release ID and binding fence; proves no start broker call is in flight | Duplicate release returns same ACK; later start rejected |
| start_intent | stop_fenced | SEM release command | Broker confirms create did not cross linearization point and cannot complete later; durable fence committed | If broker operation unresolved, remain uncertain and do not ACK effective stop fence |
| process_created_unconfirmed | termination_requested | SEM release command | Exact containment adopted; stop fence committed before termination intent | Duplicate stop idempotent; never lose process identity |
| running | termination_requested | SEM release command / policy | Stop fence committed; exact containment identity verified; termination intent persisted before OS signal | Duplicate termination returns same operation |
| termination_requested | exited | OS wait/reap or durable process owner | Exact process/containment positively exited; exit evidence journaled before event send | Duplicate evidence no-op; contradictory evidence quarantined |
| running | exited | Natural process exit | Same positive exit proof, without requiring a prior release | Later release still applies stop fence and cleanup idempotently |
| exited | cleanup_pending | Supervisor cleanup/reporting | Exit proof durable; cleanup or event delivery remains outstanding | Retain process/delivery tombstone; retry cleanup/reporting |
| cleanup_pending | cleaned | Cleanup subsystem | Required local cleanup and durable report obligations complete | Keep dedupe tombstone for configured retention |
| Any nonterminal state | local_uncertain | Supervisor recovery | Journal corruption, launch broker ambiguity, missing containment proof, contradictory process evidence or host uncertainty | Quarantine; block duplicate start and release ACK |
| local_uncertain | Prior proven state | Reconciliation | Durable journal + authoritative containment owner resolves exact launch/process state | Adopt same process/launch; never allocate a new launch ID |
| local_uncertain | exited | Durable process owner | Exact containment identity is authoritatively empty and cannot accept descendants; exit status may be unknown | Persist evidence source; PID absence alone is rejected |
| local_uncertain | stop_fenced | Launch broker + sequencer | Proves no process exists and no create is in flight/can complete; release fence committed | Only then ACK no-late-start |
| exited | cleanup_pending | Supervisor | Cleanup remains; exit fact immutable | No return to running |
| cleaned | — | — | Terminal for local delivery lifecycle; tombstone retained | Any duplicate delivery returns terminal record, never restarts |

Runner Supervisor invariants:

- stop_fenced is a durable command fence, not process exit. When a process exists, the state must proceed through termination and positive exit evidence.
- If the create operation is in flight or its outcome is ambiguous, the Supervisor must retain local_uncertain; it cannot claim the stop fence fully effective.
- exited is immutable for a particular process identity. A subsequent process requires a new execution/delivery identity and valid authorization.
- A process may be positively exited with exit_status=unknown if the durable process owner proves containment termination but the numeric exit status was lost.
- cleaned is not a business success signal and does not alter AI-PM Run/Task state.

#### 3.4.3 AI-PM business lifecycle interaction (no SEM-owned transitions)

AI-PM remains the sole authority for TaskStatus, RunKind, RunStatus, RunOutcome and delegated authorization. SEM and Runner events are inputs to AI-PM application services, not direct state writes.

| Input received by AI-PM | AI-PM-side precondition / guard | Allowed business effect | Forbidden shortcut |
|---|---|---|---|
| SEM execution accepted / reserved / bound | Correlated to exact run_id, attempt_no, execution_id; authenticated SEM event | Persist infrastructure observation; no mandatory Task/Run transition | Do not set Run Running merely because SEM reserved/bound |
| Runner process started (via SEM) | Current Run/attempt and authorization/lease fences valid | Application service may record execution observation and apply existing Run transition policy | Do not infer Task completion or Run success |
| Runner process exited (via SEM) | Exact execution and attempt correlated; evidence validated | Application service evaluates RunOutcome/RunStatus under current RunKind transition guard | Do not map exit code 0 directly to Succeeded |
| Harness delivery submitted through MCP | Current delegated grant and exact attempt; required delivery manifest valid | AI-PM submission service may transition Task Running → Submitted | Do not auto-review or auto-accept |
| Human review/acceptance | Authenticated human principal; acceptance evidence complete | Existing AI-PM review guards may transition Submitted → Reviewing → Completed | Harness/SEM cannot impersonate human principal |
| Business retry requested | AI-PM retry policy permits; old attempt terminal or explicitly isolated under policy | Create new Run/attempt (run_id, incremented attempt_no) and new execution_id/authorization generation | Do not reuse old execution ID or treat transport retry as business retry |
| Release requested | AI-PM decides infrastructure no longer needed; durable Outbox in same transaction as business authorization/release decision | Emit stable release intent; Task/Run status changes only if separate business guard allows | SEM release cannot itself set Task Completed/Run Succeeded |

### 3.5 Uncertainty and terminal-state rules

1. Uncertainty is entered when an effect may have occurred but its authoritative evidence is unavailable. It is not a synonym for failure.
2. An uncertain SEM execution or Runner process may leave uncertainty only through a transition in §3.4 backed by the named authority's durable evidence. Timeouts, elapsed SLOs, WSS state and PID absence are never resolution evidence.
3. A duplicate command with the same identity and same canonical payload returns the original durable outcome. Reuse with a changed payload is a conflict and must not mutate state.
4. A late event can advance state only if its event ID, event-stream sequence, execution identity, binding epoch, launch identity and process/containment identity all validate. Otherwise retain it for audit/reconciliation.
5. No transition may reopen a terminal delivery, binding or process identity. A new business attempt creates new AI-PM Run identity and new execution identity.
6. Capacity release is based on positive process-exit/no-create evidence and resource-specific cleanup policy. Workspace cleanup failure may retain disk/quota accounting while process slots are released only if the containment owner proves the process tree is gone.
7. A release request accepted before process creation must fence all later starts. A release request during an unresolved create remains pending; no effective stop-fence ACK is sent until the launch broker proves no-create or created-and-stoppable.
8. SEM may retain the previous known state alongside infrastructure_uncertain; implementation must not destroy that state history when entering or leaving uncertainty.

### 3.6 V1 Linux process-owner contract
> **Additional challenge contract:** See [D-05 Linux Launch, Release and Exit-Proof Addendum](./d05-linux-launch-release-exit-proof-addendum.md). It defines the conservative lost-D-Bus-reply rule, sole-broker boundary, start/release decision table and bracketed exit-evidence protocol. The addendum remains Draft and does not claim P0-02/P0-03/P0-04 closed without Linux failure-injection evidence.


User decision (2026-11-25): V1 Runner hosts are Linux-only. Windows and other operating systems are out of scope for V1.

The selected V1 architecture candidate is a host systemd manager owning one transient service unit and dedicated cgroup v2 subtree per execution binding. The Runner Supervisor is a host-managed systemd service and invokes the manager through its system D-Bus API. A Runner container without a trusted host-side broker is unsupported. The candidate systemd service properties are Type=exec, ExitType=cgroup, RemainAfterExit=yes, CollectMode=inactive, Restart=no and KillMode=control-group, with no cgroup delegation. ExitType=cgroup requires systemd 250 or later, making v250 the minimum candidate version pending distro integration tests. Harness processes run under a distinct unprivileged Unix identity, receive no cgroup delegation or manager access, and cannot move themselves/descendants out of their execution cgroup.

Normative requirements:

- Host admission requires Linux unified cgroup v2, systemd 250 or later as PID 1, reachable system D-Bus manager, and the required cgroup/systemd security controls. Unsupported hosts are never dispatch-ready.
- Each binding has a stable launch_id, containment_id and systemd unit identity derived from runner_id + execution_id + binding_epoch. The exact encoding is an implementation detail covered by the Linux systemd integration test plan; identities must be collision-resistant and immutable.
- The Supervisor commits start_intent and the stable unit identity before calling systemd. A retry queries/adopts the same unit and invocation; it never creates a second independent unit for the same launch_id.
- The systemd manager owns the live process across Supervisor restart; the Supervisor journal owns command idempotency and event durability. Both are required for recovery.
- The broker resolves the exact unit with GetUnit and inspects InvocationID, ControlGroup, ActiveState/SubState and outstanding jobs before retrying. It never blindly repeats StartTransientUnit after an ambiguous reply. Unit names are unique only while loaded; a durable journal tombstone prevents launch_id/unit identity reuse after unit cleanup or garbage collection.
- RemainAfterExit=yes retains a successfully completed service in active/exited state; CollectMode=inactive avoids aggressive inactive-or-failed collection. The Supervisor must not stop/reset-failed/clean the unit before local terminal evidence and SEM reconciliation are durable. The Supervisor journal, not systemd unit retention, is the long-lived tombstone.
- Configure no automatic restart, KillMode=control-group, no cgroup delegation, and no Harness access to host Docker/systemd control sockets. The final systemd property set and minimum supported systemd version require a finalized host contract and Linux systemd integration tests.
- Release/start is serialized through the durable Supervisor sequencer. While a systemd start job is unresolved, state remains local_uncertain and no effective stop-fence ACK is sent. Recovery queries the exact stable unit and outstanding jobs.
- The Supervisor MUST subscribe to systemd Manager job signals before issuing StartTransientUnit and persist the returned job object path/identity when the reply is received. A lost D-Bus reply is reconciled by querying both the exact unit and the manager's outstanding job list; a second StartTransientUnit call is forbidden until this reconciliation resolves the first request.
- systemd Job state distinguishes waiting (queued, not begun) from running (execution begun). CancelJob only cancels a queued job; it has no effect once job execution has begun. Therefore a stop/release path MUST NOT treat a CancelJob request or ACK as a process stop.
- If the exact start job is still waiting, the broker may cancel that job, but must observe the matching JobRemoved result and then independently prove that no unit process/containment was created and no start job remains before returning an effective no-start fence.
- If the exact start job is running, cancellation is not a valid stop mechanism. The broker must issue a StopUnit operation for the exact stable unit, observe its own job result, and then prove the matching invocation is terminal and its cgroup v2 subtree is populated=0. A StopUnit job result alone is not process-exit evidence.
- Job IDs are unique only within one systemd manager runtime. Persist the host boot_id together with job ID/path; never interpret a job ID from a prior boot as current identity. On reconnect/restart, correlate by immutable unit name + boot_id + invocation identity + current outstanding job list.
- JobRemoved result and unit ActiveState/SubState are separate observations. A successful start-job result is not proof of process completion; a canceled start-job result is not sufficient by itself to prove no process was spawned.
- Positive exit requires matching systemd invocation identity, a retained terminal state (active/exited for a successful process with RemainAfterExit, or failed for a non-zero failure) with no restart/start job pending, and exact cgroup v2 populated=0 evidence; the Supervisor journals that evidence before sending it to SEM. Stop-job ACK and PID absence are insufficient.
- Terminal unit/process evidence must remain queryable until the Supervisor journal and SEM reconciliation both durably acknowledge it. Garbage collection cannot erase the only evidence for an uncertain launch.
- Host boot_id changes require old-boot launch-registry reconciliation. A boot boundary can prove old kernel processes cannot continue, but ambiguous host identity/boot lineage still remains quarantined.

This is an architecture selection for V1, not an implementation proof. The exact systemd D-Bus call semantics, unit property set, garbage-collection behavior, cgroup population observation and restart/boot failure handling must pass the D-03 Linux integration and failure-injection suite before ratification. Permanent host loss follows the user-confirmed D-03 V1 policy: visible alert, retained quarantine and auditable on-site operator disposition; no cloud/BMC power-control integration.

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

- Each Runner event is immutable and has a unique `event_id`; sequence is monotonically increasing within a durable Runner event stream identified by `runner_id + journal_id`. The stream identity survives Supervisor restart when the durable journal is retained. Every event also carries `execution_id + binding_epoch`; SEM validates the stream cursor and execution/binding fence independently.
- Reconnect snapshot includes `runner_id`, boot ID, Supervisor instance, connection generation, journal_id, per-stream latest sequence and active process/containment identities.
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

## 10. Acceptance matrix (78 cases)

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
| D05-47 | D-05 is checked against an AI-PM source revision with different Run enums | Ratification blocked until an explicit source compatibility update is reviewed |
| D05-48 | Delivery Run and Review Run attempt an edge valid only for the other kind | AI-PM rejects the edge |
| D05-49 | Supervisor crashes after OS create but before process identity journal commit | Existing launch is discovered through the pre-created containment identity; otherwise quarantine; never launch a duplicate |
| D05-50 | Supervisor crashes during process creation while release arrives | No stop-fence ACK until in-flight create is resolved or independently fenced |
| D05-51 | Process exists outside its expected containment boundary | Quarantine; no claim of safe stop/release |
| D05-52 | Supervisor restarts after child exits but before wait status is persisted | Durable process owner proves containment empty; exit code may be unknown; no PID-only inference |
| D05-53 | Runner rebinds an execution to another Runner with independent event stream | Per-stream sequence cursors remain unambiguous; old binding events are fenced |
| D05-54 | `authorization_generation` changes while `lease_generation` remains unchanged (and vice versa) | Each authority rejects only its own stale generation; no cross-domain substitution |
| D05-55 | Process exit is proven but workspace cleanup fails | Process capacity and cleanup resource accounting follow separate evidence; no false full release |
| D05-56 | `infrastructure_uncertain` receives late valid start/exit/reconcile evidence | Only explicitly allowed reconciliation edges apply; no guessed terminal transition |
| D05-57 | AI-PM receives a TaskStatus edge not present in the pinned 31-edge matrix | Domain guard rejects it; SEM cannot bypass or widen the matrix |
| D05-58 | AI-PM receives a legal Task edge without its required evidence (E1/E2, waiting, failure, supersession or manual completion) | Application/domain guard rejects the transition and leaves Task status unchanged |
| D05-59 | Delivery and Review Run transitions are mixed, or a terminal Run is mutated | Run transition guard rejects the edge; lease reacquisition remains a separate Delivery/Claimed operation |
| D05-60 | SEM or Runner attempts a direct business-state transition based on infrastructure evidence | No business mutation; only AI-PM application service may evaluate RunOutcome/RunStatus/TaskStatus |
| D05-61 | Runner host lacks cgroup v2, systemd PID 1 or required host broker | Host is unsupported and never dispatch-ready |
| D05-62 | Supervisor crashes after systemd accepted StartTransientUnit but before reply | Recovery queries the same stable unit/job and adopts it; no second launch |
| D05-63 | Same launch_id is retried with a different unit identity or payload | Conflict; no process creation |
| D05-64 | Harness attempts to access systemd/Docker control socket or move itself out of its cgroup | Access denied; containment integrity alert; execution quarantined if integrity cannot be proven |
| D05-65 | systemd stop job is acknowledged while cgroup v2 still reports populated=1 | No process-exited event and no capacity release |
| D05-66 | systemd reports unit inactive but invocation identity does not match the recorded launch | Evidence rejected; remain uncertain |
| D05-67 | cgroup reports populated=0 but systemd has a pending restart/job for the same unit | No exit proof; remain uncertain |
| D05-68 | terminal systemd unit is garbage-collected before SEM reconciliation completes | Test must fail; retention contract must preserve recoverable terminal evidence |
| D05-69 | Runner Supervisor runs inside a container without host systemd broker | Runner is unsupported and cannot become dispatch-ready |
| D05-70 | Host boot_id changes and old process registry cannot be correlated to host identity | Old execution remains quarantined; no automatic reassignment |
| D05-71 | Supervisor receives ambiguous StartTransientUnit reply and retries without resolving the unit/job | Test fails; broker must query exact unit/job first and never blindly issue a second start |
| D05-72 | Successful Harness process exits and systemd unit would otherwise be garbage-collected | RemainAfterExit retains terminal unit until reconciliation; durable journal tombstone survives later cleanup |
| D05-73 | Failed Harness unit is reset/garbage-collected before terminal evidence is durable and SEM reconciles | Test fails; cleanup/reset is blocked until both durable acknowledgements exist |
| D05-74 | A cleaned/GC'd unit name is reused for an old launch_id after journal tombstone exists | Broker rejects reuse; launch_id and unit identity are immutable |
| D05-75 | Release races while the exact systemd start job is still `waiting` | Cancel only that job; observe matching JobRemoved result; independently prove no process/unit start and no remaining start job before effective no-start ACK |
| D05-76 | Release races after the exact systemd start job reaches `running` | CancelJob is not treated as cancellation; issue StopUnit for exact unit, await stop-job result, then verify invocation terminal and cgroup populated=0 |
| D05-77 | StartTransientUnit reply is lost before job path/ID is persisted | Subscribe-before-call and reconcile exact unit plus ListJobs; no blind duplicate StartTransientUnit |
| D05-78 | Supervisor reuses a systemd job ID across host reboot | Reject prior-boot job identity; correlate with boot_id and immutable launch/unit/invocation identity |
| D05-79 | StartTransientUnit request may have crossed D-Bus send boundary but reply is lost and no job/unit is currently visible | Remain local_uncertain and quarantined; no blind retry; missing ListJobs/GetUnit result is not proof of non-acceptance |
| D05-80 | Supervisor crashes after durable start intent but before D-Bus request is sent, with durable proof that send was not attempted | Retry same immutable launch_id through the single-writer broker; at most one unit |
| D05-81 | A second actor attempts to create or replace a unit in the reserved SEM namespace | Privilege boundary blocks it; detected interference quarantines the execution |
| D05-82 | Release commits while StartTransientUnit is call_in_flight | Persist release fence but do not ACK; reconcile exact job/unit until no-start or started-and-stopped is positively proven |
| D05-83 | Exact waiting start job receives CancelJob | No effective no-start ACK until matching JobRemoved plus no invocation, no pending start job and cgroup populated=0 |
| D05-84 | Exact start job is running when release arrives | CancelJob is not treated as stop; StopUnit exact unit, await stop job and verify invocation terminal plus cgroup populated=0 |
| D05-85 | StartTransientUnit call has ambiguous outcome and exact unit has a conflicting InvocationID or launch digest | Integrity conflict; quarantine; never adopt or retry |
| D05-86 | Exit evidence bracket observes different InvocationID or ControlGroup on second unit query | Reject candidate evidence; remain uncertain |
| D05-87 | cgroup.events populated changes between first and second reads | Reject candidate evidence; remain uncertain |
| D05-88 | A start/restart job appears between the two job snapshots used for exit proof | Reject candidate evidence; remain uncertain |
| D05-89 | Unit disappears or is garbage-collected before terminal evidence is durably journaled and SEM reconciles | No process-exited event; retention test fails; quarantine |
| D05-90 | Supervisor restarts after process exit with exact containment empty but numeric wait status unavailable | Report positive exit only if invocation-bound durable evidence is reconstructed; exit_status=unknown |
| D05-91 | Disk full or fsync failure before start/release/exit evidence commit | No ACK and no unsafe side effect; retain uncertainty/quarantine |
| D05-92 | Harness attempts system-bus, systemd control or cgroup mutation | Access denied; if containment integrity cannot be proven, quarantine |
| D05-93 | Out-of-band administrator changes or replaces the reserved unit | Detect identity/property mismatch; quarantine and audit; no silent adoption |
| D05-94 | Broker sees no matching job/unit after ambiguous D-Bus request but cannot prove request was never sent | Remain local_uncertain; operator reconciliation; no second StartTransientUnit |
| D05-95 | harness.process_exited omits evidence_schema_version or evidence_digest | Schema validation rejects the event; no process-exited transition |
| D05-96 | Replayed event reuses evidence_id but changes digest or evidence payload | SEM detects integrity conflict and quarantines/reconciles; never overwrite accepted evidence |
| D05-97 | SEM sends durable event ACK before the complete event envelope is committed | Test fails; ACK must follow durable persistence |
| D05-98 | Runner deletes or mutates the raw evidence record before receiving durable ACK for its event_sequence | Test fails; evidence must remain replayable and immutable until ACK |
| D05-99 | Runner replays process-exit event after reconnect | journal_id, event_sequence, evidence_id, schema version, digest and payload remain identical; only connection-scoped framing may change |
| D05-100 | SEM sends durable ACK without acknowledged_journal_id or acknowledged_event_sequence | Reject ACK; Runner retains raw evidence and replays the event |
| D05-101 | ACK journal_id/event_sequence refers to a different durable stream position | Reject as stale/conflicting ACK; do not release evidence retention gate |
| D05-102 | Transport ACK or accepted/duplicate disposition is received without durable_recorded disposition for the exact event cursor | Do not delete or mutate the process-exit evidence record |

## 11. Open decisions required before ratification

1. Recheck the pinned AI-PM Run/attempt source revision immediately before ratification; any source drift requires a new compatibility review.
2. Whether SEM persists a single execution aggregate with transition history or separate delivery/binding/release tables; uniqueness constraints and retention.
3. Runner journal storage engine, fsync policy, corruption recovery and disk-full behavior.
4. Exact D-Bus StartTransientUnit request/property serialization, non-replacing job mode, JobNew/JobRemoved correlation, GetUnit/GetJob/ListJobs recovery behavior and systemd >=250 distro compatibility; the Linux systemd integration test plan must prove these with failure injection.
5. Durable terminal-unit evidence retention through both local journal and SEM acknowledgement, including successful exit, failed exit, StopUnit-driven termination, unit garbage collection and Supervisor restart.
6. Event sequence scope is proposed as a durable Runner event stream keyed by `runner_id + journal_id`, with `execution_id + binding_epoch` carried on each event. D-04 must freeze the stream/cursor schema and retention semantics and cross-check every state-changing WSS message.
7. Snapshot/replay API exact schemas, cursor semantics and maximum journal retention.
8. Reservation expiry/recovery rules and the minimal audited manual operator disposition under the user-confirmed D-03 host-loss profile.
9. D-04 now defines evidence_id as an immutable Runner journal reference, adds evidence_schema_version + JCS/SHA-256 evidence_digest to harness.process_exited, and requires SEM durable event persistence before journal-sequence ACK. the Linux systemd integration test plan must prove journal fsync, replay identity, ACK gating and post-ACK retention; independent cryptographic verification is not a V1 promise.
10. Exact reconciliation deadlines are operational SLOs, not correctness shortcuts; timeout must never resolve uncertainty by assumption.

## 12. Readiness conclusion

D-05 now has a detailed lifecycle, transaction, crash-recovery and acceptance proposal. It is **not ratified** until the open decisions above are resolved, the AI-PM Run/attempt vocabulary is checked against the exact source revision, and D-04 schemas encode the required identities and replay behavior.

**D-05 status: DRAFT / REVIEW — NOT READY FOR DEVELOPMENT.**

No runtime implementation, migration, deployment change, Phase 0 or merge is authorized by this document.
