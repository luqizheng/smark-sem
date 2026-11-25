# Linux systemd Integration and Failure-Injection Test Plan

- Status: **DRAFT / REQUIRED BEFORE D-03/D-05 RATIFICATION**
- Scope: Linux-only V1 Runner Supervisor, systemd transient-service launch, cgroup v2 containment, durable Runner journal, WSS replay/ACK and permanent-host-loss disposition.
- Related contracts:
  - [Runner Host Isolation and Permanent-Loss Recovery](../runner-host-isolation-and-permanent-loss-recovery-draft.md)
  - [Lifecycle State Machines and Crash Consistency](./lifecycle-state-machines-and-crash-consistency-draft.md)
  - [D-05 Linux Launch, Release and Exit-Proof Addendum](./d05-linux-launch-release-exit-proof-addendum.md)
  - [Runner–SEM WSS Protocol](../../protocol/RUNNER-SEM-WSS-PROTOCOL-DRAFT.md)
- This plan defines test obligations only. It authorizes no production implementation, schema migration, deployment change or merge.

## 1. Purpose and exit criteria

The purpose is to produce executable evidence for the Linux V1 process-owner and crash-consistency claims. Passing JSON Schema, OpenAPI, crypto-vector or fixture CI is necessary but does not prove OS process behavior.

D-03/D-05 may be considered for ratification only when:

1. Every applicable D05 acceptance case is mapped to one or more executable Linux integration tests or explicitly marked as a non-runtime protocol/unit test.
2. The minimum supported systemd version and supported distribution profile have been exercised on a real systemd host using unified cgroup v2.
3. StartTransientUnit lost-reply, Supervisor crash, Release race, process-exit proof, unit retention/GC, replay/ACK and disk-failure paths pass deterministic failure injection.
4. The Harness cannot control systemd, the system bus, cgroup hierarchy or the host launch broker, and cannot escape its execution containment.
5. Test artifacts prove identity correlation and durable evidence; a green test summary without raw evidence is insufficient.
6. Any unresolved/ambiguous outcome fails closed to `local_uncertain` / `infrastructure_uncertain` and retained quarantine, never a guessed retry or release.

## 2. Test environment profile

### 2.1 Required host

Use a disposable Linux VM or dedicated test host with:

- systemd **250 or later**, with the exact systemd build/version recorded per run;
- unified cgroup v2 mounted and active (`/sys/fs/cgroup`);
- a functioning system bus and systemd Manager D-Bus API;
- host-managed Runner Supervisor service;
- separate unprivileged Harness UID/GID;
- a reserved SEM transient-unit namespace and a dedicated test slice;
- sufficient privilege for the test controller to inspect systemd/cgroups and inject host-level failures;
- no production credentials, production Runner identity, production SEM endpoint or real external side effects.

A container nested inside an ordinary CI container is not an acceptable substitute for the host profile unless it demonstrably exposes the same systemd manager, cgroup v2 ownership and failure semantics. A fake systemd implementation is useful for unit tests only, never for P0 closure.

### 2.2 CI topology

- Fast protocol/schema/crypto tests may run on ordinary GitHub-hosted CI.
- Privileged systemd/cgroup tests run on an isolated, disposable Linux integration host or an explicitly managed internal self-hosted runner.
- The integration host must be rebuilt from a known image or reverted to a known snapshot after each destructive test group.
- Tests must not run on production SEM or production Runner hosts.
- The test controller, fake SEM endpoint and test Runner Supervisor communicate over an isolated test network. The fake SEM must implement the versioned WSS contract and durable ACK behavior, not bypass the production message path.
- A test-only D-Bus fault proxy or broker injection seam may drop/delay replies and kill the Supervisor at deterministic boundaries. The seam must not alter the production state machine or manufacture systemd success.

### 2.3 Test Harness process

The test Harness helper must support deterministic modes:

- record a unique `launch_id` and append exactly one start marker to a durable test ledger;
- remain alive behind a synchronization barrier;
- fork child and grandchild processes and report their identities;
- ignore graceful termination or delay exit when a test requires force-stop;
- attempt prohibited systemd/D-Bus/cgroup operations and report access-denied results;
- attempt cgroup migration/delegation/escape and create late descendants;
- exit with a selected code or signal;
- create a bounded, local-only side-effect marker to detect duplicate starts.

The helper must never perform real Git pushes, API mutations, package publishing or other external side effects.

## 3. Observability and evidence artifacts

Each test run records:

- test case ID and source acceptance-case IDs;
- kernel release, distribution image, systemd version, cgroup mode and host boot_id;
- Runner ID, Supervisor instance ID, journal_id and journal sequence;
- execution_id, delivery_id, binding_epoch, launch_id, containment_id and unit name;
- D-Bus method request/result, JobNew/JobRemoved observations, job object paths/IDs and timestamps;
- systemd unit properties including InvocationID, ControlGroup, ActiveState, SubState, Result and ExecMain status where available;
- both cgroup.events observations and their timestamps;
- raw Supervisor journal records and fsync/commit boundaries;
- WSS messages, durable journal cursor, replay frames and exact ACK payloads;
- expected disposition, observed disposition and assertion results;
- evidence_id, evidence_schema_version and evidence_digest for process-exit evidence.

Artifacts must redact secrets and prompt/body data. Preserve enough metadata to independently reconstruct event ordering and identity correlation. Test artifacts are not workspace backups.

## 4. Deterministic fault-injection controls

The test controller must be able to pause, crash or fail the Supervisor at each of these named boundaries:

1. before launch-intent journal commit;
2. after launch-intent fsync and before D-Bus send;
3. after D-Bus request send and before method reply;
4. after systemd accepts the job but before JobNew is observed by the broker;
5. after JobNew and before job identity is durably recorded;
6. while the job is waiting;
7. during waiting-to-running transition;
8. after process spawn but before invocation/process identity journal commit;
9. immediately before and after Release fence commit;
10. during CancelJob / StopUnit and before job result observation;
11. after process exit but before exit evidence journal commit;
12. after evidence commit but before WSS send;
13. after WSS send but before SEM durable persistence;
14. after SEM persistence but before durable ACK reaches Runner;
15. after durable ACK but before local evidence cleanup;
16. during unit GC, systemd manager restart, host reboot and journal disk-full/fsync failure.

Every injection must be reproducible by a test ID and deterministic barrier, not a sleep-only race.

## 5. Required test suites

### 5.1 Launch idempotency and ambiguous D-Bus outcomes

- Prove crash before D-Bus send permits one safe launch using the same immutable launch_id.
- Prove any crash after the request may have crossed the send boundary is reconciled by exact unit/job/invocation identity.
- Drop the D-Bus method reply after send; prove no second StartTransientUnit is issued while outcome is ambiguous.
- Return no matching ListJobs/GetUnit result after an ambiguous send; prove quarantine and operator reconciliation, not retry.
- Deliver JobNew while dropping the method reply; prove the existing exact job is adopted and only one Harness start marker exists.
- Pre-create a conflicting unit or invocation identity; prove integrity conflict and no adoption.
- Repeat the same delivery_id/launch_id and prove deduplication prevents a second process.

### 5.2 Start/Release race and linearization

Run deterministic schedules where Release wins:

- before Start intent is committed;
- after intent commit but before D-Bus send;
- while the D-Bus call is in flight;
- while the exact job is waiting;
- at the waiting-to-running transition;
- after systemd has accepted the job but before process spawn;
- immediately after process spawn;
- while the invocation is running;
- during StopUnit and after the stop job completes.

Assert that the durable release fence blocks all later start commands, in-flight starts are reconciled, waiting jobs are canceled only with exact correlation, running jobs are stopped using the exact unit, and no effective release ACK is emitted before the required no-start or positive-exit proof.

### 5.3 Process containment and hostile descendant behavior

- Verify the exact systemd unit properties on the minimum supported systemd version and every supported distribution profile.
- Verify Harness and descendants run under the unprivileged identity and cannot access system bus, systemd control sockets, Docker/container runtime sockets, broker journal or cgroup control files.
- Verify cgroup delegation is disabled and Harness cannot migrate itself or descendants outside the assigned cgroup.
- Verify KillMode=control-group and StopUnit terminate all descendants, including a grandchild that ignores graceful termination.
- Verify a late descendant cannot appear after the broker has committed terminal exit evidence.
- Verify an out-of-band actor cannot create/replace a unit in the reserved namespace; detected interference quarantines the execution.

### 5.4 Positive exit proof and Supervisor restart

- Capture normal code exit, signal exit and unknown numeric exit status while proving the exact cgroup is empty.
- Kill the Supervisor after the process exits but before the evidence journal commit; reconstruct containment proof from the durable process owner without inventing a numeric exit status.
- Kill the Supervisor after evidence journal commit but before WSS publication; replay the same immutable event.
- Mutate InvocationID, ControlGroup or boot_id between bracketed observations; reject the candidate proof.
- Change cgroup.events populated between reads or introduce a start/restart job between job snapshots; reject the candidate proof.
- Force systemd unit GC before SEM ACK; the test must fail unless the chosen durable retention strategy still reconstructs the exact invocation proof.
- Restart systemd manager and reboot the host; old job IDs are invalid outside their boot identity. Prior-host uncertainty follows the D-03 quarantine/manual disposition, not guessed exit.

### 5.5 Evidence digest, replay and durable ACK

- Generate the complete immutable evidence record and verify SHA-256 over RFC 8785 JCS bytes equals evidence_digest.
- Persist the record and digest before emitting harness.process_exited.
- Verify SEM stores the complete event envelope before ACK.
- Verify the ACK has disposition=durably_recorded and echoes the exact acknowledged_journal_id + acknowledged_event_sequence + acknowledged_message_id.
- Drop ACK and reconnect; Runner replays the same journal cursor, evidence_id, schema version, digest and payload.
- Change evidence payload or digest while reusing evidence_id/cursor; SEM detects integrity conflict.
- Prove Runner cannot delete/mutate raw evidence before exact durable ACK; after ACK, verify configured retention and disk-pressure policy.
- Verify local raw evidence expiry does not delete or mutate SEM's persisted event summary/digest.

### 5.6 Journal durability and storage failure

- Crash at every write-ahead journal boundary and verify recovery is deterministic.
- Inject fsync failure and disk-full conditions before launch intent, release fence, process-exit evidence and ACK state transitions.
- Prove no side effect or positive ACK is emitted before the required durable commit.
- Corrupt/truncate the journal and verify fail-closed quarantine; never reconstruct a guessed process-exited or no-start fact.
- Verify journal compaction/retention preserves launch tombstones, event cursors and evidence records still awaiting ACK.

### 5.7 D-03 permanent host-loss manual disposition

- Unauthorized identity and AI-PM agent cannot invoke `runner.quarantine.resolve`.
- Current authenticated Runner session or successful normal reconciliation blocks manual resolution.
- `inspection_inconclusive` is append-only audited and retains all quarantine/reservations.
- `host_physically_isolated` requires exact affected identities, operator attestation, timestamp and non-empty reason.
- Accepted physical-isolation disposition closes only listed old execution reservations; old host capacity remains unschedulable.
- Fresh re-enrollment creates a new trusted Runner identity; old Runner identity, boot lineage and binding epochs remain fenced.
- Repeated resolution_id with identical content is idempotent; changed content is an audit conflict.
- Manual disposition never emits process-exited evidence or mutates AI-PM Task/Run/Outcome.

## 6. Mapping to D-05 acceptance cases

The test implementation must maintain a machine-readable mapping from every D05-01–D05-102 case to:

- test suite and executable test ID;
- test layer: schema/unit, SEM integration, Runner journal integration, Linux systemd integration or operational/manual test;
- required host profile and privileges;
- fault-injection point;
- expected state/evidence/ACK;
- artifact path and pass/fail result.

A case may be covered by more than one test. A case may not be silently marked covered by a prose-only assertion. Non-runtime cases (for example, schema shape) must point to the exact CI test that validates them.

## 7. Ratification gates

| Gate | Required evidence | Failure disposition |
|---|---|---|
| Linux host profile | systemd >=250 + unified cgroup v2, version/build recorded | Unsupported profile; no V1 dispatch |
| Launch idempotency | lost-reply and crash-window tests; one start marker only | local_uncertain + quarantine; no retry |
| Start/Release | deterministic race matrix | no effective release ACK; quarantine |
| Containment | privilege and hostile-descendant tests | quarantine; do not claim safe stop |
| Exit proof | invocation-bound systemd/cgroup evidence after Supervisor restart | no process-exited event; reservation retained |
| Evidence journal | fsync, digest, replay and ACK gating | no event ACK; retain raw evidence |
| Unit retention | successful/failed/forced-stop and GC tests through SEM ACK | P0-04 remains open |
| Host loss | manual disposition authorization/audit/no-capacity-reuse tests | quarantine remains |
| Full traceability | D05-01–D05-102 mapping with raw artifacts | no ratification |

## 8. Explicit non-goals

- No test authorizes production deployment or implementation by itself.
- No GitHub-hosted container test substitutes for real host systemd/cgroup behavior.
- No test treats WSS disconnect, heartbeat expiry, timeout, PID absence, CancelJob ACK or StopUnit ACK as process-exit proof.
- No test interprets process exit as AI-PM business success/failure.
- No test represents external Git/API side effects as rolled back.
- No workspace backup, cloud/BMC power API, automatic host-loss failover or second evidence transport is introduced.

## 9. Readiness

This plan is the required test design for D-03/D-05 Linux process lifecycle claims. It is not evidence that tests have been implemented or passed. D-05 remains **CHANGES REQUIRED — NOT READY FOR RATIFICATION OR DEVELOPMENT** until the executable harness, supported host profile and failure-injection artifacts satisfy the gates above.
