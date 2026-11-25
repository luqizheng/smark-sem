# D-05 Independent Architecture Audit

- Status: **CHANGES REQUIRED — NOT READY FOR RATIFICATION OR DEVELOPMENT**
- Reviewed D-05 HEAD: `1a8433bcdecb5bc9537fb171f3c41a1631ae2ee3`
- Reviewed AI-PM source baseline: `master` at `d0e72fa6805aebeadf1b282e430deba493072fd6`
- Scope: independent review of lifecycle authority, AI-PM source compatibility, process start/exit evidence, release/start races, crash recovery, event ordering and acceptance coverage.
- This is a documentation-only audit. It does not authorize runtime changes, migrations, deployment changes, Phase 0 or merge.

## 1. Executive conclusion

The D-05 draft has the right top-level safety principles: three independent authorities, durable-before-effect, unknown-is-not-failed, no blind duplicate start, separate business and infrastructure fencing, and no inference of business success from process exit.

However, the draft is not yet an implementable lifecycle contract. Four blocking findings remain:

1. The proposed AI-PM Run/attempt states do not match the current AI-PM source model and conflate Run status, Run outcome, Task status and authorization lifecycle.
2. The process-create-before-journal window is named but not closed by a concrete OS-level launch/containment primitive or an idempotent launch broker.
3. The release/start race is described as serialized, but the design does not define the linearization point or how release behaves when OS process creation is already in flight.
4. Positive process-exit evidence after Supervisor crash/restart is not tied to a concrete durable process owner/containment authority. A local journal alone cannot preserve a wait status if the process-owning Supervisor dies.

The draft also lacks complete transition tables, explicit uncertainty-resolution edges, a frozen event-sequence scope, and several acceptance cases for the above failure windows.

**Recommendation: keep PR #3 Draft. Resolve P0 findings and update D-04/D-03 contracts before D-05 ratification.**

## 2. Source-of-truth verification against AI-PM

Reviewed source files on AI-PM `master`:

- `crates/pm-domain/src/task.rs`
- `crates/pm-domain/src/task_run.rs`
- `crates/pm-application/src/run_transition_guard.rs`
- `crates/pm-application/src/run_dispatch/port.rs`
- `crates/pm-application/src/run_dispatch/claim.rs`
- `crates/pm-application/src/run_dispatch/lease.rs`
- `crates/pm-infrastructure/src/repo_runs.rs`
- `apps/ai-pm-runner/src/adapter.rs`
- `apps/ai-pm-runner/src/runner_loop.rs`

### 2.1 Task lifecycle is a separate 13-state machine

The actual `TaskStatus` enum is:

`Draft, Ready, Claimed, Running, AwaitingDecision, Blocked, Submitted, Reviewing, Completed, ChangesRequested, Failed, Cancelled, Superseded`.

D-05 correctly says that Task transitions remain AI-PM-owned and must not be driven directly by SEM infrastructure events. Preserve this boundary.

### 2.2 Current Run lifecycle is not the proposed D-05 lifecycle

The actual application enum is `RunKind::{Delivery, Review}` and `RunStatus::{Queued, Claimed, Running, Succeeded, Failed, TimedOut, Cancelled}`.

The current guarded transition matrix is:

| Run kind | From | Allowed targets |
|---|---|---|
| Delivery | Queued | Claimed, Failed, Cancelled |
| Delivery | Claimed | Running, Queued, Succeeded, Failed, TimedOut, Cancelled |
| Delivery | Running | Queued, Succeeded, Failed, TimedOut, Cancelled |
| Review | Queued | Running, Cancelled |
| Review | Running | Succeeded, Failed, TimedOut, Cancelled |

Terminal Run statuses are immutable. Delivery lease reacquisition is a same-state operation while `Claimed`, not a lifecycle transition.

The current D-05 proposal (`created / authorized / active / result_submitted / awaiting_review / succeeded / failed / cancelled / superseded`) therefore cannot be described as the current AI-PM Run state machine. In particular:

- `result_submitted` and `awaiting_review` are not current `RunStatus` values.
- `superseded` is a Task status, not a current Run status.
- `authorized` is not a current Run status.
- `succeeded / failed / cancelled` overlap with Run status vocabulary but must not be confused with `RunOutcome` or Task status.
- Delivery and Review Runs have different allowed edges and must not be collapsed into one generic Run transition table.

The separate `RunOutcome` enum is `Succeeded / Failed / TimedOut / Cancelled`. It is outcome data, not the Run status enum.

### 2.3 Identity and fencing fields need precise mapping

The current Run creation path creates a `run_id` and increments `attempt_no` for each Delivery Run. This is the current durable representation of an execution attempt; there is no separate current `attempt_id` in the reviewed domain model.

The current executor lease has `lease_generation` and a lease token. D-05's proposed `authorization_generation` is a different business-authorization fence and must not be silently mapped to or substituted by `lease_generation`.

Required D-05 correction:

1. Use `run_id` as the stable current Run/attempt identity and retain `attempt_no` as its task-local ordinal.
2. Model the current `RunStatus` and `RunOutcome` exactly as separate concepts.
3. Model Task status independently using the actual 13-state enum.
4. Model future delegated authorization as a separate AI-PM-owned authorization record/generation, with explicit correlation to `run_id`; do not invent additional RunStatus values.
5. Preserve Delivery vs Review Run kinds and their distinct transition rules.
6. State clearly which future schema additions are proposals, not existing source facts.

The AI-PM source baseline is a moving branch. The final D-05 ratification must record the exact source commit used for compatibility and re-check it if AI-PM changes before implementation.

## 3. Blocking findings

### P0-01 — AI-PM Run/attempt state model is source-incompatible

**Evidence:** `crates/pm-application/src/run_transition_guard.rs`, `crates/pm-domain/src/task_run.rs`, `crates/pm-domain/src/task.rs`, `crates/pm-application/src/run_dispatch/port.rs`.

**Problem:** D-05 currently presents a proposed nine-state Run/attempt model without an explicit mapping to the existing seven-state RunStatus, four-value RunOutcome, two RunKinds and independent TaskStatus. This would lead to implementation teams creating a second, incompatible business lifecycle or incorrectly treating infrastructure events as business transitions.

**Required correction:** Replace §3.1 with a source-compatible mapping table and identify each future extension as a separate authorization dimension or proposed record. Include the exact source commit. Add an acceptance case proving that SEM process-exit/release events cannot directly set RunStatus, RunOutcome or TaskStatus.

### P0-02 — OS process creation is not yet idempotent across the create/containment/journal crash window

**Evidence:** D-05 §3.3, §5.3, §6.6. The draft requires a pre-create `start_intent`, then says recovery should enumerate a dedicated containment unit using a launch nonce/labels. It does not specify how the OS guarantees that a created process is already inside that unique containment unit, nor how the unit is discoverable if the Supervisor crashes immediately after create.

**Problem:** A pre-create journal record alone does not prevent duplicate processes. If OS process creation succeeds and the Supervisor dies before persisting the process identity, a retry may create a second process unless the launch operation itself is idempotent and the process is discoverable through a pre-existing, unique containment identity. A post-create “assign to cgroup/job” step can itself introduce another orphan window.

**Required correction:**

- Allocate and durably persist a unique `launch_id` and immutable containment identity before process creation.
- Define a platform-specific primitive that creates the process within the already-identified containment boundary, or define a single-writer launch broker/service that durably owns and deduplicates the launch operation.
- Linux profile must choose and specify an enforceable primitive (for example, an OCI/container-runtime unit with stable unique ID, a systemd transient unit, or a supported `clone3(CLONE_INTO_CGROUP)` design). The design must also prevent the child from escaping/migrating out of its containment boundary.
- Windows profile must define Job Object assignment at creation time (for example, a supported extended startup attribute/job-list design) or a brokered create/assign/resume protocol whose crash recovery is explicit. “Create then assign” without a recoverable owner is insufficient.
- Recovery must query the unique containment/launch identity, adopt the one existing process if proven, and otherwise quarantine. It must never infer “not created” from a missing PID file.
- Define disk-full, journal corruption and partial containment creation behavior.

Do not declare this race closed by the phrase “enumerate the containment unit”; the unit's creation, ownership and discoverability must be specified.

### P0-03 — Release/start race has no defined linearization point

**Evidence:** D-05 §3.3, §4, §6.1.

**Problem:** The draft says start and release are serialized per execution/binding and that a durable stop fence prevents late starts. It does not define what happens when a start operation has crossed the durable `start_intent` boundary and is currently inside the OS create call when release arrives. Persisting `stop_fenced` cannot retroactively cancel an OS create already in flight.

**Required correction:**

- Define one Supervisor single-writer command sequencer for each `execution_id + binding_epoch`.
- Define the exact start linearization point and whether the OS create operation is synchronous from the sequencer's perspective.
- If release arrives before the OS create linearization point, it must durably fence and prevent creation.
- If release arrives after the create linearization point, the Supervisor must discover/adopt the process and terminate that exact containment unit.
- If the create result is ambiguous, release must remain pending/uncertain; the Supervisor cannot ACK that no process can start until the in-flight operation is resolved or independently fenced.
- A stop-fence ACK must mean both that later starts are fenced and that any earlier in-flight start has been accounted for. It still does not mean process exit.
- Specify Supervisor crash behavior at every point in the sequence.

### P0-04 — Process-exit proof after Supervisor crash is underspecified

**Evidence:** D-05 §3.3, §5.3, §6.7.

**Problem:** A Supervisor's in-memory child handle / wait-reap result is not durable across Supervisor process death. The draft says to re-observe the exact containment unit or use a durable OS/Supervisor record, but does not name which component owns that record or what evidence is sufficient. A process disappearing from a PID listing is not enough; nor does a new boot ID prove external side effects were undone.

**Required correction:**

- Identify the durable process owner for each supported OS/deployment profile (for example, container runtime/system service manager/host supervisor) and the authoritative query used after SEM Runner Supervisor restart.
- Define positive exit proof as a stable containment identity whose process set is authoritatively empty and cannot accept late descendants, or a durable exit record from the process owner. PID absence alone is never sufficient.
- Define how child processes are prevented from escaping the containment boundary.
- Separate “process no longer executing on this host” from “all external side effects are rolled back”; only the former can release local process capacity.
- Define whether exit code can be unknown after Supervisor crash while process-exit itself is still positively proven.
- If the selected host profile cannot prove exit, remain quarantined and require operator intervention per D-03.

## 4. Major design gaps (P1)

### P1-01 — State transition tables are incomplete

The draft lists state meanings and a few high-level paths, but does not provide a complete allowed-transition table for all three authorities. It also does not define all transitions out of `infrastructure_uncertain`, `local_uncertain`, `cleanup_failed`, or the recovery path from a late but valid event.

Add normative tables with: current state, target state, actor, preconditions, durable write, emitted event, duplicate behavior, fencing rule, and recovery behavior. Define which states are terminal per execution vs terminal per binding.

### P1-02 — Event sequence scope is inconsistent/open

§5.4 says sequence is per execution/binding, while §11 leaves “per execution or per execution + binding epoch” open. A rebind to a different Runner can create a new event producer for the same execution. A single per-execution sequence then requires cross-Runner sequence allocation, which is not naturally owned by either Runner.

**Recommendation:** Scope the monotonic sequence to a durable Runner event stream (for example, `runner_id + journal_id`), preserve that stream across Supervisor restarts, and include `execution_id + binding_epoch` in every event. A new Runner has its own stream. SEM tracks contiguous cursors per stream and validates execution/binding fencing separately. Freeze this in D-04 schemas.

### P1-03 — `authorization_generation` and `lease_generation` are not mapped

The reviewed AI-PM source already has a Delivery Run `lease_generation` for executor lease fencing. D-05 requires a future `authorization_generation` for delegated MCP authority. Define them as independent counters with distinct owners, storage, validation paths and rotation/revocation semantics. Do not reuse one to satisfy the other.

### P1-04 — Uncertain state and retry/rebind policy needs explicit edges

The rule “unknown is not failed” is correct, but the draft must define how uncertainty can be resolved without allowing unsafe retry. Specify evidence that permits return to a known state, re-delivery of the same delivery ID, new binding, new execution ID, or operator release. A timeout/SLO must never be the resolution evidence.

### P1-05 — Capacity release and cleanup need separate evidence

Define exactly when CPU/RAM/process slots may be returned, when disk/workspace cleanup is complete, and when the SEM reservation is fully released. If process exit is proven but cleanup fails, represent process capacity as free only if the containment is empty while retaining a cleanup/quarantine record for resources still consumed. Workspace backup remains out of scope.

### P1-06 — D-03 host profile must be selected or constrained for V1

D-05 depends on D-03 to prove permanent host loss. The no-independent-management profile must default to quarantine/operator intervention. Ratification must either select supported host profiles for V1 or explicitly make the weaker profile unsupported for automatic failover.

### P1-07 — D-04 schemas must carry the actual fencing and evidence tuple

OpenAPI/JSON Schema must define canonical identity, idempotency, event sequence/cursor, process identity, containment identity, launch nonce, boot ID, authorization generation, lease generation (where surfaced), binding epoch, release fence, evidence type, and unknown/contradictory event behavior. D-05 cannot be ratified independently of these schema semantics.

## 5. Existing AI-PM Runner code: compatibility warning, not a target implementation prescription

The reviewed AI-PM Runner currently uses local process APIs and persists process metadata after `Command::spawn()` in `apps/ai-pm-runner/src/adapter.rs`. Its existing `ExecutorSession` is described as a pre-spawn launch intent, and the application executor has its own `ExecutorProgress::Uncertain` recovery semantics.

This code is useful as source-audit evidence, but it is not proof that the new independent SEM Runner Supervisor already satisfies D-05. The new topology must not assume that the current AI-PM Worker/Runner process registry is a durable, cross-host SEM process journal. The new Supervisor requires its own explicit journal, containment owner and recovery protocol.

## 6. Required acceptance additions

Add at least these cases to the D-05 matrix:

| ID | Scenario | Required result |
|---|---|---|
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

## 7. Required document changes before re-review

1. Rewrite D-05 §3.1 using the actual AI-PM TaskStatus, RunKind, RunStatus and RunOutcome model; mark future authorization state as a separate proposal.
2. Add a source-compatibility mapping with the reviewed AI-PM commit and exact field mapping (`run_id`, `attempt_no`, `lease_generation`).
3. Close P0-02 with a concrete V1 Linux process creation/containment/recovery design; Windows is explicitly out of V1 scope.
4. Close P0-03 with a command sequencer and start/release linearization contract.
5. Close P0-04 with durable process-owner exit evidence and explicit unknown-exit-code behavior.
6. Add complete transition tables and uncertainty-resolution edges for all three authorities.
7. Freeze event stream/sequence scope in D-04 schemas.
8. Add D05-47 through D05-56 acceptance cases and tests for all P0 race windows.
9. Align D-03 host profiles and D-09 operational retention/recovery with the selected process containment design.

## 8. Audit disposition

| Area | Result |
|---|---|
| Authority separation | Pass at principle level |
| Task lifecycle boundary | Pass, subject to source mapping |
| AI-PM Run/attempt compatibility | **Fail — P0-01** |
| Durable delivery/idempotency model | Pass at principle level; schemas still open |
| Process creation crash consistency | **Fail — P0-02** |
| Release/start race | **Fail — P0-03** |
| Process exit evidence after Supervisor crash | **Fail — P0-04** |
| Event replay/sequence | Partial — P1-02 |
| State transition completeness | Partial — P1-01 |
| Acceptance coverage | Partial — add D05-47–56 |
| Readiness | **CHANGES REQUIRED** |

**Final disposition: D-05 remains Draft / Review. Do not ratify, merge or start implementation until P0-01 through P0-04 are closed and independently re-reviewed.**


## 9. Follow-up revision status (2026-11-25)

After this audit was committed, the D-05 draft was revised on the same review branch:

- `b109c62`: §3.1 now maps the exact AI-PM TaskStatus, RunKind, RunStatus, RunOutcome, `run_id`, `attempt_no` and `lease_generation` source model; delegated `authorization_generation` is explicitly separate.
- `db59053`: §3.3 now requires a pre-created stable launch/containment identity, an idempotent launch broker or equivalent OS primitive, named Linux/Windows profile decisions, and durable process-owner evidence for post-restart exit proof.
- `a04cc16`: §6.1 now defines a single-writer launch/release sequencer and the required start linearization behavior; stop-fence ACK is withheld while an in-flight create remains unresolved.
- `d527203`: event sequence recommendation now uses a durable Runner event stream keyed by `runner_id + journal_id`, with execution and binding identity carried per event.
- `d7cc817`: acceptance cases D05-47 through D05-56 were added; the matrix reached 56 cases.
- `26299f8`: added normative SEM Execution and Runner Supervisor transition tables, including actor/evidence, preconditions, durable commits, duplicate handling and uncertain-state recovery edges; corrected identity tuple fields to use AI-PM `run_id + attempt_no` and added `launch_id`, `containment_id` and `journal_id`.
- `91599bc`: added the complete 31-edge AI-PM TaskStatus allow-list with transition guards, verified against the pinned domain source.
- `b1ee2a5`: added D05-57 through D05-60 to test forbidden business-state mutation and AI-PM transition guards; the matrix now has 60 cases.

These edits address the source-mapping defect and the previously missing normative transition-table requirement at the document level. The complete matrices still require independent line-by-line review and implementation-level contract tests. They do **not** close all P0 findings:

- P0-01 is corrected in the draft but requires independent re-review against the pinned AI-PM source commit.
- P0-02: V1 OS scope and architecture candidate are now selected (Linux + host systemd + cgroup v2); remains open until systemd D-Bus launch idempotency, unit retention/GC, cgroup isolation and crash behavior pass integration/failure-injection tests.
- P0-03 is materially specified; remains open until the Linux launch broker proves the start/release linearization contract under failure injection.
- P0-04: systemd manager + cgroup v2 are selected as the V1 process owner/evidence source; remains open until exact invocation matching, terminal unit retention, cgroup populated=0 observation and post-Supervisor-crash recovery are proven.
- P1-01 is now addressed in the draft with SEM, Runner and AI-PM transition tables plus uncertainty-resolution edges; it remains subject to independent review for omitted/contradictory edges.
- D-04 machine-readable stream/cursor schemas (P1-02/P1-07) remain required. The D-05 main acceptance matrix has since expanded to 70 cases (D05-61–74 cover Linux profile and process-owner behavior).

**Updated disposition remains CHANGES REQUIRED.** The audit is a review record, not an approval. D-05 remains Draft / Review and is not ready for ratification or development.

## 10. Linux-only V1 decision and follow-up audit status (2026-11-25)

The user approved Linux-only Runner hosts for V1. The D-03 draft now selects the architecture candidate of a host-managed systemd transient service per execution, backed by a dedicated cgroup v2 subtree. Runner Supervisor is a host-managed systemd service; Harness runs under a separate unprivileged Unix identity. Windows, cgroup v1, non-systemd Linux and Runner containers without a trusted host-side broker are out of scope.

The D-05 draft now contains the Linux process-owner contract and D05-61 through D05-74, bringing its main acceptance matrix to 74 cases. It also specifies systemd 250+ candidate properties (Type=exec, ExitType=cgroup, RemainAfterExit=yes, CollectMode=inactive, Restart=no, KillMode=control-group), exact-unit/job lookup before retry, and durable launch tombstones after unit cleanup. The completion register and architecture index were updated.

This is a design decision, not implementation evidence. The Linux profile is not ready for ratification until a focused integration design/test plan resolves at least:

1. Exact systemd minimum version and D-Bus StartTransientUnit/StopUnit job semantics, including timeout and ambiguous reply handling.
2. Stable unit naming, invocation identity, unit garbage-collection/retention behavior, and how terminal evidence survives until SEM reconciliation.
3. Exact cgroup v2 subtree ownership, write permissions, populated=0 observation, descendant escape prevention and cleanup semantics.
4. How the Supervisor's durable journal and systemd's manager state reconcile after Supervisor crash, systemd restart, host reboot and disk-full/journal corruption.
5. How a host-side broker is packaged and authenticated if Runner control-plane components are containerized.
6. Failure-injection evidence for every start/release/exit boundary in D-03 §13.5 and D-05 D05-61–74.

(Superseded by §11) At the earlier review snapshot, permanent host loss had no selected deployment profile. The user subsequently confirmed the V1 visible-status + quarantine + manual on-site handling policy; no managed VM/BMC integration is required.

**Updated audit disposition: CHANGES REQUIRED.** The OS scope and architecture candidate are selected, but P0-02/P0-03/P0-04 remain open pending Linux integration/failure-injection proof; P0-01 still requires independent source/matrix review. No ratification or implementation is authorized.

## 9. Follow-up re-review against the current D-05 draft — 2026-11-25

Reviewed current companion draft sections 3.1, 3.4, 3.6, 4, 5.3–5.4 and 6.1 against the earlier findings. The previous P0 findings must not be repeated as if no progress occurred; the current disposition is below.

### P0-01 — AI-PM Run/attempt source compatibility: CLOSED AT DRAFT-CONTRACT LEVEL

The current D-05 §3.1 now pins the AI-PM source baseline and explicitly maps:
- 13 TaskStatus values and the 31 guarded TaskStatus edges;
- RunKind Delivery/Review and the seven RunStatus values with distinct transition matrices;
- RunOutcome as separate outcome data;
- run_id + attempt_no as current Delivery attempt identity;
- lease_generation as current executor-lease fencing;
- authorization_generation as a future, separate AI-PM-owned authorization dimension.

This closes the original source-vocabulary conflation in the Draft. It does not prove the source has not changed since the pinned commit; the exact AI-PM source must be re-audited immediately before ratification and bilateral implementation.

### P0-02 — OS create/containment crash window: PARTIALLY ADDRESSED; INTEGRATION PROOF OPEN

The current D-05 §3.6 selects a V1 Linux-only host profile: systemd >=250 as PID 1, cgroup v2, host systemd manager, one stable transient service/cgroup per execution binding, no automatic restart, KillMode=control-group, no cgroup delegation, and a durable launch_id/unit tombstone. It defines GetUnit/InvocationID/ControlGroup/job inspection after ambiguous StartTransientUnit replies and forbids blind second starts. This is materially more concrete than the earlier generic OS-adapter draft and Windows is now out of V1 scope.

Remaining blockers:
- Earlier §3.3 generic text still says the Linux OS adapter decision is open and lists multiple alternatives/Windows. Reconcile or explicitly supersede that text so there is one normative V1 profile.
- Define the exact D-Bus StartTransientUnit request, unit properties, job-mode, returned job-path persistence, and the GetUnit/GetJob recovery decision table. A stable unit name alone is not proof that a specific invocation was started exactly once.
- Prove the launch broker's same-launch_id deduplication and systemd job semantics under a real systemd >=250 host with failure injection at request-send, manager-accept, job-queued, ExecStart, process-created, Supervisor-crash and reply-lost boundaries.
- Prove cgroup escape prevention and the exact privilege boundary with a hostile Harness/descendant test.

### P0-03 — Release/start race: PARTIALLY ADDRESSED; SYSTEMD JOB LINEARIZATION NEEDS PROOF

Current §6.1 now defines a per-execution/binding durable single-writer sequencer, a launch-broker linearization point, before/after release behavior, unresolved-create uncertainty, and the meaning of stop-fence ACK. This closes the earlier absence of any linearization model at the conceptual level.

The remaining ambiguity is the exact OS linearization point. systemd `StartTransientUnit` returns a job object; acceptance/queueing of that job is not necessarily equivalent to ExecStart having created the process. The contract must distinguish at least: request not accepted; job accepted/queued; job running; unit process spawned; unit terminal. If release arrives after job acceptance but before process spawn, the broker must define how it cancels/fences that exact job and prove no late process can appear. Do not use “atomically creates or adopts the process” as a shorthand for the D-Bus method unless the integration proof establishes that behavior.

### P0-04 — Process exit after Supervisor crash: PARTIALLY ADDRESSED; EVIDENCE QUERY CONTRACT OPEN

Current §3.6 identifies systemd as durable process owner and requires matching InvocationID, retained terminal unit state, no pending start/restart job, exact cgroup v2 populated=0, and journaled evidence. It also separates unknown numeric exit status from proof that the containment is empty. This is a substantial improvement.

Remaining blockers:
- Freeze exact systemd properties and D-Bus query sequence used to bind the observation to the immutable invocation: InvocationID, ControlGroup, ActiveState, SubState, Result, ExecMainCode, ExecMainStatus, job state and cgroup.events populated value.
- Define how evidence is captured atomically enough to avoid querying one invocation and reading cgroup state after a unit-name reuse/race. The journal tombstone and invocation check must fence reuse.
- Prove retention/GC behavior for successful and failed units until both local journal and SEM reconciliation acknowledge evidence.
- Define host reboot reconciliation separately from the user-confirmed D-03 manual host-loss procedure; systemd state from the prior boot may not be queryable after reboot.

### P1 observations

- The event sequence scope is now explicit in D-05 §5.4 as `runner_id + journal_id`, with execution_id + binding_epoch validated separately. Confirm every state-changing WSS message branch carries journal_id + event_sequence and that replay snapshots/cursors use the same scope.
- D-05 now has explicit uncertainty-resolution edges and a separate process-capacity vs workspace-cleanup distinction. The D-05 transition table and the D-04 wire schemas still need a mechanical cross-reference check.
- The selected systemd profile remains an architecture candidate, not an implementation proof. No runtime work should start until D-10 integration/failure-injection evidence and D-03 host-loss profile are complete.

## 10. Updated disposition

| Finding | Previous | Current |
|---|---|---|
| P0-01 AI-PM Run/attempt vocabulary | OPEN | **CLOSED at Draft-contract level; source recheck required before ratification** |
| P0-02 create/containment crash window | OPEN | **PARTIAL; Linux systemd profile selected, integration proof and stale generic text remain** |
| P0-03 release/start race | OPEN | **PARTIAL; conceptual linearization defined, systemd job boundary remains ambiguous** |
| P0-04 exit evidence after Supervisor crash | OPEN | **PARTIAL; systemd process owner identified, exact query/atomicity/retention proof remains** |
| P1-02 event sequence scope | OPEN | **DRAFT-CLOSED; verify all state-changing message branches and replay cursors** |

**Overall: CHANGES REQUIRED — NOT READY FOR RATIFICATION OR DEVELOPMENT.** This re-review records real progress but does not close D-05's remaining P0 integration and D-03 dependencies.

## 11. Re-review after D-03 V1 host-loss decision and D-05 Linux-profile alignment — 2026-11-25

The user has explicitly confirmed the V1 permanent-host-loss operating model: the deployment is inside the company network; SEM only needs to make an unreachable Runner visible; an on-site person handles physical investigation. No cloud/VM power API, BMC/IPMI or remote power-off integration is required.

D-03 now specifies a durable `unreachable` status in the SEM operator-facing surface, `infrastructure_uncertain` affected executions, retained quarantine/reservations, and a minimal audited manual resolution action only when normal Runner reconnect/reconciliation cannot resolve the incident. No email/SMS/IM integration, evidence-upload subsystem, cloud/BMC control or automatic permanent-host-loss failover is required. Alert/status acknowledgement, timeout, WSS disconnect, heartbeat expiry, MCP revocation and stop ACK do not release capacity.

The stale D-05 §3.3 generic OS-adapter alternatives have also been replaced with the already user-approved Linux-only systemd 250+/cgroup v2 profile. Windows Job Object and alternate Linux launch mechanisms are explicitly out of V1 scope. This closes the documentation contradiction identified in the previous review; it does not close the systemd integration proof.

### Updated findings

- **P0-02 stale generic OS profile text: CLOSED at Draft-contract level.** D-05 §3.3 now consistently selects the Linux systemd transient-unit/cgroup v2 profile. Exact D-Bus properties, StartTransientUnit job semantics, hostile-descendant containment and crash injection remain open.
- **D-03 permanent-host-loss deployment choice: CLOSED at user-decision level.** V1 is visible alert + quarantine + manual on-site operator disposition. There is no open choice among managed VM/BMC/unmanaged profiles. The minimal administrative disposition/audit record and its authorization still require acceptance tests; no separate evidence-management workflow is required.
- **P0-03 release/start race: PARTIAL.** systemd job accepted/queued versus ExecStart/process-spawn linearization and cancellation/fencing proof remain open.
- **P0-04 process exit after Supervisor crash: PARTIAL.** Exact systemd D-Bus evidence query, cgroup observation consistency, unit retention/GC and reboot reconciliation remain open.
- **P0-01 remains closed only at Draft-contract level; AI-PM source recheck is required immediately before ratification.
- **P1 event stream scope remains Draft-closed pending full branch-by-branch schema/cursor cross-check.

**Overall disposition remains CHANGES REQUIRED — NOT READY FOR RATIFICATION OR DEVELOPMENT.** The host-loss decision and stale OS-profile contradiction are resolved, but the Linux integration/failure-injection evidence and D-04 bilateral protocol closure are still missing.
## 12. systemd D-Bus job semantics verification — 2026-11-25

Reviewed the official systemd 250 D-Bus API contract. It confirms that StartTransientUnit returns a job object path; the Manager exposes JobNew/JobRemoved, ListJobs and GetJob; job state is waiting or running; and CancelJob has no effect once execution of that job has begun. The API also documents that a canceled JobRemoved result does not by itself prove the associated operation had no process side effect. See the [systemd 250 D-Bus API](https://www.freedesktop.org/software/systemd/man/250/org.freedesktop.systemd1.html).

The official systemd control-group interface documents that RemainAfterExit retains a completed transient service in `SubState=exited`, allowing status properties to be read before StopUnit cleanup. See [systemd Control Group Interface](https://systemd.io/CONTROL_GROUP_INTERFACE/).

Consequences now incorporated into D-05 §3.6 and acceptance cases D05-75–78:
- Subscribe to job signals before StartTransientUnit and persist returned job identity/path; lost replies require exact unit + ListJobs reconciliation, never blind duplicate start.
- A `waiting` start job may be canceled, but no effective no-start ACK is allowed until the matching JobRemoved result and independent no-process/no-pending-start proof are observed.
- A `running` start job cannot be canceled with CancelJob. The broker must issue StopUnit against the exact unit, observe its stop job, then verify exact invocation terminal state and cgroup v2 `populated=0`.
- Job IDs are manager-runtime scoped and must be bound to host boot_id; old-boot IDs cannot be reused as current evidence.
- JobRemoved result, unit ActiveState/SubState and cgroup emptiness are distinct observations; none alone substitutes for the full exit/no-late-start proof.

This is authoritative documentation research, not a live systemd integration test. It sharpens the contract but does not close P0-03/P0-04. A systemd 250+ failure-injection harness remains mandatory.

## 13. Challenge review — Linux launch/release/exit proof addendum

A focused challenge addendum was added at [D-05 Linux Launch, Release and Exit-Proof Addendum](./d05-linux-launch-release-exit-proof-addendum.md). It does not mark any P0 closed. It converts the remaining ambiguity into explicit, testable contract obligations.

### P0-02 — Launch idempotency across lost D-Bus replies

The addendum now makes the safety rule explicit: once a StartTransientUnit request may have crossed the D-Bus send boundary, a lost reply is an ambiguous side effect. The broker may adopt a matching job/invocation, but if neither can be proven it must quarantine; an empty ListJobs result or missing unit is not proof that the original call was never accepted. Blind retry is prohibited.

It also makes the sole-broker privilege boundary mandatory: Harness cannot access systemd/D-Bus/cgroup controls, and no ordinary competing actor may create or replace units in the reserved namespace.

**Disposition: DESIGN CONSTRAINTS CLARIFIED; P0 remains OPEN pending D-10 implementation and systemd >=250 failure injection.**

### P0-03 — Start/release linearization

The addendum separates the durable release fence from systemd manager acceptance of a start job. It defines outcomes for pre-send, call-in-flight, waiting job, running job, running invocation, terminal invocation and unresolved evidence. A waiting job can only be canceled with exact-job correlation plus independent no-process/no-pending-start proof. A running job requires StopUnit for the exact unit; CancelJob is not a stop.

**Disposition: DECISION TABLE ADDED; P0 remains OPEN pending race injection at D-Bus send, JobNew, waiting→running, process spawn and StopUnit boundaries.**

### P0-04 — Exit proof after Supervisor restart

The addendum specifies an identity-bound evidence record and a conservative bracketed observation: exact unit/invocation properties, job snapshots, cgroup.events populated=0, then re-read unit/jobs/cgroup and require stable identity and no pending start/restart. It explicitly does not claim an atomic cross-interface snapshot. Unit retention through SEM acknowledgement is still an unresolved implementation proof obligation; CollectMode/RemainAfterExit alone must not be assumed sufficient.

**Disposition: EVIDENCE PROTOCOL SPECIFIED AS A CHALLENGE; P0 remains OPEN pending proof of bracket semantics, unit retention/GC behavior and restart failure injection.**

### Overall

No Linux integration harness or runtime code was added in this documentation-only step. D-05 remains **CHANGES REQUIRED — NOT READY FOR RATIFICATION OR DEVELOPMENT**. P0-01 remains Draft-contract closed against the pinned AI-PM source revision and must be rechecked immediately before ratification. D-04 schema cross-reference and D-03 operator-resolution acceptance remain separate gates.


## 14. D-05 ↔ D-04 durable-event cross-check

A branch-level review of `runner-sem-v1.schema.yaml`, `RUNNER-SEM-WSS-PROTOCOL-DRAFT.md`, the D-05 event model and the contract validators found:

- The schema currently requires `journal_id + event_sequence` for seven durable Runner message types: `execution.delivery_received`, `harness.starting`, `harness.started`, `harness.start_failed`, `harness.process_exited`, `execution.release_applied` and `runner.admission.changed`.
- The WSS narrative states that durable Runner observations use the `runner_id + journal_id` stream and that transport `message_sequence` is not a substitute. The seven-branch list is now pinned in `validate_sem_contracts.py`; payload fixtures now reject missing `journal_id` and missing `event_sequence` independently for each durable message.
- Replaceable heartbeat/health/resource snapshots remain outside the durable event stream. The schema/validator must be updated together if a new message becomes state-changing or replayable.

### P1 — Exit evidence reference semantics are not yet frozen

The new D-05 Linux proof addendum defines a complete local evidence record (boot, launch, unit, invocation, cgroup, job snapshots, unit state, exit status and observation sequence). The current Runner WSS `HarnessProcessExited` schema carries the key correlation fields and an `evidence_id`, but it does not carry the complete bracket observations or define a separate evidence-fetch/replay resource.

This is not automatically a defect if the contract intentionally treats the authenticated Runner Supervisor as the authority and `evidence_id` as an opaque audit reference into its durable journal. However, D-04 must explicitly choose and define that model: evidence retention duration, replay/snapshot behavior, what SEM persists, and what happens when SEM asks for an evidence_id that Runner can no longer serve. If SEM is expected to independently validate the bracket, the wire schema needs a structured evidence summary or a defined authenticated evidence retrieval operation.

**Disposition: P1 OPEN — do not silently assume that an evidence_id is self-describing or fetchable.**

The added validator checks schema branch parity and required journal cursor fields; it does not prove the semantics of event production, replay persistence or evidence retention. Latest CI is required to validate the new checks.
