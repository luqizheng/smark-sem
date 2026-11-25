# D-05 Linux systemd Launch, Release and Exit-Evidence Contract — Challenge Addendum

- Status: **DRAFT / CHALLENGE — NOT RATIFIED**
- Parent: [Lifecycle State Machines and Crash Consistency Draft](./lifecycle-state-machines-and-crash-consistency-draft.md)
- Audit: [D-05 Independent Architecture Audit](./d05-independent-architecture-audit.md)
- Scope: resolve the remaining design ambiguity in P0-02 (launch idempotency), P0-03 (start/release race) and P0-04 (post-Supervisor-restart process-exit proof).
- This addendum is a documentation proposal only. It authorizes no runtime implementation, migration, deployment change, or merge.
- V1 host profile remains Linux + systemd >=250 + unified cgroup v2. Windows, non-systemd Linux and Runner containers without a trusted host-side broker remain unsupported.

## 1. Safety conclusion

The current D-05 draft has selected the right process owner (the host systemd manager) and the right containment primitive (one systemd transient service/cgroup v2 subtree per binding). It has **not** yet proved exactly-once process creation or a complete exit-proof snapshot.

Three distinctions are mandatory:

1. A D-Bus method call being sent is not the same fact as systemd accepting a start job.
2. A start job being accepted/queued is not the same fact as ExecStart having spawned the process.
3. A successful stop-job result is not the same fact as the exact invocation having no remaining process or descendant.

A lost D-Bus reply is an ambiguous side effect. Absence from one later ListJobs response, or absence of a unit from GetUnit, MUST NOT be interpreted as proof that the original call was never accepted. If the exact invocation cannot be positively identified, the result is quarantine, not retry.

## 2. Authority and privilege boundary

The Runner Supervisor's host-side launch broker is the sole normal actor permitted to create, stop, reset or remove transient units in the reserved SEM unit namespace.

- Harness and all descendants run as an unprivileged identity.
- Harness receives no system-bus access, systemd/Docker control socket, cgroup delegation, or write access to the broker journal.
- The broker validates the exact tuple `runner_id + execution_id + binding_epoch + delivery_id + launch_id` on every command.
- The broker owns a durable per-launch sequencer and a durable launch tombstone. It serializes start, release, reconciliation and cleanup for one launch identity.
- An administrator's out-of-band systemd mutation is a break-glass event. The broker detects any unit/job/invocation mismatch and quarantines the execution; it does not silently adopt an administrator-created replacement.
- Unit names and launch IDs are never reused, including after unit garbage collection or host reboot. A new business attempt receives a new execution and launch identity.

This privilege boundary is a prerequisite for interpreting a stable unit identity. If any other ordinary service can create or replace units in the reserved namespace, the broker cannot safely infer that a queried unit belongs to its launch.

## 3. Durable launch protocol

### 3.1 Before the D-Bus boundary

In one durable local journal transaction, the broker records:

- launch_id, immutable unit name, execution_id, delivery_id and binding_epoch;
- host boot_id and broker journal identity;
- canonical launch specification digest;
- state = `start_intent`;
- monotonically increasing local command sequence.

The journal commit must be durable before the broker invokes StartTransientUnit. The unit name is derived deterministically from the immutable launch identity and is never reused.

### 3.2 StartTransientUnit invocation

- Subscribe to Manager JobNew and JobRemoved signals before issuing StartTransientUnit.
- Use the reserved unit name and a non-replacing job mode. Never use a mode that replaces or merges a conflicting unit/job.
- Persist the returned job object path, job ID, boot_id and observed JobNew correlation before reporting a start result.
- Persist the exact requested unit properties and their digest. The approved property set remains the one in D-05 §3.6; any change requires review.
- The broker must not issue a second StartTransientUnit for the same launch_id while the first call may have crossed the D-Bus send boundary.

### 3.3 Lost reply / ambiguous call

After a request may have been sent but its reply is lost:

1. Keep the launch in `local_uncertain`; keep its SEM reservation/quarantine.
2. Query the exact unit identity, the current manager job list, and any persisted JobNew/JobRemoved observations.
3. If an exact matching job is found, persist/adopt that job and continue its state machine.
4. If an exact matching invocation is found, adopt that invocation; do not issue another start.
5. If a conflicting unit, invocation, job, boot identity or launch digest is found, quarantine and raise an integrity incident.
6. If neither a matching job nor a matching invocation is found, the outcome remains **unknown**. The broker MUST NOT infer that the call was not accepted and MUST NOT retry StartTransientUnit. Operator reconciliation is required unless a separately verified systemd/bus guarantee proves the request was never delivered.

Only a failure proven to occur before the D-Bus request could have been sent permits retry without reconciliation. A timeout, connection reset, missing reply or empty ListJobs result is not such proof.

### 3.4 Launch states exposed to the sequencer

| State | Evidence | Allowed action |
|---|---|---|
| `intent_durable` | Local intent committed; D-Bus call not yet sent | Start may proceed unless release fence wins first |
| `call_in_flight` | D-Bus request may have crossed send boundary | No second start; release waits for reconciliation |
| `job_waiting` | Exact job identity and waiting state observed | Start is not yet process-spawn proof; release may cancel exact job |
| `job_running` | Exact job is running | CancelJob is not a stop; release must StopUnit exact unit |
| `invocation_running` | Exact InvocationID + unit + cgroup observed | Process may be running; stop exact invocation |
| `invocation_terminal` | Exact invocation terminal evidence observed | Capture exit evidence; no new start |
| `launch_unknown` | No authoritative resolution | Quarantine; no retry/rebind |

The broker must retain the raw D-Bus job result and the unit/invocation observations separately. They are different evidence types.

## 4. Start/release serialization and linearization

### 4.1 One sequencer

For each `runner_id + execution_id + binding_epoch + launch_id`, exactly one durable sequencer serializes:

- start intent;
- D-Bus StartTransientUnit;
- job observation and invocation adoption;
- release fence;
- CancelJob / StopUnit;
- exit proof;
- cleanup and tombstone acknowledgement.

The sequencer's journal lock alone is not sufficient if a second process can bypass it and call systemd. The sole-broker privilege boundary in §2 is mandatory.

### 4.2 Linearization points

The business-visible linearization point for **start accepted by the OS manager** is the systemd manager's acceptance of the exact start job, evidenced by the correlated JobNew/job object. It is not the local intent commit, D-Bus send, or eventual process-start event.

The **release fence** linearizes when the sequencer durably commits the release ID and rejects all later start commands for that binding. This prevents future requests from entering the D-Bus boundary; it does not retroactively cancel an earlier in-flight call.

### 4.3 Release decision table

| Observed state when release wins sequencer | Required action | Effective no-start / stopped ACK |
|---|---|---|
| `intent_durable`, D-Bus call provably not sent | Commit release fence; suppress StartTransientUnit | Allowed after durable fence |
| `call_in_flight` | Commit release fence; reconcile exact unit/job; do not ACK yet | Forbidden until resolved |
| Exact start job is `waiting` | Cancel that exact job; observe matching JobRemoved; verify no matching invocation/process, no pending start job, and cgroup empty | Allowed only after all checks and durable evidence |
| Exact start job is `running` | CancelJob is ineffective; issue StopUnit for exact unit; observe stop job and verify exact invocation terminal + cgroup empty | Allowed only after all checks and durable evidence |
| Exact invocation is running | Stop exact unit; verify exact invocation terminal + cgroup empty | Allowed only after all checks and durable evidence |
| Exact invocation is terminal | Capture and persist exit proof; no new start | Allowed after exit proof and durable fence |
| Unit/job/invocation evidence is missing or contradictory after ambiguous call | Keep `local_uncertain`; quarantine; operator resolution | Forbidden |

A CancelJob response, JobRemoved result, StopUnit response, WSS ACK, or stop-fence journal record alone is never sufficient to claim process exit or no-late-start.

## 5. Positive process-exit evidence contract

### 5.1 Required identity binding

Every exit observation must bind all of the following in one durable evidence record:

- host boot_id;
- immutable launch_id and unit name;
- systemd unit object path;
- exact InvocationID;
- exact ControlGroup path;
- execution_id, delivery_id and binding_epoch;
- relevant start/stop job identities and their terminal results;
- unit ActiveState, SubState and Result;
- ExecMainCode and ExecMainStatus when available;
- cgroup v2 `cgroup.events` populated value;
- observation timestamps and broker journal sequence.

A PID or process name is supplementary diagnostic data only.

### 5.2 Evidence collection protocol

The broker uses a conservative bracketed observation, not an assumed atomic cross-interface snapshot:

1. Under the per-launch sequencer, verify the current boot_id and immutable launch tombstone.
2. Query the exact unit and capture InvocationID, ControlGroup, ActiveState, SubState, Result and execution status properties.
3. Query outstanding manager jobs and reject any pending start/restart job for the unit.
4. Read `cgroup.events` for the exact ControlGroup and require `populated 0`.
5. Re-query the exact unit and outstanding jobs.
6. Require the InvocationID, ControlGroup and terminal state to match the first observation; require no pending start/restart job in the second job snapshot.
7. Re-read cgroup.events and require `populated 0` again.
8. Durably commit the complete evidence record before emitting `harness.process_exited` or acknowledging effective release.

If any value changes, the unit disappears before its identity can be revalidated, a job appears, cgroup state is unreadable, or the invocation cannot be correlated, discard the candidate proof and remain uncertain.

This protocol is deliberately conservative. It still requires a real systemd >=250 integration test to demonstrate that the chosen unit properties, job lifecycle and cgroup observation semantics make the bracket meaningful under concurrent process exit, unit GC and manager activity.

### 5.3 Exit status versus exit proof

- Positive process-exit proof and numeric exit status are separate fields.
- If the containment is proven empty but the Supervisor lost the wait status, report `exit_status=unknown`; do not invent an exit code.
- A non-zero exit, signal termination or unknown exit status is an infrastructure observation, not a Task/Run business decision.
- Empty cgroup is not proof that external side effects were rolled back.
- If exact invocation identity or no-late-descendant guarantees cannot be established, no process-exited event is emitted and capacity remains quarantined.

### 5.4 Unit retention and garbage collection

The selected `CollectMode=inactive` and `RemainAfterExit=yes` settings must be tested for both successful and failed executions and for StopUnit-driven termination. The broker must not assume that a unit remains queryable merely because a prior query returned it.

Before the implementation can claim P0-04 closed, it must specify and prove one durable retention strategy that survives Supervisor process restart until both the local journal and SEM reconciliation have acknowledged the terminal evidence. Candidate mechanisms (such as a manager-held unit reference, a retained terminal unit state, or a separately durable systemd journal record correlated to InvocationID) are not interchangeable and must be validated on the minimum supported systemd version. If the only unit evidence can be garbage-collected before reconciliation, the design is not acceptable.

## 6. Required failure-injection acceptance cases

Add these cases to D-05's acceptance matrix and implement them in the D-10 Linux integration harness before ratification:

| ID | Injection point / condition | Required result |
|---|---|---|
| D05-LNX-01 | Crash after journal intent commit, before D-Bus send | Safe single start after restart; no duplicate |
| D05-LNX-02 | Crash after D-Bus send, before method reply | Query exact unit/jobs; if unresolved, quarantine; never blind retry |
| D05-LNX-03 | JobNew arrives but method reply is lost | Adopt exact job; one invocation only |
| D05-LNX-04 | Job waiting while release arrives | Cancel exact job; no effective ACK until JobRemoved + no invocation + no pending start + cgroup empty |
| D05-LNX-05 | Job becomes running immediately before release | Stop exact unit; CancelJob is not treated as stop |
| D05-LNX-06 | Release commits immediately before StartTransientUnit send | Start suppressed; no job created |
| D05-LNX-07 | StartTransientUnit is accepted but no JobNew is observed by broker | Reconcile exact unit/jobs; unresolved means quarantine |
| D05-LNX-08 | Unit name exists with a different InvocationID or launch digest | Integrity conflict; no adoption or mutation |
| D05-LNX-09 | Harness attempts systemd/D-Bus/cgroup escape | Access denied; quarantine if containment integrity cannot be proven |
| D05-LNX-10 | Supervisor crashes after process exits but before evidence journal commit | Reconstruct proof from durable owner; exit code may be unknown |
| D05-LNX-11 | cgroup populated changes between bracketed reads | Reject proof; remain uncertain |
| D05-LNX-12 | Start/restart job appears between job snapshots | Reject proof; remain uncertain |
| D05-LNX-13 | Unit is garbage-collected before SEM acknowledges terminal evidence | Test fails; retention strategy must prevent loss |
| D05-LNX-14 | systemd manager restarts or host boot_id changes | Old job IDs are rejected; old host follows D-03 quarantine/manual disposition |
| D05-LNX-15 | Another process attempts to create/replace a unit in reserved namespace | Privilege boundary blocks it or broker quarantines on detected interference |
| D05-LNX-16 | Disk full or journal fsync failure before start/release/exit ACK | No ACK and no unsafe side effect; execution remains quarantined |

## 7. P0 disposition after this addendum

| Finding | Draft disposition | Evidence still required |
|---|---|---|
| P0-02 launch/create crash window | **Design constraints made explicit; not closed** | D-10 broker implementation, systemd >=250 failure injection, hostile descendant/escape tests |
| P0-03 start/release race | **Sequencer and release decision table specified; not closed** | Prove D-Bus job correlation and exact cancellation/StopUnit behavior under all race windows |
| P0-04 exit proof after Supervisor restart | **Conservative evidence protocol specified; not closed** | Prove bracketed D-Bus/cgroup evidence and durable terminal-unit retention through SEM acknowledgement |

P0-01 remains closed at Draft-contract level only, subject to rechecking the pinned AI-PM source revision immediately before ratification.

## 8. Explicit non-goals and no-shortcuts

- No automatic retry after an ambiguous StartTransientUnit call.
- No reassignment to another Runner based on WSS disconnect, timeout, missing PID or empty ListJobs alone.
- No claim that CancelJob or StopUnit ACK proves process exit.
- No claim that a systemd unit's inactive state alone proves the cgroup is empty.
- No claim that cgroup populated=0 alone proves the queried invocation was the intended launch.
- No automatic host-loss failover; D-03's user-confirmed visible alert + quarantine + on-site operator disposition remains authoritative.
- No workspace backup requirement.
- No runtime implementation is authorized by this addendum.

## 9. Readiness

This addendum makes the missing proof obligations explicit and supplies a conservative challenge contract. It does **not** claim that systemd's D-Bus and cgroup interfaces provide an atomic cross-interface snapshot. The Linux integration harness must validate the proposed bracket and retention strategy. Until that evidence exists, D-05 remains **CHANGES REQUIRED — NOT READY FOR RATIFICATION OR DEVELOPMENT**.
