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
3. Close P0-02 with a concrete Linux and Windows process creation/containment/recovery design.
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
