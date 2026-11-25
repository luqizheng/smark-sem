# SEM V1 Domain Model

Status: normative architecture target, not a claim about current implementation.

## 1. Core concepts

| Concept | Meaning | V1 identity / authority |
|---|---|---|
| Logical execution | One task's execution lineage across retries | A lineage of delivery.task_run rows |
| Run / Attempt | One concrete execution attempt and lease generation | One task_run row; attempt_no and supersedes_run_id preserve lineage |
| Executor Session | Platform-created executor process identity | task_run.executor_session; never a Harness session ID |
| Harness Native Session | Session identity owned by a Harness | task_run.harness_session_id + harness_kind |
| Runner | Registered client-side process supervisor | Persisted Runner registration |
| Lease | Time-bounded execution ownership | Run owner, token verifier, expiry and generation |
| HIR | Human workflow for abnormal execution intervention | New governance.human_intervention_request entity |
| Scheduling Shield | Durable exclusion from automatic claim/requeue | PostgreSQL state associated with the Run |

## 2. Run lineage

- One logical execution may contain multiple Run rows.
- One Run row is one Attempt and has at most one active execution owner.
- supersedes_run_id points to the prior Run in the same task lineage.
- attempt_no increases monotonically within that lineage.
- A replacement Attempt receives a new Run ID, generation, executor process identity and workspace.
- A Harness Resume does not transfer the old lease or process identity.
- A copied Harness session ID alone never proves cross-device or cross-host resumability.

## 3. HIR entity target

Target table: governance.human_intervention_request.

Minimum conceptual attributes:
- ID and tenant/project/task/Run references.
- Optional superseding Run reference.
- Reason code and evidence class (E3/E4/E5 or non-liveness intervention).
- Status, requested action and resolution code.
- Created/updated/resolved/closed timestamps.
- Actor identity for system and human transitions.
- Optional Runner selection and Harness session reference.
- Optimistic concurrency/version field.

Required constraints:
- HIR and Run must share tenant/project/task lineage.
- Multiple historical HIRs may exist; unresolved duplicates for one active intervention episode are prevented.
- Every transition is transactional and audited.
- HIR does not replace task_interaction. Interaction requests normal user input/decision/permission; HIR coordinates abnormal execution, process uncertainty and takeover.

## 4. Runner supervision

- Missing supervision mode at first registration defaults to unattended.
- unattended may claim automatically within platform authorization.
- supervised requires explicit user confirmation before each claim.
- Supervision mode is independent of online/offline/busy/unavailable.
- Mode changes are authorized and audited; active leases are not silently reinterpreted.

## 5. Session and workspace rules

- executor_session is not a Harness Native Session ID.
- Harness capabilities are code-level adapter metadata; Resume is disabled by default and gated by exact Harness/version acceptance.
- Workspace loss does not imply process death.
- Workspace, Worktree and Git Mirror are not backup targets. The runtime volume may persist while SEM operates; loss invokes E4/E5 isolation.
- Each Repository has one authoritative Git origin. SEM does not orchestrate multi-origin synchronization.

## 6. Scheduling Shield

The shield is a durable scheduling invariant, not an audit-only event or lease extension:
- Every claim and automatic requeue/recovery path excludes shielded Runs.
- Lease may expire naturally while shield remains active.
- Late heartbeat does not clear the shield or revive an old generation.
- Only E1/E2/E3 evidence-backed termination may release it. E6 may authorize one risk-accepted successor but leaves the original Barrier unresolved.
- A shielded Run must have an actionable HIR or explicit operational escalation record.


## 7. Runner resource capacity (ADR-SEM-26 — approved)

Runner reports CPU, memory, and the actual Workspace volume's free space to SEM. SEM owns the latest resource snapshot and per-Run+Generation admission reservations; Platform remains authoritative for Claim, Lease, Generation, and business Run state. Candidate tasks carry a conservative resource profile (CPU units, peak memory budget, Workspace growth budget, profile class). SEM atomically reserves capacity before requesting Platform Claim, retains reservations through ambiguous Claim outcomes and active execution, and releases only after safe terminal/termination handling. Unknown or stale metrics block new work but never imply that active processes have exited. Resource pressure does not automatically kill or migrate running tasks in V1.


## 8. Interaction / HIR / Continuation / Cleanup 分域（Review Pending）

- Interaction 表达 Agent 向人提问及响应链；其 scheduling_shield 四值保持原样。
- Continuation 表达 checkpoint + response 投递、执行端注入和新 Session 启动；consumed 不证明旧进程退出。
- HIR 表达执行异常、失联、风险处置和 handoff；Phase 0 最小可操作，Phase 4 扩展高级流程。
- Cleanup Need 表达 Workspace/进程清理失败；仅在伴随执行不确定性时关联 HIR/Barrier。
- Execution Barrier 表达 Run+Generation 的物理执行不确定性；Detached 是生命周期投影，不是 shield 枚举值。
- Notification 必须有明确 recipient 与 delivery 状态；Interaction/HIR 事务各自 Outbox 触发通知。

## 9. E6 Human Risk Acceptance

E6 是授权事实，不是进程终止事实。它允许一个被精确绑定的 successor Attempt 在明确披露旧进程仍可能运行的残余风险后启动；旧 Barrier 保持 `risk_accepted_unconfirmed`，不能标记 released。只有 E1/E2/E3 才能证明进程终止并释放 Barrier。自动重派仍严格要求 E1/E2/E3。

## 10. Dispatchability

Platform 统一 dispatchability predicate 必须检查 Interaction shield 与 Execution Barrier，并覆盖 queued claim、B3-1/B3-2、B06-D3、retry/requeue、orphan reconciliation、handoff 和 E6 successor。候选 SQL 过滤不能代替事务锁内重验。
