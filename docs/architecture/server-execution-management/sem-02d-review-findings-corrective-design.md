# SEM-02D 评审问题核验与修正设计（Review Findings 01–10）

- 状态：**Corrective Design Proposal — Review Pending**
- 日期：2026-11-25
- 适用范围：SEM V1 的人工介入闭环、进程证据、Runner 重启恢复、Session 连续性、调度屏障和阶段验收。
- 性质：基于当前 master 代码与架构文档的只读复核及修正设计；不代表用户已批准，不是实施授权。
- 实施状态：未修改业务代码、Migration、API、Runner/Worker 主循环、Dockerfile 或 Compose；Phase 0 未启动。

## 1. 结论

用户提出的 10 项评审问题整体成立。它们揭示了上一版 SEM-02D 设计的关键缺口：设计把“HIR 数据实体”“Runner 控制消息”“执行端进程事实”“Interaction continuation”和“Session Manager”分散在不同 Phase，未形成一个可运行的端到端闭环。

**修正原则：**
1. Phase 0 必须已有可操作的最小 HIR 闭环；不能把 HIR 的可用性推迟到 Phase 4。
2. Interaction 的 terminate / continue 是执行控制，不是 HIR。必须覆盖 Runner 与 SEM 本机 CodexExecutor 两种执行位置。
3. E3 不应只依赖 cancel 命令 ACK。Runner 必须上报自然退出、主动终止、租约丢失清理、启动孤儿清理等所有可观察的进程退出事实。
4. Runner 断线或重启必须有 Detached → Active 的明确恢复路径；不能把“已有 start_wait 回复”误当成全部恢复场景。
5. 缺少 PID 文件、日志或 Workspace 卷不能证明进程死亡。对已确认启动的 Run，证据丢失一律 E5。
6. 人工授权重派必须作为独立的风险授权类别记录，不能伪装成 E1/E2/E3。
7. Interaction、Continuation、HIR、Execution Barrier、Workspace Cleanup 是不同领域对象，明确关联但不合并。
8. Detached 是执行生命周期状态，不扩展 Interaction 的四值 scheduling_shield。
9. 所有自动派发、回收、重试、重排入口必须使用同一 Platform dispatchability predicate。
10. Phase 2 的端到端验收必须覆盖 Interaction 完整往返、HIR 可操作、E3 证据和 Runner 重启恢复，不只验收“跑一条普通任务”。

## 2. 十项问题核验结论

| # | 级别 | 核验结论 | 主要代码/文档依据 | 设计处理 |
|---|---|---|---|---|
| 1 | P0 | **确认**。Interaction 创建会签发 terminate 命令；当前 Runner 是 terminate/continue 命令消费者。Runner 的 continue 会创建新的 Agent 进程并写入回复文件；CodexExecutor 没有对应的 Interaction reply-injection / continue command adapter。不能把 Runner 的命令消费者当作所有 spawn 执行形态的闭环。 | `interaction.rs` 创建 Interaction、更新 human_wait、写 task_waiting、调用 `issue_terminate_command`；`runner_loop.rs` 的 `tick` 轮询命令、`execute_command` 处理 terminate/continue；`codex_executor.rs` 只有 RunExecutor start/poll/terminate 进程端口。 | 增加统一 Execution Control Port；Runner WSS Adapter 与 SEM-local CodexExecutor Adapter 都必须实现 terminate、continue_with_response、process-exit reporting。 |
| 2 | P0 | **确认**。Phase 0–3 的 runner 失联路径被设计为 E4/HIR，但旧路线把可操作 HIR 放到 Phase 4，早期阶段会只留下无法处置的屏障。 | `execution-safety.md` §3.2；`migration-roadmap.md` Phase 0/4；当前 HIR 尚无完整通知/处置闭环。 | 最小 HIR（创建、查询、责任人/收件人、通知、受控处置）移到 Phase 0；Phase 4 只保留高级跨 Runner handoff / 监督选择体验。 |
| 3 | P0 | **确认**。Runner 的自然退出路径主要记录日志后清空 active；租约丢失清理路径终止本地 Agent 后写本地 cleanup 证据；在 cleanup pending 时跳过正常 tick/命令轮询。当前没有完整、持久、独立于 Lease 有效性的 Runner 进程退出证据回传。 | `runner_loop.rs` 主循环与 `lease_lost_cleanup_pending`；自然退出 `adapter::reap`；`execute_command` 的 terminate ACK；`adapter.rs` `reap/terminate_with_retry`。 | 定义 Runner process evidence spool + WSS `runner.process.exit` / `runner.process.reconciled`；报告不要求有效 Run Lease，但必须有有效 Runner 设备身份，并绑定 Run、Generation、boot_id、process identity。 |
| 4 | P1 | **确认**。当前 Runner 启动恢复主要面向已响应且处于 `start_wait` 的 Interaction continuation；不等于执行中途 Runner 进程/网络失联后的通用同设备恢复。 | `recovery.rs` 要求 `scheduling_shield='start_wait'`、同一 `lease_client_id`、已有 responded Interaction；`session-manager-design.md` §6.4“平台侧无需变更”过度概括。 | 增加 Runner lifecycle `Active → Detached → Reconciling → Active/Terminated/Quarantined`；平台提供同设备 reconnect/reconcile API，恢复需检查 boot/process identity、Lease、Generation 和 barrier。 |
| 5 | P1 | **确认**。CodexExecutor 在 PID 记录缺失且 logs 目录也不存在时返回 `Done{Lost}`；对曾经 `stage='started'` 的 Run，这种情况也可能由 Workspace 卷丢失造成，不能作为死亡证据。 | `codex_executor.rs` poll 的跨重启分支；`run_executor.rs` 将 `Done{Lost}` 走失联恢复路径。 | `Lost` 不再等于已终止。若 Platform 记录表明曾启动，缺失 PID/log/workspace 一律 `Uncertain/E5`；只有权威证明从未 spawn 才可走未启动回收。 |
| 6 | P1 | **确认**。原文一方面要求 E4 不能重派，另一方面又写“授权重派”，同时要求不变式①必须先停止/隔离旧执行端，语义冲突。 | `execution-safety.md` R-SAFE-1/2 与解除屏障段；`runner-supervision-and-handoff.md` §4.2。 | 新增 E6 Human Risk Acceptance（人工风险接受授权）。E6 不是进程终止证据；它允许一次显式风险接受的后继 Attempt，但旧 Barrier 仍标记未证实终止，展示残余风险并单独审计。 |
| 7 | P1 | **确认**。现有 `integration.notification` 没有收件人字段；Interaction 创建事务只写 Interaction、shield、waiting、terminate command 和 audit，没有写通知。HIR/Interaction/Continuation/cleanup 的映射也未定义。 | `0001_baseline.sql` `integration.notification`；`interaction.rs` Interaction 创建事务；现有 interaction deadline 默认配置。 | 建立明确 Recipient Resolution、事务 Outbox、通知投递账和用户 Inbox 落点；Interaction 通知与 HIR 通知分别触发。120 秒是 Interaction response deadline，不是通知发送延迟或 HIR 自动关闭时间。 |
| 8 | P1 | **确认**。Session Manager 文档把采集点放在 SEM 的 `poll_active_runs`，不能采集远端 Runner 设备本地 CODEX_HOME 的原生 Session；现有 continue 路径是 checkpoint/reply 注入后启动新 Agent Session，不等于 Harness Native Resume。 | `session-manager-design.md` §4/§6；`runner_loop.rs` continue 的 `spawn_agent_session(... Some(&response) ...)`；Codex resume 默认 false。 | 拆分 Interaction Continuation、Process Reattachment、Harness Native Resume 三种能力；Native Session ID 在实际执行主机采集并上报；跨设备不凭 session ID 声称可恢复。 |
| 9 | P2 | **确认**。当前 scheduling_shield CHECK 仅四值；把 Detached 塞入该枚举会改变 Interaction 状态域，并与现有 timeout/reacquire 精确匹配冲突。 | `0001_baseline.sql` `task_run_scheduling_shield_check`；`recovery.rs` 精确要求 `start_wait`。 | 不新增 shield 枚举值。Detached 由 Session/Execution lifecycle 投影表达；持久执行隔离由独立 `delivery.run_execution_barrier` 表承载。Phase 0 必须包含正式 Schema Migration，不能声称无 Schema 变更。 |
| 10 | P2 | **确认**。B06-D3 把 Run 改回 queued 后，普通 queued claim 路径不会经过仅对过期 claimed Run 执行的 `candidate_shield` 检查；屏蔽中的 Run 可能被普通领取。 | `run_executor.rs` B06-D3 UPDATE；`claim.rs` candidate_shield 只在 `run_state == claimed` 回收分支检查；queued 正常领取继续走 Task ready 和依赖门禁。 | 所有入口使用共享 `is_dispatchable` / `assert_dispatchable`；必须检查 Interaction shield + Execution Barrier + HIR/授权策略 + Generation/Lease + Task/Project/Device 条件。B06-D3 不得把 shielded Run 回队。 |

## 3. 人工介入与执行控制：必须区分的对象

### 3.1 Interaction（Agent 向人提问）

Interaction 是业务交互链，保持现有语义：
- Agent 创建 Interaction：持久化 `task_interaction`、`task_waiting`，Interaction shield 进入 `human_wait`，并创建 terminate 命令。
- 执行端收到 terminate：终止当前 Agent 进程并回传命令结果与进程退出证据。
- 用户回复：Interaction 进入 `responded`，shield 进入 `start_wait`，创建 response delivery 与 continuation。
- 执行端收到 continue：将 checkpoint + 用户回复注入执行上下文，默认创建新 Harness 进程/Session；成功后回报 input-injected + process-alive 消费证据。
- Interaction 进入 `consumed` 后关闭等待链；只有按现有事务规则满足消费条件，Interaction shield 才回到 `none`。

### 3.2 HIR（执行异常、失联、人工接管）

HIR 是执行治理对象，不代替 Interaction：
- 触发源：E4/E5、进程清理失败、Runner 重启无法对账、执行端身份不一致、需要人工风险接受或跨 Runner handoff。
- Phase 0 即创建正式 HIR 并具备最小操作能力：创建、查询、责任人/收件人、通知、追加证据、受控处置、审计。
- HIR 可以关联一个或多个 Interaction、Run/Generation、Execution Barrier、Cleanup Need；HIR 关闭不自动释放 Barrier。
- HIR 的基本处置至少包括：`hold`（继续隔离）、`terminate_confirmed`（已有 E1/E2/E3）、`risk_acceptance_requested`（进入 E6 审批，不直接放行）。
- Phase 4 增加完整 Runner 选择、跨设备 handoff、监督模式通知和用户体验，不再承担“首次让 HIR 可用”的责任。

### 3.3 Continuation（回复投递与新会话启动）

Continuation 是回复投递/注入账本，不是 HIR：
- 它绑定 Interaction response、delivery、continue command 和 generation。
- 当前已实现的基本行为是 checkpoint/reply 注入后创建新的 Agent 进程/Session。
- `supports_resume=false` 时必须继续走 Fresh Session，不得把新 Session 标记为 Native Resume。
- Continuation consumed 仅表示回复被执行端实际注入且 Agent 已启动，不证明旧执行进程终止；旧进程终止必须有独立 E1/E2/E3。

### 3.4 Cleanup Need（资源清理人工处理）

现有 `task_run_cleanup.needs_human` 表示 Workspace/进程清理重试耗尽后的运维人工处理：
- 它不等于 HIR，也不等于 Interaction。
- 若 cleanup 失败同时意味着进程状态未知，应关联 HIR + Execution Barrier。
- 单纯文件清理失败但进程已确认终止，可保留 Cleanup Need，不应制造执行不确定性 HIR。
- 清理记录完成不能自动清除 Interaction shield 或 Execution Barrier。

### 3.5 两类屏障

- `task_run.scheduling_shield` 保持四值 `none/human_wait/start_wait/timed_out`，只表达 Interaction/Continuation 调度保护。
- `delivery.run_execution_barrier` 是独立持久实体，表达特定 Run+Generation 的进程/执行状态不确定性。
- `Detached` 是 Execution/Session lifecycle 的状态投影，不是 scheduling_shield 新值。
- Platform 所有派发和回收入口必须同时检查这两类屏障。

## 4. 统一 Execution Control Port

所有执行位置必须有同一组业务语义，不允许只在 Runner 上实现命令消费者：

```rust
trait ExecutionControlPort {
    async fn terminate(&self, target: ProcessIdentity, reason: TerminateReason)
        -> TerminationObservation;
    async fn continue_with_response(&self, input: ContinuationInput)
        -> ContinuationStartResult;
    async fn report_process_observation(&self, observation: ProcessObservation)
        -> Result<()>;
}
```

Adapter：
- **Runner adapter**：SEM 通过 WSS 投递命令；Runner Supervisor 在本机操作 Agent 进程、注入 checkpoint/reply，并报告结果。
- **SEM-local CodexExecutor adapter**：SEM 接收 Platform HTTPS 命令后，直接调用本机 CodexExecutor；必须实现 Interaction terminate 与 continue_with_response，而不只是 RunExecutor 的 start/poll/terminate。
- **Harness adapter**：声明 Native Session ID、Resume、Inspection、Termination、Activity 能力；resume 默认 false，未通过实测不得打开。
- Platform `worker_command` 是业务命令状态权威；SEM `command_delivery` 是远程传输账本；本机执行命令也必须落同一业务 ACK/结果模型。
- Receipt ACK、command result、process termination evidence、continuation consumption 是四种不同事实，不能相互代替。

## 5. E3：Runner 进程退出证据必须覆盖所有退出路径

### 5.1 上报事件

WSS 增加：
- `runner.process.exit`：进程已退出，包含 `runner_id`（由连接身份推导）、`boot_id`、`run_id`、`generation`、`process_identity`、`exit_outcome`、`observed_at`、`source`、可选 `command_id`、evidence digest。
- `runner.process.reconciled`：Runner 重启后对先前进程记录做对账，报告仍存活、已不存在或无法验证；不得把无法验证报成已退出。
- `runner.reconnect_sync`：报告当前 boot_id、活动进程清单、待发送证据 spool、当前 Run/Generation 视图。

`source` 至少区分：`natural_exit`、`command_terminated`、`lease_loss_cleanup`、`startup_orphan_cleanup`、`runner_shutdown`、`boot_transition_reconciliation`。

### 5.2 本地可靠证据账本

- Runner 在确认 OS 进程退出后，先将结构化证据原子追加到本地持久 spool，再经 WSS 发送；收到 SEM 持久化 ACK 后才标记已送达。
- spool 不放在可随单个 Workspace 回收的目录中；使用 Runner 自身状态目录。它不是 Workspace 备份，不改变 Workspace 可重建原则。
- WSS 断开、Lease 过期、Generation 失效均不能阻止 Runner 上报“旧进程已经退出”的证据；该通道只允许追加观察事实，不允许用旧 Lease 修改 Run 业务状态。
- SEM 对 evidence_id 幂等持久化，再通过 Platform HTTPS API 提交；Platform 校验 Runner 身份、原 Run/Generation、process identity 和事件顺序。
- cancel command receipt ACK 与 `runner.process.exit` 分开；只有后者满足 E3 终止证据条件。
- 自然退出也必须上报，不能只在日志中记录后丢弃 active。

### 5.3 PC 重启

- Runner 每次启动生成/读取 OS boot identity；进程身份必须绑定 `boot_id + pid + process_creation_time`（Windows 可用进程创建时间/Job Object；Linux 使用 boot_id + /proc starttime；macOS 使用可验证的 boot/process start identity）。
- 若重启后 boot identity 改变，且旧进程身份可证明属于旧 boot，OS 重启本身可形成受约束的 E3 子类 `boot_transition_absence`；必须保留旧/新 boot_id、设备身份、Run/Generation 和进程身份。
- OS 无法提供稳定 boot identity、身份记录缺失或证据冲突时降级 E5，不能猜测旧进程已死。

## 6. Runner Detached → Active 恢复

目标生命周期：
```text
Active
  └─ connection/supervisor lost → Detached
Detached
  └─ same Runner reconnects → Reconciling
Reconciling
  ├─ same boot + exact process alive + current Lease/Generation valid → Active (reattach)
  ├─ E3 process exit confirmed → Platform finalizes/recovery path; then Active or Idle
  ├─ boot-transition E3 confirmed → Platform finalizes/recovery path; then Active or Idle
  └─ process/identity/lease state uncertain → Quarantined (Barrier + HIR)
```

规则：
- `Detached → Active` 只允许同一 Runner/device 身份完成 reconnect sync，并且 Platform 仍承认该 Generation/Lease；Runner 必须重新绑定 OS process handle/Job Object 或其他可验证进程观察能力。
- 不能只凭同一 device ID、同一 PID 或同一 Harness session ID 恢复。
- Lease 已过期但进程仍存活：先执行安全终止并报告 E3；不得直接重签 Lease 后让旧进程继续运行。
- 若旧进程已死并有 E3，按 Interaction continuation / retry policy 选择恢复；Native Resume 仍需独立能力门禁。
- 若 E4/E5，无自动新 Attempt；进入 HIR/Barrier。人工风险接受只能走 E6。

## 7. E5 与 Workspace 丢失：修正 Lost 语义

- `ExitOutcome::Lost` 表示退出原因/状态无法确认，不等于 OS 观察到进程退出。
- 对 Platform `stage='started'` 或有 spawn-confirmed 记录的 Run，PID 文件、logs、Workspace root 同时缺失必须返回 `Uncertain/E5`，不允许返回 `Done{Lost}`。
- 只有 Platform 权威状态明确证明尚未 spawn（例如 stage 仍为 dispatch 且无 spawn-confirmed 记录），才允许走 B3-1 未启动重领。
- Workspace 卷丢失是证据丢失，不是进程死亡证据；不得自动释放 Execution Barrier、资源预留或重派。
- 将 `Done{Lost}` 从可回收结果中移除；所有调用点和测试必须明确断言 Lost → E5。

## 8. E6：Human Risk Acceptance（人工风险接受授权）

E6 不是“旧进程已死”的证据，而是“有权限的人明确接受旧进程仍可能运行的风险”的授权记录。

自动重派规则：
- 自动重派：仅 E1/E2/E3。
- E4/E5：默认只隔离，不自动重派。
- 人工风险接受重派：必须有 E6，不得将 E6 转写成 E1/E2/E3，也不得伪造 terminate ACK。

E6 最低要求：
1. 操作者具备明确的高风险处置权限；记录身份、时间、原因、工单/说明。
2. 展示并二次确认：旧进程可能仍运行、Git push/commit/外部 API/LLM 费用等副作用可能重复、DB fencing 无法阻止进程外部副作用。
3. 显示旧 Run、Generation、Runner、最后心跳、进程证据缺口、Workspace 状态、已尝试的终止/凭据撤销及其结果。
4. 尽可能先撤销可撤销凭据；新 Attempt 使用独立 Workspace/Worktree/branch；禁止自动覆盖或合并不确定旧 Attempt 的外部结果。
5. 在 Platform 事务中写入不可变 E6 授权记录、操作者、风险摘要、缓解措施、被授权的唯一 successor Run/Generation；创建后不可扩大授权范围。
6. 旧 Execution Barrier 保持 `risk_accepted_unconfirmed`，不能标成 released/terminated；新 Attempt 只能作为该 Barrier 的唯一授权 successor。
7. 后续若获得 E1/E2/E3，再独立释放旧 Barrier；HIR 关闭和 E6 授权均不能自动释放旧 Barrier。
8. E6 不允许绕过设备身份、租户/项目权限、Generation fencing、Workspace 单写者和审计要求。

## 9. 通知与 HIR / Interaction 映射

### 9.1 通知投递

- `interaction.created` 与 HIR 创建都必须在各自业务事务中追加 Outbox 事件；不能只写 Audit。
- 通知需要明确收件人。建议采用 `integration.notification` + 独立 recipient/delivery 关系（或等价的规范化模型），至少支持 `recipient_user_id`、渠道、状态、attempt、read/delivered 时间和幂等事件 ID。
- Recipient Resolution 必须确定且可审计：优先任务明确负责人；否则项目负责人/项目管理员；没有可解析收件人时创建可见的项目级未分派队列并告警，不能静默丢弃。
- 通知应在 Interaction/HIR 创建提交后立即进入投递，不得等待 120 秒。Interaction 的 120 秒是响应 deadline，不是通知延迟。
- 通知失败重试/死信不改变 Interaction/HIR/Barrier 的业务状态；收件箱查询仍可见待处理事项。

### 9.2 映射表

| 现有/目标对象 | 负责的事实 | 与 HIR 的关系 | 不得混淆 |
|---|---|---|---|
| `task_interaction` | Agent 问题、用户回复、responded/consumed | HIR 可引用 interaction_id | HIR 不是 Interaction 的替代 |
| `interaction_response_delivery` | 回复投递/重试 | HIR 可引用失败 delivery | delivery ACK 不代表进程终止 |
| `continuation` | checkpoint + response 注入、新 Session 启动和消费 | HIR 可引用 continuation_id | continuation consumed 不释放 Execution Barrier |
| `task_run.scheduling_shield` | Interaction/Continuation 四值调度保护 | HIR 可关联，但不承载 Detached | 不新增 Detached 枚举 |
| `run_execution_barrier` | 特定 Run+Generation 的执行不确定性隔离 | HIR 必须关联 barrier | HIR closed 不自动释放 barrier |
| `task_run_cleanup` / needs_human | Workspace/进程清理失败的运维队列 | 发生执行不确定性时关联 HIR | 单纯清理失败不等于 HIR |
| `integration.notification` | 通知内容/收件人/投递 | 分别由 Interaction/HIR Outbox 触发 | Notification delivered 不等于用户已处置 |

## 10. 全局 Dispatchability Predicate

定义 Platform 统一谓词 `is_dispatchable(run, target_runner, operation)`，用于：
- 普通 queued claim（Model A / Model B）；
- B3-1 / B3-2 lease recovery；
- B06-D3 orphan reconciliation；
- retry / requeue / retry exhaustion recovery；
- SEM 发起 Platform Claim；
- same-device Detached recovery；
- handoff / E6 successor authorization。

至少校验：
1. Run/Task/Project 状态允许执行；
2. Interaction shield 允许该操作（普通新启动要求 `none`；合法 continuation 必须匹配对应 `start_wait` + responded Interaction + 未消费 response）；
3. 不存在阻断该 successor 的 active Execution Barrier；如存在，只能由精确绑定的 E6 授权 successor 走受限例外；
4. 租户、项目、设备绑定、Runner 注册/撤权、lease_client_id 和目标 Runner 资格有效；
5. Generation、Lease、命令状态、单执行者约束有效；
6. 资源准入与资源预留成功（SEM 调度层）；
7. 所有判定在 Platform 事务内对权威字段重新校验，不能信任 SEM 缓存或候选 SQL 的早期快照。

**B06-D3 特别规则：**
- 若 Run 有非 `none` Interaction shield 或 active Execution Barrier，不得将其改为普通 queued 并允许正常 claim。
- B06-D3 只能对经过 dispatchability/recovery predicate 的对象处理；不能仅因 >1h + audit 缺失就重排。
- 普通 queued candidate SQL 必须过滤 shield/barrier；锁内仍需再次校验，不能只依赖候选查询过滤。

## 11. 修正后的 Phase 顺序与验收

### Phase 0 — Safety + Minimum Human Intervention（必须可操作）

- 正式 Migration：Execution Barrier + 最小 HIR + 通知收件人/投递关系（或明确等价模型）；不增加 scheduling_shield 枚举值。
- HIR 最小生命周期：创建、查询、责任人/收件人、通知、追加证据、hold/安全关闭、审计；未获得 E1/E2/E3 时不得把 barrier 标成释放。
- 统一 Platform dispatchability predicate，覆盖 claim/recovery/B06-D3/retry/requeue/普通 queued claim。
- 修复 B3-2、B06-D3、`Done{Lost}` 卷丢失误判；Runner 项目孤儿不能被绕过证据自动回收。
- 建立 Execution Control Port，至少覆盖 Runner 与 SEM-local CodexExecutor 的 terminate/continue/reply injection；不能有“命令已发出但没有消费者”的执行形态。
- 交付最小人工 Inbox/处置入口。高级跨 Runner handoff 可留 Phase 4，但 HIR 不能只是数据库里一行。

验收：Agent Interaction 完整往返；Runner 和 CodexExecutor 两种执行位置都能 terminate、收到回复后 continue、注入 response、报告消费；HIR 可被责任人看到和处置；屏蔽 Run 不会被 B06-D3 或普通 claim 重启；Lost/卷丢失只进 E5。

### Phase 1 — SEM Control Plane + Runner E3

- Platform–SEM HTTPS、Runner–SEM WSS、Ticket、connection epoch、WSS command delivery。
- Runner 本地持久 process evidence spool；自然退出、terminate、lease-loss cleanup、startup cleanup、shutdown、boot transition 都能上报。
- WSS reconnect sync 与 Detached → Active / Quarantined 对账。
- 移除 Runner MCP Claim/command poll/ACK/recovery 控制旁路；Harness MCP 仍保留业务上下文/Interaction/结果能力。
- Claim、Lease renewal、命令业务状态仍由 Platform 权威管理。

验收：网络断开、Lease 过期、Runner 重启、进程自然退出、Runner 本地 kill 等路径均能产生可验证证据或明确降级 E5；旧 Generation 事件不能修改新 Run。

### Phase 2 — 独立 Docker 部署 + Full Interaction Acceptance

- 独立 SEM DB/容器/Workspace 运行期卷部署。
- 必须验收普通任务、Interaction terminate→response→continue、HIR 通知/处置、E3 回传、资源感知准入、服务重启与网络分区。
- 不能只以“跑通一条普通 delivery Run”作为部署完成标准。

### Phase 3 — Session Continuity

- Session Manager 负责跨服务生命周期投影与仲裁；Native Session ID 在实际 Harness 执行主机采集。
- Runner 上报本机 Harness Session 元数据；SEM 不尝试读取 Runner 设备的 CODEX_HOME。
- Process Reattachment、Interaction Continuation、Harness Native Resume 分别验收。
- Resume 默认 false；同一 Native Session ID 不代表跨设备可恢复。

### Phase 4 — Advanced HIR / Cross-Runner Handoff / E6

- 完整 HIR 通知、用户选择、supervised Runner handoff 和受控 E6 风险接受。
- E6 需要权限、二次确认、风险摘要、缓解措施、唯一 successor 绑定和审计。
- Phase 4 扩展 HIR，不再首次创建 HIR 或首次提供 HIR 可见性。

### Phase 5 — Multi-Runner Chaos and Security Acceptance

增加：WSS 中断/重连、旧 boot 进程对账、证据 spool 重放、E3 重复/乱序、E5 卷丢失、E6 单次授权、Interaction 双执行端、shielded queued Run、通知收件人缺失和死信等场景。

## 12. 对原 SEM-02D 文档的强制修订

1. 删除“Runner 重启平台侧无需变更”；改为明确的 Detached → Active reconnect/reconcile。
2. 删除“E4 授权重派”未定义表述；统一采用 E6 Human Risk Acceptance，且不伪装成终止证据。
3. 删除“PID 文件和 logs 同时缺失即可 Done{Lost}”语义；started Run 的证据缺失是 E5。
4. 删除“HIR 到 Phase 4 才完整可用”；Phase 0 提供最小可操作 HIR 和通知收件人。
5. 修正 Session ID 采集位置：Runner 本机由 Runner 收集；SEM-local Executor 在 SEM 主机收集。
6. 明确 Interaction Continuation 默认是 checkpoint/reply 注入 + 新 Session，不是 Native Resume。
7. Detached 不进入 scheduling_shield CHECK；执行屏障由独立表承载，Phase 0 必须有 Migration。
8. B06-D3、queued claim、B3-1/B3-2、retry/requeue 和 handoff 统一调用 dispatchability predicate。
9. Protocol WSS 必须覆盖自然退出、主动终止、租约丢失清理和启动对账的进程证据消息。
10. Phase 2 验收必须包含 Interaction 完整往返与 HIR 可操作，不得只验收普通 Run。

## 13. 评审状态

以上是针对 10 项发现的修正设计提案，尚未获得用户批准。任何新增 E6、通知收件人模型、Execution Control Port、阶段调整及其 Schema/API 变更，均须在用户评审后冻结为 ADR。Phase 0 仍未启动。
