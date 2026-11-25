# SEM V1 State Machines

Status: target behavior, not a claim that all states exist in code.

## 1. Run / Attempt

- queued → claimed only through successful claim.
- claimed → running after executor/process identity is confirmed.
- running → terminal result only through guarded transition handling.
- claimed/running with uncertain liveness → durable Execution Barrier plus evidence/HIR; Interaction scheduling_shield remains a separate four-value state.
- Barrier-held Run → E1/E2/E3-backed release, or E6 risk-accepted successor while the old Barrier remains unresolved.
- Replacement Attempt is a new task_run row with lineage, never a reset of the old row.

Forbidden: lease expiry alone → queued; E4/E5 → automatic new Attempt; late heartbeat → shield removal; stale generation → accepted result.

## 2. Lease

- Unowned → Owned(generation, client, token verifier, expiry) on claim.
- Owned → Renewed only with matching client identity, token proof and generation.
- Owned → Expired when time passes. Expiry is a trigger, not proof of process death.
- Expired → Reclaimed only after E1/E2/E3 and guarded transaction.
- Expired + uncertain process → Shielded; lease may expire naturally while shield remains.
- New claim increments generation and rotates token verifier.
- Never rewrite a lease owner from Runner A to Runner B.

## 3. Termination evidence

| Evidence | Meaning | Permitted action |
|---|---|---|
| E1 | SEM observed process exit result from OS poll/wait | Confirm exact process dead; guarded recovery may proceed |
| E2 | PID/process identity checked against OS and original process absent | Confirm exact process dead; guarded recovery may proceed |
| E3 | Authenticated Runner supervisor observed target process exit and sent generation-bound confirmation | Confirm exact remote process dead; guarded recovery may proceed |
| E4 | Runner heartbeat absent beyond configured grace | Shield + HIR only |
| E5 | Process state unknown or contradictory | Retain Execution Barrier, alert/HIR, no automatic reclaim |

Evidence applies only to the exact process identity and generation it describes.

## 4. Runner

Supervision mode is unattended or supervised. Missing value at first registration defaults to unattended. supervised requires pre-claim user confirmation. Availability (online/offline/busy/unavailable) is independent.

## 5. HIR

Target lifecycle: Created → Notified → AwaitingUserAction or AwaitingRunnerSelection → Accepted → InProgress → Resolved → Closed.

A self-resolved HIR may close only when the original condition is proven safe; record evidence. Reopen must preserve prior history. HIR status is workflow state, not Run state; HIR cannot grant a lease or clear an Execution Barrier by itself.

## 6. Handoff

1. User authorizes/selects target Runner when policy requires.
2. Old execution is stopped or remains safely isolated.
3. Old lease/token becomes unusable through guarded expiry/revocation and generation change.
4. New Runner explicitly performs normal claim.
5. Generation increments and fresh token is issued.
6. Target Runner creates its own workspace.
7. New execution begins only after successful claim.

No direct lease-owner rewrite and no weakening of lease_client_id checks.


## 7. Detached / Runner reconnect lifecycle（修正设计，Review Pending）

```text
Active → Detached → Reconciling
Reconciling → Active              # same Runner + exact process alive + current Lease/Generation valid
Reconciling → Terminated          # E1/E2/E3 proves exact process exit
Reconciling → Quarantined         # E4/E5, identity mismatch, missing evidence
Quarantined → RiskAccepted        # explicit E6, one bound successor only; old barrier remains unresolved
```

`Detached` 是 Execution/Session lifecycle 状态，不属于 `task_run.scheduling_shield`。当前 Interaction shield 四值保持不变。Platform 持久化的 `run_execution_barrier` 是执行不确定性的隔离载体。

### 7.1 Detached → Active 条件

- 必须由同一 Runner/device 重新认证并提交 reconnect sync；
- Run/Generation/Lease 仍由 Platform 判定有效；
- 进程必须由 boot_id + process creation identity 精确识别，且 Runner 重新建立 OS 监督句柄；
- 仅凭 device ID、PID 或 Harness Native Session ID 不足以恢复；
- Lease 已过期但进程仍活着时，先安全终止并获得 E3，不能重签 Lease 后让旧进程继续；
- 无法对账则进入 Quarantined + HIR。

## 8. E6 Human Risk Acceptance（授权证据，不是终止证据）

| 类别 | 含义 | 允许动作 |
|---|---|---|
| E1/E2/E3 | 已观察到精确进程退出 | 可按安全事务释放 Barrier 并自动恢复/重派 |
| E4/E5 | 进程可能仍运行或无法判断 | 仅隔离、通知、HIR；禁止自动重派 |
| E6 | 有权限操作者明确接受旧进程仍可能运行的残余风险 | 可授权一个绑定的 successor Attempt；旧 Barrier 仍保持 risk_accepted_unconfirmed |

E6 必须二次确认、风险展示、凭据撤销尝试/副作用缓解、独立 Workspace、唯一 successor 绑定和不可变审计。E6 不得标记原进程已死，不得解除旧 Barrier；后续只有 E1/E2/E3 才能释放。

## 9. Execution Control 与 Interaction Continuation

Interaction 的 terminate/continue 命令必须有确定的执行端消费者。Runner WSS adapter 与 SEM-local CodexExecutor adapter 都实现统一 Execution Control Port。continue 表示 checkpoint + 用户回复注入；默认启动新 Harness Session。它不等于 Native Session Resume，也不证明旧进程终止。Command receipt、command result、process-exit evidence 和 continuation-consumed 分别记账。

## 10. 通知与 HIR

Interaction/HIR 创建事务都必须追加 Outbox 通知事件并解析收件人；通知有独立 delivery 状态。HIR Phase 0 即有最小可操作生命周期和 Inbox。Interaction 的响应 deadline（当前默认 120 秒）不是通知延迟，也不能自动释放 Execution Barrier。
