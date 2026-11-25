# Runner Host Isolation and Permanent-Loss Recovery — Design Draft

- Status: **Proposed safety design / review required**.
- Decision ID: SEM-D-03.
- Scope: Runner disconnect, host failure, process containment, positive exit evidence, host fencing and safe reassignment.
- Authority: Runner Supervisor owns local process facts; SEM owns binding/resource quarantine; AI-PM owns business attempt/grant and retry decisions.
- This document does not authorize implementation or automatic failover.

## 1. Safety invariant

A second Harness must not be allowed to perform side effects for the same authorized business attempt while an older Harness may still be alive.

The following are **not** proof of process exit or host isolation:
- WSS disconnect or missed heartbeat;
- expired session, binding or business authorization;
- timeout or repeated connection failures;
- process-list absence reported without trusted host/process identity;
- workspace/worktree deletion or missing runtime files;
- command receipt, stop request or Harness self-report;
- MCP grant revocation;
- SEM process state inferred from stale cached observations.

When proof is unavailable, the state remains `infrastructure_uncertain`, capacity remains quarantined and automatic reassignment is prohibited.

## 2. Per-execution process containment

Runner Supervisor should launch each Harness execution in an independently identifiable OS containment unit:
- Linux: dedicated cgroup v2 subtree and process group, optionally one container per execution;
- Windows: dedicated Job Object, optionally one container per execution;
- other platforms: equivalent OS process-tree containment with reliable wait/termination semantics.

The containment unit is the primary stop/observe boundary. A process PID alone is insufficient. Persist before/at launch:
- runner_id, key_version, supervisor_instance_id and Runner boot_id;
- execution_id, binding_epoch, delivery_id and release_id when present;
- containment_unit_id (container ID / cgroup path / Job Object identity);
- process PID plus OS process-start identity;
- Harness profile/version, launch timestamp and parent/supervisor identity;
- durable event sequence and last acknowledged event ID.

Supervisor must not start a Harness until the process registry record and containment unit ownership are durably established. If the Supervisor crashes between record creation and process spawn, recovery reconciles the record and OS runtime before any new launch.

## 3. Positive local process-exit evidence

A trusted `harness.process_exited` observation requires:
1. matching runner_id, execution_id and binding_epoch;
2. matching Runner boot_id and Supervisor instance lineage;
3. exact containment_unit_id and process-start identity;
4. Supervisor-observed exit/reap of the exact child or authoritative runtime confirmation that the containment unit is stopped and contains no remaining process;
5. unique observation_id, event_id and monotonic event_sequence;
6. authenticated Runner session and evidence provenance.

For a container runtime, a stop command ACK is not enough. The Supervisor must query the runtime and observe the exact container ID in a terminal stopped/dead state, with no restart policy that could restart it. For cgroup/Job Object, Supervisor must confirm the group is empty and the owned handle/runtime has reached the terminal state.

A host reboot changes boot_id. A rebooted Runner must reconcile the previous boot's process registry against the host runtime before reporting prior processes exited. If the old boot cannot be reconciled, the old execution remains uncertain until host-level isolation is established.

## 4. Disconnect state machine

When WSS disconnects before positive process exit:
1. SEM marks the execution `infrastructure_uncertain`.
2. SEM retains the old binding_epoch and resource reservation as quarantined.
3. SEM rejects new delivery to that execution and does not select a second Runner for the same attempt.
4. AI-PM revokes or suspends the delegated grant if policy requires preventing future MCP business operations. Revocation is not process-exit evidence.
5. On reconnect, Runner authenticates with its enrolled key and replays its durable event spool in event_sequence order.
6. SEM reconciles process registry, containment state and the last acknowledged sequence. Gaps or conflicting observations remain uncertain and are escalated.

No automatic transition from uncertain to released occurs solely because a timeout elapsed.

## 5. Permanent Runner host loss: isolation profiles

A permanently unreachable Runner is not the same as a terminated process. Safe reassignment requires an isolation action independent of the lost Runner process.

### Profile A — Managed VM / cloud instance (recommended for automatic recovery)

Prerequisites:
- Runner host is a dedicated VM/instance per Runner identity or per independently fenceable Runner pool.
- AI-PM/SEM deployment has a separately authenticated management-plane client with least privilege to power off the exact instance.
- Instance identity is immutably bound to runner_id in enrollment/operations records.

Procedure:
1. Mark the execution and Runner `infrastructure_uncertain`; quarantine reservation.
2. Ask the independent infrastructure control plane to stop/power off the exact instance.
3. Poll the provider's authoritative instance state until it reports a terminal powered-off/deallocated state.
4. If the provider reports unknown, stopping, failed or API timeout, remain quarantined.
5. Record provider, instance ID, request ID, operation ID, observed terminal state, timestamp and signed/API response evidence.
6. Only after confirmed power-off may SEM mark the old host binding fenced. Do not reuse the old runner_id/key until host rebuild/re-enrollment.
7. AI-PM invalidates the old authorization_generation/grant and decides whether to create a new business attempt or authorize a replacement execution according to business policy.
8. A replacement execution uses a new execution_id and a new Runner binding. No old process can run because the entire old VM is confirmed off.

Power-off confirmation proves the old VM cannot currently execute. It does not prove external side effects already sent to Git, package registries or third-party services have been rolled back.

### Profile B — Bare-metal host with independent BMC/IPMI

Same safety requirements as Profile A, using an independently reachable BMC/IPMI or hardware management plane:
- BMC identity must be registered separately from Runner credentials.
- The management action must power off the exact host, not merely restart Runner service or stop Docker.
- A positive power state must be read back from the BMC after the command.
- BMC unavailability, ambiguous state or conflicting telemetry means quarantine remains.

A BMC command ACK alone is not proof; a subsequent authoritative power-state observation is required.

### Profile C — Bare metal / unmanaged host without independent management

There is no safe automatic remote fencing procedure when the only control path is the lost Runner itself.

Required behavior:
- keep execution and resource reservation quarantined;
- open an operator intervention with the exact Runner/host/execution identity and last-known evidence;
- require an authorized operator to physically verify power-off/disconnection or restore host management access;
- record operator identity, verification method, evidence and timestamp;
- only then permit the AI-PM business decision and SEM binding transition.

Do not invent a software timeout that converts an unmanaged host to safely dead.

## 6. Reassignment and fencing semantics

- AI-PM `authorization_generation` fences old Harness MCP business calls.
- SEM `binding_epoch` fences stale Runner delivery, observation and release messages.
- Runner Supervisor containment/process identity proves local process termination.
- Independent host management evidence fences a host that cannot report its own process state.

All four solve different problems.

After positive local exit or independently verified host power-off:
1. SEM records the old process/binding as fenced and releases the quarantined capacity according to cleanup policy.
2. AI-PM invalidates the previous delegated grant.
3. AI-PM decides whether this is a new business attempt or a new infrastructure binding for the existing attempt.
4. A replacement execution receives a new execution_id; a new Runner binding receives a new binding_epoch.
5. No old grant or stale Runner event can affect the replacement.

A risk acceptance or human decision to proceed without proof is not process-exit evidence. If the product ever supports such a mode, it must be a separate explicit unsafe-override design with unique successor identity, external side-effect warning and non-reversible audit. It must not be called safe failover.

## 7. Release/start race

Runner Supervisor maintains a durable local stop fence:
- release is persisted before applying stop;
- if release arrives before process spawn, the Supervisor marks the execution released/stopped and rejects any later start for that execution_id + binding_epoch;
- if release arrives during launch, it is serialized against process registration and prevents a late untracked process;
- duplicate release_id returns the original outcome;
- a release for an older binding_epoch cannot stop a newer process;
- natural exit before release is recorded; subsequent release converges idempotently;
- cleanup failure or uncertain containment retains quarantine.

The local process registry and stop fence must survive Supervisor restart and Runner reboot.

## 8. Resource reservation semantics

- SEM reserves capacity when binding is established.
- Reservation remains active while process state is running or uncertain.
- WSS disconnect, stale telemetry, MCP grant revocation and stop-command ACK do not release it.
- Release occurs only after positive local process exit or independent host fence, plus completion of required cleanup.
- If the Runner host is permanently fenced, old capacity is not automatically assumed reusable until the old host is rebuilt/re-enrolled and reports fresh capacity.

## 9. Operator runbook requirements

The operational contract must provide:
- Runner identity, host identity, boot ID, execution_id, binding_epoch and process containment ID;
- last heartbeat, last event sequence and last durable ACK;
- exact independent host-management operation and current power state;
- who is authorized to trigger host power-off and who verifies it;
- quarantine age alerts and escalation policy;
- evidence retention and audit requirements;
- process for reconciling external side effects (Git pushes, API calls, package publishing) after uncertain execution.

## 10. Acceptance tests

1. WSS loss with a live Harness leaves the execution uncertain and capacity reserved.
2. Heartbeat expiry and MCP grant revocation do not release the reservation.
3. Supervisor restart recovers the process registry and stop fence.
4. PID reuse cannot match the old process identity.
5. Runner reboot cannot claim prior processes exited without boot/runtime reconciliation.
6. Release before process spawn prevents a late launch.
7. Release during process start is serialized and cannot leak an untracked process.
8. Stale binding_epoch release cannot stop a newer process.
9. Container stop ACK without terminal runtime observation is not accepted as process exit.
10. Managed VM API timeout or ambiguous power state keeps quarantine.
11. Confirmed VM power-off records independent host-fencing evidence.
12. Bare-metal without BMC/independent management cannot auto-failover.
13. Duplicate/out-of-order process events are idempotently reconciled.
14. External Git/API side effects are not represented as rolled back by host power-off.
15. Capacity is released only after process/host fence and cleanup policy succeed.

## 11. Open deployment decision

The user has specified an independent Docker server for Worker/Runner infrastructure, but the host-management profile is not yet specified:
- dedicated cloud VM/managed instance with power-control API;
- bare-metal with BMC/IPMI;
- unmanaged bare-metal.

The deployment document must select the actual profile. Until then, automatic permanent-host-loss recovery cannot be claimed. The safe default is Profile C: quarantine and operator intervention.

## 12. Status

This is a safety design draft. The per-execution containment unit, host-management integration, signed evidence format and operator authorization model must be finalized with the deployment topology before implementation. No code, migration or automatic failover is authorized.
