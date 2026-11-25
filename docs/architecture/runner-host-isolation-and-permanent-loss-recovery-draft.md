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

## 5. Permanent Runner host loss: V1 manual on-site intervention

V1 runs inside the company's private network. The deployment does not require a cloud control plane, managed-VM power API, BMC/IPMI, remote power control or a second independent host-management network.

When SEM can no longer observe a Runner host, it cannot infer that the Harness process has exited. The required V1 behavior is:

1. Mark the Runner as `unreachable` and each affected execution as `infrastructure_uncertain`.
2. Retain the existing binding identity and capacity reservation in quarantine. Do not expire or silently release it.
3. Show a durable `unreachable` status in the SEM operator-facing status surface, including Runner/host identity, affected execution IDs, last heartbeat, last authenticated event sequence, last durable ACK, boot ID and last-known process/containment identity. V1 does not require email/SMS/IM alert integrations or a separate incident-management system.
4. Keep the unreachable status and quarantine visible until the host reconnects and reconciliation succeeds, or an authorized operator resolves the incident after the offline handling is complete.
5. The on-site handling itself is an offline operational procedure; SEM does not orchestrate physical inspection or remote power control. If the host cannot simply reconnect and reconcile, an authorized operator may use a minimal administrative resolution action to record the disposition, operator identity and timestamp.
6. If the host/process is still alive or its state remains ambiguous, quarantine remains. If the operator has physically handled the host and positively established it cannot continue running the old execution, the operator may record that disposition and authorize the controlled quarantine release/recovery workflow.
7. AI-PM independently decides whether to create a new business attempt or authorize a replacement execution. Any replacement uses a new execution identity and binding; stale authorization generations and binding epochs remain fenced.

The operator's action is a manual administrative disposition, not an automated process-exit observation. The minimum audit record is the affected Runner/execution, operator identity, disposition, timestamp and any short reason. V1 does not require an evidence-upload subsystem or a detailed incident-management workflow.

A status acknowledgement, elapsed timeout, WSS disconnect, heartbeat expiry, MCP grant revocation or stop-command ACK is not process-exit evidence and cannot by itself release capacity.

V1 does not promise automatic failover for a permanently unreachable host. It deliberately trades availability for safety: quarantine remains until on-site handling establishes an auditable disposition. External Git/API side effects are never represented as rolled back merely because a host was powered off.

## 6. Reassignment and fencing semantics

- AI-PM `authorization_generation` fences old Harness MCP business calls.
- SEM `binding_epoch` fences stale Runner delivery, observation and release messages.
- Runner Supervisor containment/process identity proves local process termination.
- For V1 permanent host loss, an auditable on-site operator verification of physical host isolation is the only host-level fencing evidence; SEM has no cloud/BMC remote-fencing integration.

All four solve different problems.
After positive local process-exit evidence or recorded on-site verification that the host is physically isolated:
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
- Release occurs only after positive local process-exit evidence or recorded on-site physical-isolation evidence, plus completion of required cleanup and an authorized operational disposition.
- If the Runner host is permanently fenced, old capacity is not automatically assumed reusable until the old host is rebuilt/re-enrolled and reports fresh capacity.

## 9. Operator runbook requirements

The operational contract must provide:
- Runner identity, host identity, boot ID, execution_id, binding_epoch and process containment ID;
- last heartbeat, last event sequence and last durable ACK;
- current unreachable/quarantine status and last-known host/process evidence;
- authorized operator identity, manual disposition, timestamp and short reason if manual quarantine resolution is required;
- who is authorized to record the on-site inspection and approve the subsequent administrative disposition;
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
9. Stop-command ACK without terminal runtime observation is not accepted as process exit.
10. Permanent host loss raises a visible alert and retains the execution and reservation in quarantine.
11. Alert acknowledgement or timeout alone cannot release quarantine.
12. Manual quarantine resolution, if required, is recorded with operator identity, disposition and timestamp.
13. Ambiguous physical condition keeps quarantine; no replacement execution is dispatched.
14. Manual quarantine release is allowed only after the offline handling has established that the old execution cannot continue; the administrative disposition is audited.
15. Duplicate/out-of-order process events are idempotently reconciled.
16. External Git/API side effects are not represented as rolled back by host isolation.
17. Capacity is released only after process/host fence and cleanup policy succeed.

## 11. V1 permanent-host-loss decision (user confirmed: 2026-11-25)

The user has confirmed that the Runner environment is inside the company network and that an on-site person can handle an unreachable host. V1 therefore selects **manual on-site intervention**:
- no cloud/VM power-control API;
- no BMC/IPMI integration;
- no remote power-off requirement;
- SEM must make the unreachable host and affected executions visibly discoverable to operators;
- quarantine and capacity reservation remain until an auditable on-site inspection and controlled disposition;
- no timeout-based automatic failover or release.

This is a resolved V1 deployment decision, not an open choice among host-management profiles. The minimum product requirement is a durable, visible unreachable status in the operator-facing SEM status surface and an auditable manual resolution action only when quarantine must be cleared without normal Runner reconnect/reconciliation. No separate alert-delivery integration is required in V1.

## 11.1 Minimal manual quarantine-resolution authority contract (V1)

The on-site host-loss decision is implemented as one explicit, audited administrative disposition; it is not a synthetic process-exit event and does not require a two-person approval workflow in V1.

### Authority and preconditions

- Only an authenticated SEM operator identity granted the dedicated `runner.quarantine.resolve` capability may submit the disposition. Ordinary Runner operators, project users and AI-PM business agents cannot invoke it.
- The action is available only for an existing unreachable/quarantined Runner host and its explicitly listed affected executions. A live current authenticated session or successful normal reconciliation blocks manual resolution; use normal reconciliation instead.
- The operator must attest that the offline on-site procedure has established the old host cannot continue the affected execution (for example, host power physically isolated or execution storage/compute removed from service). SEM does not claim to verify the physical fact remotely.
- If the operator cannot establish physical isolation, the only permitted disposition is `inspection_inconclusive`; quarantine and reservation remain unchanged.
- A manual disposition never sets `harness.process_exited`, never invents an exit status, never marks AI-PM Run/Task successful or failed, and never authorizes a replacement business attempt.

### Required disposition record

The durable audit record contains:

- immutable `resolution_id`;
- `runner_id`, host identity, last known `boot_id`;
- the exact affected `execution_id + binding_epoch + launch_id + containment_id` set;
- operator's authenticated subject ID and effective capability/role at action time;
- disposition: `host_physically_isolated` or `inspection_inconclusive`;
- operator attestation timestamp, server receipt timestamp and a non-empty reason;
- prior quarantine/reservation state and resulting administrative state;
- correlation to the triggering unreachable incident and audit/event sequence.

The audit record is append-only. Corrections are new superseding records; no in-place edit or deletion is allowed. No evidence-upload subsystem is required for V1.

### State effects

- `inspection_inconclusive`: record the attempt; keep host and all affected executions quarantined; retain reservations; dispatch remains blocked.
- `host_physically_isolated`: record the attestation and mark the old host identity `fenced_pending_recovery`. The affected execution reservations may be closed through the controlled administrative workflow, but the host's capacity is **not** returned to schedulable capacity. It remains unavailable until host rebuild/re-enrollment creates a fresh trusted host/Runner identity and fresh resource telemetry.
- AI-PM independently decides whether a new business attempt is appropriate. Any replacement uses a new execution identity and new binding/authorization generation.

V1 deliberately does not require a second approver, because the agreed deployment model relies on an on-site person and visible SEM quarantine. The dedicated capability, immutable audit record, explicit physical-isolation attestation and no-capacity-reuse rule are the compensating controls. A future organization policy may require dual control, but it is not a V1 protocol or release prerequisite.

### Additional acceptance cases

1. Unauthorized operator or AI-PM agent invokes manual resolution — reject without state change.
2. Current authenticated Runner session exists or normal reconciliation succeeds — manual resolution is unavailable.
3. Operator submits `inspection_inconclusive` — audit the attempt and retain all quarantine/reservations.
4. Operator submits `host_physically_isolated` without a non-empty reason or exact affected identity set — reject.
5. Accepted physical-isolation disposition closes only the listed old execution reservations; old host capacity remains unschedulable.
6. A replacement Runner registers as a fresh identity; old host/Runner identity and binding epochs remain fenced.
7. Repeated resolution_id with byte-equivalent content is idempotent; same ID with changed content is an audit conflict.
8. Manual resolution never emits process-exited evidence or mutates AI-PM Task/Run/Outcome.

## 12. Status

This is a safety design draft. The per-execution containment unit, on-site operator evidence record, administrative authorization model and Linux failure-injection proof must be finalized before implementation. No code, migration or automatic failover is authorized.

## 13. V1 Linux-only execution profile (user decision: 2026-11-25)

The user has approved **Linux-only Runner hosts for V1**. Windows and other operating systems are out of V1 scope. This narrows the supported OS matrix; it does not by itself approve implementation or close permanent-host-loss recovery.

### 13.1 Required host baseline
V1 Runner hosts MUST satisfy all of the following:

- Linux with unified **cgroup v2** enabled; hybrid/v1 cgroup mode is unsupported.
- systemd is PID 1 and exposes its system D-Bus manager API to the Runner Supervisor.
- The host's systemd manager, not a nested/unprivileged container runtime, owns each Harness execution unit.
- The Runner Supervisor runs as a host-managed systemd service with narrowly scoped permissions to create, inspect, stop and query only SEM-owned execution units.
- The Supervisor and Harness execution units use distinct Unix identities. Harness processes MUST NOT receive systemd manager privileges, cgroup delegation, writable cgroup control files, host Docker socket access, or permission to move themselves/descendants out of their assigned cgroup.
- No privileged Docker-in-Docker or privileged Harness container is part of the V1 baseline.
- If Runner is itself packaged in Docker, it is supported only when a separately installed host-side broker exposes narrowly scoped systemd/cgroup operations. A container with only its own namespace/cgroup view is not a supported process owner.

A host failing any baseline check is unsupported and MUST NOT become dispatch-ready.

### 13.2 Per-execution process owner
The V1 candidate process owner is a **systemd transient service unit backed by one dedicated cgroup v2 subtree per execution binding**.

- The stable unit identity is derived from immutable runner_id + execution_id + binding_epoch; exact unit-name encoding and collision limits are frozen in D-04/D-10.
- Before any OS launch call, the Supervisor durably commits launch_id, containment_id, delivery identity, binding epoch, expected unit identity and a start_intent journal record.
- The launch broker calls systemd Manager.StartTransientUnit for that exact transient service unit. The V1 candidate property set is Type=exec, ExitType=cgroup, RemainAfterExit=yes, CollectMode=inactive, Restart=no, KillMode=control-group, and no cgroup delegation, plus an explicit resource-control policy. ExitType=cgroup requires systemd 250 or later; V1 therefore sets systemd 250 as the minimum candidate version, subject to distro integration tests. The exact serialized D-Bus property values and distro support matrix are D-10 contract items.
- The broker never launches the Harness directly as an untracked child of the Supervisor.
- A repeated start for the same launch_id queries/adopts the same unit and invocation; it MUST NOT issue a second independent launch. A different payload or identity for an existing launch_id is a conflict.
- The unit's systemd invocation identity, cgroup path, host boot_id, main process identity and durable SEM execution tuple are recorded. PID alone is never an identity.
- RemainAfterExit=yes keeps a successfully completed unit active after its processes exit; CollectMode=inactive avoids the more aggressive inactive-or-failed collection mode. The Supervisor MUST NOT stop/reset-failed/otherwise release the unit before terminal evidence is durable locally and SEM has acknowledged/reconciled it. The durable Supervisor journal remains the authoritative tombstone even after the unit is eventually cleaned up; systemd unit retention is a live-reconciliation aid, not the sole durable history.

The systemd manager is the OS process owner across Runner Supervisor process restarts. The Supervisor's journal remains the durable command/idempotency ledger; systemd is the authoritative live process/containment observer. Neither replaces the other. The systemd transient-unit API documents that units may be released when no longer running/referenced or at reboot, so the design explicitly retains successful units with RemainAfterExit and keeps a separate durable Supervisor tombstone; no correctness claim depends on indefinite systemd unit retention.

### 13.3 Start/release linearization and crash recovery

- All start and release commands pass through one durable single-writer sequencer in the Supervisor.
- The sequencer commits a release fence before it can authorize any later launch for that binding.
- A launch broker request has a stable launch_id and stable systemd unit identity. The broker first resolves the exact unit with GetUnit and inspects its InvocationID, ControlGroup, ActiveState/SubState and outstanding jobs; it MUST NOT blindly repeat StartTransientUnit after an ambiguous reply. If the D-Bus request times out or the Supervisor crashes, recovery queries the same unit and outstanding systemd jobs before deciding whether launch occurred. The systemd API requires the unit name to be unique while the unit is loaded; after cleanup/GC the durable journal tombstone prevents that launch_id/unit identity from being reused.
- While the systemd operation is unresolved, the state is local_uncertain; no effective stop-fence ACK is sent, no replacement launch is issued and SEM retains the reservation.
- If the unit exists or its start job is pending, the Supervisor adopts the same invocation and applies termination to that unit after the release fence.
- If systemd authoritatively proves the unit was never created and no start job remains or can later complete, the Supervisor may commit stop_fenced and acknowledge that no late start can occur.
- The broker MUST NOT interpret a D-Bus timeout, missing unit from a stale cache, or missing PID as proof of no process.

### 13.4 Positive process-exit evidence

For V1, a process-exit report requires correlated evidence from the host systemd manager and cgroup v2:

1. Exact runner_id, execution_id, binding_epoch, launch_id, containment_id and host boot_id.
2. Exact systemd unit invocation identity and cgroup path for that launch.
3. systemd reports the matching invocation in a terminal inactive state with no restart pending.
4. The exact cgroup v2 subtree reports populated 0 after termination, and the broker has verified that the cgroup cannot accept new descendants.
5. The Supervisor durably journals the observation before publishing the event to SEM.

For a normal process exit, the numeric exit status may be recorded when available. If the host manager proves the exact containment is empty but the numeric status was lost during a crash, report exit_status=unknown; do not fabricate an exit code. A systemd stop job ACK alone is not exit evidence.

A change in host boot_id proves that processes from the prior kernel boot cannot still be executing on that same host, but it does not by itself prove the old process registry was correctly associated with the prior boot. The Supervisor must reconcile its durable old-boot launch records and report a boot-boundary evidence record. If host identity or boot lineage is ambiguous, retain quarantine.

### 13.5 Required Linux failure-injection tests

The implementation acceptance suite MUST inject crashes at each boundary:

- after durable start_intent, before D-Bus call;
- while StartTransientUnit is in flight;
- after systemd creates the unit, before the D-Bus reply;
- after process creation, before process identity is journaled;
- after release fence commit, before systemd stop request;
- while systemd stop is in flight;
- after process exit, before exit evidence is journaled;
- after exit evidence is journaled, before WSS publication/ACK;
- while the Supervisor restarts with an active Harness;
- while the host reboots with active or uncertain execution units.

Every case must prove no duplicate Harness launch, no false stop/exit ACK, no premature reservation release and deterministic reconciliation using the same unit/launch identity.

### 13.6 Upstream interface references

- systemd transient unit API and supported transient properties: https://systemd.io/TRANSIENT-SETTINGS/ and https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.systemd1.html
- systemd control-group interface and StartTransientUnit semantics: https://systemd.io/CONTROL_GROUP_INTERFACE/
- systemd service ExitType/RemainAfterExit semantics: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
- Linux cgroup v2 populated semantics: https://docs.kernel.org/admin-guide/cgroup-v2.html

These upstream documents establish available interface semantics, not the behavior of every target distribution build. The minimum supported distro/systemd/kernel matrix still requires integration testing.

### 13.7 Explicit limitations

- V1 does not support Windows Job Objects, macOS launchd, cgroup v1, non-systemd Linux hosts, or a Runner container that cannot use a trusted host-side systemd broker.
- The user has selected manual on-site handling for permanent host loss. No managed-VM API or BMC/IPMI integration is required; V1 needs only a durable visible `unreachable` status, retained quarantine and a minimal audited manual resolution action if normal reconnect/reconciliation cannot resolve it.
- The systemd/cgroup design is a selected V1 architecture candidate, not yet implementation-verified. A Linux integration spike and failure-injection evidence are required before D-03/D-05 can be ratified.