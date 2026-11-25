# SEM-02E — 全量架构收敛基线

- 状态：**Design In Progress — Review Pending**
- 日期：2026-11-25
- 分支：`docs/sem-02e-architecture-convergence`
- 基线：从 GitHub `master` 创建；本文件及同步后的专题文档属于候选设计，不自动成为 Ratified ADR。
- 范围：SEM 独立服务、Platform/SEM/Runner 边界、执行安全、Barrier、HIR、E6、Interaction、进程证据、通知、协议、部署、RabbitMQ 现状、Phase 0–5。
- 实施边界：仅修改架构文档；不修改业务代码、Migration、API、WSS、Dockerfile、Compose 或运行环境；Phase 0 未启动。

## 1. 本轮裁决摘要

| 项目 | 裁决 |
|---|---|
| SEM 部署身份 | SEM 是独立服务，有独立部署单元、数据库、HTTPS API、Runner WSS 控制面和执行运行时；不是 Platform Worker 的可选模块 |
| E6 | 正式提出修订 ADR-SEM-04 与 ADR-SEM-10；仍需最终评审批准，不得伪称已 Ratified |
| HIR | 复用并扩展 `governance.human_intervention`；不另建语义重复的 HIR 主表 |
| E6 决定 | 复用并扩展 `governance.human_consultation` 记录正式人工决定；必须强关联 HIR、Barrier 和唯一 successor |
| 通知 | 保留 `integration.notification` 项目 Feed 与原 `read_at`；新增 `integration.notification_recipient` 承载个人 Inbox、收件人和未分派队列；V1 站内通知与 HIR/Interaction 同事务写入 |
| Execution Barrier | 提升为 Task 作用域；至少记录 task_id、origin_run_id、generation、状态和证据；每个 Task 至多一个 active Barrier |
| 周期性孤儿扫描 | Phase 0 由 Platform Worker 执行纯 DB 周期扫描；不是 SEM 扫描，不调用 SEM/Runner，不依赖 Worker 重启 |
| 进程身份 | Platform 新增 `delivery.task_run_process` 登记 Run+Generation 内有序进程身份；Lease Renewal 只接受当前 active_process_sequence |
| RabbitMQ | 环境中已有独立 RabbitMQ 单实例服务、未做集群。SEM 不部署第二套、不假定 HA；安全权威路径不依赖它。可选用作非权威唤醒/通知加速，但 DB Outbox/Inbox 与 API 对账才是可靠性依据 |
| 状态 | 23 份专题文档必须同步；本轮未完成全文核验前，整体不得标记 Design Complete |

## 2. 服务边界与权威

### 2.1 Platform
Platform PostgreSQL 是 Project/Task/Run/Lease/Generation、Interaction、HIR、Human Consultation、业务通知记录、worker_command 和业务审计的唯一权威。所有 Claim、Generation 变更、Task 级 Barrier 检查和 E6 successor 授权都由 Platform 事务完成。

### 2.2 SEM
SEM 是独立服务，拥有独立数据库和部署生命周期。SEM 负责 Runner 连接、WSS 控制、调度协调、执行端适配、进程观察、证据 spool 接收、执行资源预留、Workspace 路径和本机恢复协调。SEM 不连接、不共享、不查询 Platform PostgreSQL。

### 2.3 Runner 与 Harness
Runner 通过认证 WSS 连接 SEM，监督本机 Harness 进程并报告进程事实。Harness 继续通过 Platform MCP 使用项目上下文、Interaction、Agent Activity、交付与知识业务能力。Runner 不再绕过 SEM 轮询 Platform Claim、命令、ACK 或恢复控制。

### 2.4 服务间通信
Platform Outbox → HTTPS → SEM Inbox；SEM → Platform 版本化 HTTPS API；Runner ↔ SEM WSS。Platform Outbox 仍只有 Platform 一个消费者。两侧不做分布式事务，以幂等、重试、对账和补偿完成恢复。

RabbitMQ 是已存在的独立单实例基础设施，但不是上述权威链路的必要依赖。即使 RabbitMQ 停机，Claim、Lease、Barrier、HIR、进程证据和恢复仍必须由数据库与 HTTPS/WSS 契约保证。不得把 RabbitMQ ACK 当作业务提交、进程退出或 E3 证据。

## 3. Task 级 Execution Barrier

### 3.1 作用域
Barrier 的安全作用域是 Task，而非仅 Run + Generation。Barrier 必须保存：
- `task_id`：Task 级隔离作用域；
- `origin_run_id`、`origin_generation`：产生不确定性的原执行身份；
- `state`：`active`、`risk_accepted_unconfirmed`、`released`；
- 原因、证据分类、创建/更新时间、HIR 关联和审计关联。

同一 Task 同时最多一个未释放 Barrier。建议以部分唯一索引或等价数据库约束实现。新 Run 行、新 Generation、重试、回队、handoff、B06-D3 和普通 queued claim 都不得绕过 Task 级 Barrier。

### 3.2 释放
只有 Platform 接受并验证 E1/E2/E3 对应的可靠终止事实，才能将 Barrier 释放。HIR closed、Interaction continued、Cleanup completed、Lease expired、Runner offline、Workspace missing、RabbitMQ message ACK 均不能释放 Barrier。

### 3.3 E6
E6 不释放 Barrier。Barrier 继续处于 `risk_accepted_unconfirmed`，明确表示旧进程仍可能运行。E6 仅允许一个预先绑定的 successor 执行对象。

## 4. E6：人类风险接受

E6 是独立的人工风险授权类别，不是终止证据，不是 E1/E2/E3 的子类。

正式授权必须满足：
1. 操作者具有专门的高风险授权权限；
2. 展示旧进程可能仍运行及外部副作用风险（Git push、外部 API、LLM 费用、共享资源等）；
3. 明确理由、残余风险摘要、缓解措施；
4. 二次确认并写入不可变审计；
5. 与一个 HIR、一个 Task Barrier 和一个唯一 successor_run_id 绑定；
6. successor 在授权事务内预分配或以等价方式原子保留，唯一约束防止重复授权；
7. successor 仍必须通过正常 Platform Claim、设备授权和新 Generation；SEM 不得绕过 Platform 授权；
8. 旧 Barrier 不释放；不得把 E6 记录序列化成 process.terminated、E3 或 cancel ACK。

因此正式修订提案为：
- ADR-SEM-04：E1/E2/E3 才能自动安全重派；E4/E5 隔离；E6 是唯一受控人工风险例外，允许单一 successor，但不宣称安全终止、不释放旧 Barrier。
- ADR-SEM-10：HIR 是人工执行处置的统一入口；HIR 可关联 Interaction 与 Human Consultation；HIR 的关闭不是 Barrier 释放。E6 决定必须通过正式 Human Consultation 记录。

这两项是 Proposed Amendment，待最终用户冻结。

## 5. 现有治理表裁决

本轮采用“复用现有治理实体，扩展字段与约束”的方向，不创建平行的 HIR / consultation / notification 主表。

### 5.1 governance.human_intervention
复用为 HIR 主实体。需要审计现有 schema、迁移、路由和读写路径后再决定字段。逻辑上至少表达 Task/Run/Generation/Barrier、类别、严重性、状态、责任人、收件人、创建原因、证据引用、处置结果、关闭原因和审计时间。不得仅凭表名推断当前字段已满足要求。

### 5.2 governance.human_consultation
复用为正式人工决定实体。保留现有四态、决定四元组 CHECK 和 supersede 链。E6 是一种明确类型的正式决定，增加或关联 HIR、Barrier、Task、唯一 successor_run_id、操作者、决定时间、原因和风险摘要。必须检查现有 CHECK / FK / 唯一约束，不能破坏现有咨询语义。

### 5.3 integration.notification
复用项目级通知 feed，保留 read_at 行级已读语义。补充 recipient 明确性和投递状态。通知产生必须与 Interaction/HIR 创建处于同一业务事务 Outbox 语义；实际外部投递可异步。缺少收件人时进入项目级未分派队列并告警，不得静默丢弃。通知失败不得回滚 HIR 或 Interaction 业务状态。

是否需要独立 notification_delivery 表，必须依据完整 schema 和当前消费者审计决定；不可在未对账前新增同义表。

## 6. Phase 0 周期性孤儿发现与原子处置

Phase 0 必须实现 Platform DB-only 周期扫描器，部署在 Platform 侧，不依赖 SEM、Runner 在线、Session Manager 或 Worker 重启。

扫描候选至少覆盖：
- `claimed` / `running` 且 Lease 已过期并超过配置宽限期；
- Interaction shield 为 `none`；
- 当前 Task 没有已释放以外的 active Execution Barrier；
- 没有足以构成 E1/E2/E3 的终止证据；
- 不因 runner 项目、普通 claim 候选过滤或 executor 类型而漏扫。

处置在单一 Platform DB 事务内完成：锁定 Task/Run（遵循既有锁序）、重新验证 generation/lease/shield/barrier/evidence、创建或复用 Task Barrier、创建或关联 HIR、记录审计和通知 Outbox。不得先回队再异步补 Barrier。B06-D3 并入该统一发现与处置流程，不再保留独立的危险回队旁路。

扫描器必须周期运行、有运行心跳、可观测扫描水位、可重复执行、并发安全、幂等。启动时 reconcile 只能作为补充，不能作为唯一触发器。宽限期是检测策略，不是进程终止证据。

## 7. 统一 Dispatchability

Platform 定义唯一权威 `is_dispatchable(task_id, run_id, generation, actor/device, operation)` 谓词，所有路径在锁内重验：
- 普通 queued claim；
- claimed lease recovery；
- B3-1 / B3-2；
- B06-D3；
- retry / requeue；
- orphan reconciliation；
- handoff；
- E6 successor；
- SEM-local 与 Runner 执行适配器触发的任何新进程。

谓词至少检查 Task 级 active Barrier、Interaction scheduling shield、Run 状态、Lease/Generation、设备/项目授权、并发互斥和 operation 专用约束。所有路径必须调用同一实现或同一事务内等价共享函数，不得复制局部检查。任何检查结果与实际写入之间必须由锁/约束保护。

## 8. Run + Generation 内 Process Identity 序列

一个 Run + Generation 可以先后产生多个进程身份，不能把 Run+Generation 与单个 PID 永久一一绑定。

每个进程身份至少包括：
- `process_sequence`（Run+Generation 内单调递增）；
- `boot_id`；
- OS process identity（PID + creation identity / handle-derived stable identity）；
- Harness kind / launch identity；
- 启动、退出、观察时间；
- 产生原因：initial_start、interaction_continue、recovery_restart、cleanup 等；
- 对应 command_id（如由命令触发，可选）。

Interaction continue 的语义是 checkpoint + response 注入并启动 Fresh Session / 新进程。Runner 必须在启动成功后发送 `continuation.consumed`，登记新的 process_sequence 和 identity。续租身份校验必须接受当前活动序列成员，而非只认首次启动 PID。

迟到的旧进程 terminate/exit evidence 必须按精确 process identity + sequence 归属。它只能关闭其自身进程观察，不得覆盖较新的活动进程。Run+Generation 的执行终止只有在该序列中所有应受监督的进程均有可信终止证明后才能判定。必须有“terminate 的旧进程退出证据在 continue 新进程启动之后迟到”的测试。

## 9. Process Evidence、E3 和 Detached Recovery

Runner 将进程退出证据先写入本机持久 spool，再经 WSS 上报；SEM 持久 ACK 前不得删除 spool。证据来源包括自然退出、命令终止、lease-loss cleanup、startup orphan cleanup、shutdown 和 boot transition。Lease 过期或 generation 已变化不阻止上报历史事实，但 Platform 只将证据用于精确 Run/Generation/Process Identity，不得影响新 generation。

统一消息名：
- `runner.process.exit`：单个进程退出事实；
- `runner.process.reconciled`：重启后对历史进程的 alive / exited-with-proof / unknown 对账；
- `runner.reconnect_sync`：boot identity、活动进程清单、spool 引用与 connection epoch；
- `continuation.consumed`：Interaction 回复注入并成功启动新进程的回执。

`command_id` 对自然退出可选。不得以 command_id 缺失单独否定自然退出证据；但破坏 Run/Generation/Process Identity 归属的证据必须拒绝或隔离为诊断证据。D-09 必须改成：校验证据是否匹配 Run+Generation 内已登记的 Process Identity 序列；不能要求所有进程退出都匹配同一个 command_id。

Runner 重启后状态：Active → Detached → Reconciling → Active / Terminated / Quarantined。Detached/Reconciling 的权威状态由 SEM 自身持久化，不由 Session Manager 直读 Platform DB 投影。恢复前必须验证 Runner 设备身份、boot identity、进程序列、当前 Platform Lease/Generation 和 SEM connection epoch。身份/证据不完整进入 E5/HIR，不自动重派。

## 10. Interaction 双执行适配器

Interaction 的 terminate / continue 是执行控制，不能只存在 Runner command consumer。

- Runner 执行：Platform worker_command → SEM command_delivery → WSS → Runner Supervisor。
- SEM-local 执行：Platform worker_command → SEM Execution Control Port → CodexExecutor adapter。

两个 adapter 必须支持 terminate、continue_with_response、process observation、process exit evidence、continuation consumed。命令接收 ACK、命令执行结果、进程退出证据、continuation consumed 是四个不同事实。无消费者时必须失败可见，不能伪装 delivered/acked。

SEM-local Worker 重启时必须恢复 awaiting-interaction/awaiting-continue 状态；人工等待期间按明确策略续租，且不得把仍有 shield 的 Run 误判为 Done/Success/Lost 或自动回队。终态扫描和 recovery_lost 必须调用统一 dispatchability / interaction guard。

## 11. HIR / Interaction / Cleanup / Notification 生命周期

HIR、Interaction、Human Consultation、Cleanup Need、Execution Barrier 和 Notification Recipient 是不同实体：
- Interaction：Agent 请求用户输入/决策/权限；continue 产生 continuation。
- HIR：执行异常、失联、风险处置、接管协调的人工工作项。
- Human Consultation：正式人工决定，包括 E6 风险接受。
- Cleanup Need：Workspace / 进程清理任务。
- Execution Barrier：Task 级物理执行不确定性安全约束。
- Notification：`integration.notification` 保持项目级 Feed；`integration.notification_recipient` 负责每位收件人的 Inbox 状态与未分派队列。父表 `read_at` 语义不变。

HIR 主体复用 `governance.human_intervention`，用 `record_kind=action|hir` 区分既有干预动作与 HIR 工作项；HIR 状态域以 state-machines.md 为唯一规范。HIR closed 不自动释放 Barrier。Interaction 创建与 HIR 创建必须在同一 Platform 事务中写入 Feed + Recipient 行；V1 站内 Inbox 不需要 RabbitMQ 或异步投递成功才能可见。

## 12. RabbitMQ 使用边界

已知环境事实：RabbitMQ 是一个已存在的独立服务，单实例、没有集群。

本架构不要求新增 RabbitMQ，也不把它作为 SEM 的安全关键依赖。V1 权威可靠性仍由 Platform Transactional Outbox、Platform–SEM HTTPS、SEM Inbox、幂等处理和 API reconciliation 保证。RabbitMQ 可以在后续单独批准后用于非权威的 wake-up / notification acceleration，但必须满足：
- 消息只是提示，消费者始终从权威 DB/API 读取真实状态；
- 丢消息、重复、乱序、服务停机均不改变业务正确性；
- 不承担 Claim、Lease renewal、Barrier、HIR 决定、E3 证据或唯一执行权；
- 单实例不可用时自动退回 DB polling / Outbox retry，不阻塞安全恢复；
- 不把 broker ACK 等同于业务处理完成；
- 不把现有 RabbitMQ 的存在描述为 HA/集群能力。

在没有用户单独批准前，SEM V1 不新增 RabbitMQ 必需依赖，不改变 ADR-SEM-19 的 HTTPS Outbox/Inbox 主路径。

## 13. 统一协议与实现名称

- Platform–SEM API 前缀统一候选为 `/internal/sem/v1/`；删除 `/internal/v1` 旧候选。最终 OpenAPI/DTO 在实施前冻结。
- WSS process 消息统一使用第 9 节名称，不再并存 `process.terminated`、`runner.process.exit` 等别名。
- Process Identity 字段、ACK 类型和 E3 证据格式由 `protocol-contracts.md` 唯一规范。
- HIR 状态域由 `state-machines.md` 唯一规范；其他文档只引用，不再各自定义枚举。
- Detached / Reconciling 不加入 `scheduling_shield` CHECK；由 SEM 私有状态和 Platform Task Barrier 分别承载。
- 所有图表移除 `Done{Lost}` 自动重派路径；增加 `Uncertain` / E5 quarantine。
- Runner 不再使用 MCP Claim/command polling/ACK 作为控制旁路。
- 所有章节号在专题文档内唯一且连续。

## 14. Phase 0–5 统一路线

| Phase | 名称 | 必须交付 |
|---|---|---|
| 0 | Safety + Minimum Human Intervention | Task Barrier、复用治理表、最小 HIR/通知、周期 DB orphan scanner、统一 dispatchability、Platform Process Registry + active sequence fence、process-bound Lease Renewal、Interaction 双 adapter、安全凭据盘点、SEM-local waiting/restart 修复 |
| 1 | SEM Control Plane + Runner E3 + Detached Recovery | 独立 SEM DB/API/WSS、Runner process spool、E3 evidence 转发、将 Phase 0 临时 Runner MCP process-control adapter 切换为 SEM WSS + Platform HTTPS、Detached reconnect/reconcile、服务身份与 Claim 幂等 |
| 2 | Independent Deployment + Full Interaction Acceptance | SEM 独立主机部署、Platform/SEM 数据库隔离、全 Interaction terminate/continue 端到端、故障恢复 |
| 3 | Session Continuity | Session Manager 采集/恢复；Native Resume 默认 false；Fresh Session continuation 明确验收 |
| 4 | Advanced HIR / Cross-Runner Handoff / E6 | 高级 HIR、监督模式选择、跨 Runner handoff、E6 风险授权与唯一 successor |
| 5 | Multi-Runner Chaos Acceptance | 多 Runner、多 OS、网络分区、服务重启、资源压力、撤权、无双重执行混沌验收 |

Phase 0 不依赖 RabbitMQ，不依赖 Session Manager，不依赖 SEM 独立部署完成。Phase 编号以本表为唯一基准。

## 15. 设计一致性硬门槛

在所有 23 份专题文档完成正文同步前，不得标记 Design Complete。同步范围：
1. README
2. decision-record
3. deployment-topology
4. worker-role-separation
5. session-manager-design
6. execution-safety
7. runner-supervision-and-handoff
8. domain-model
9. protocol-contracts
10. state-machines
11. failure-recovery
12. security-model
13. operational-runbook
14. testing-and-acceptance
15. migration-roadmap
16. consistency-review
17. code-contract-mapping
18. sem-02d-closure-design-proposal
19. sem-02d-review-package
20. sem-02d-final-architecture-review
21. resource-aware-runner-scheduling
22. service-protocol-security-and-persistence
23. sem-02d-review-findings-corrective-design

逐份审查必须清除冲突定义，而非仅在文末追加“以新节为准”。必须复核表结构、代码映射、图表、消息名、API 前缀、状态枚举、Phase 编号、章节编号和所有引用。未完成的项目必须在一致性矩阵标为 Open，不得写成“已一致”。

## 16. 明确未做事项

本次没有修改业务代码、Migration、API、WSS、Dockerfile、Compose、Worker/Runner 主循环或部署配置；没有创建新表；没有连接或配置 RabbitMQ；没有启动 Phase 0。本文所有模型均为候选架构设计，等待整体评审。


## 17. SEM-02E follow-up audit — additional blockers

A read-only fetch of the current migration baseline and application source found that the three-table reuse direction needs a more precise schema contract. See [SEM-02E Schema and Protocol Gap Register](./sem-02e-schema-and-protocol-gap-register.md).

- `governance.human_intervention` currently stores executed intervention actions (veto/rollback/freeze/unfreeze/mode_switch/policy_change/rollback_failed), not open HIR work items. Reuse remains the approved direction, but must preserve the distinction between HIR lifecycle and action history through a deliberate discriminator/refactor.
- `governance.human_consultation` has four existing states and completeness CHECKs; E6 needs typed decision scope, HIR/Barrier/successor anchors and stronger non-null/unique integrity without weakening ordinary consultation behavior.
- `integration.notification` remains the project Feed with existing `read_at`; SEM-02F proposes `integration.notification_recipient` for per-principal Inbox membership and explicit unassigned queue. Existing Feed readers/writers remain compatible.
- `delivery.task_run_cleanup` is keyed only by Run and models cleanup lifecycle; it cannot be reused as the multi-process identity/exit-evidence ledger.
- Platform must persist/fence the active process sequence because Platform owns Lease Renewal and cannot query SEM DB. SEM-02F now specifies the candidate `delivery.task_run_process` registry, `task_run.active_process_sequence` fence and authenticated registration/continuation/renewal contract; executable SQL/API remains a review blocker.

These findings supersede any wording elsewhere that suggests the existing tables are already a drop-in HIR/E6/notification implementation. SEM-02F now specifies candidate physical contracts; they remain unratified until the full review and exact SQL/API specification are approved.


## 18. SEM-02F executable contract baseline

The detailed physical and protocol proposal is [SEM-02F — Executable Physical and Protocol Contracts](./sem-02f-executable-physical-and-protocol-contracts.md). It supersedes the open-ended implementation wording in this document for the following candidate contracts:

- `delivery.task_execution_barrier`: one unreleased Barrier per Task; only the exact E6-bound successor can pass a `risk_accepted_unconfirmed` Barrier.
- `governance.human_intervention`: `record_kind=action|hir`; preserve existing action rows while adding the seven-state HIR lifecycle.
- `governance.human_consultation`: typed E6 anchors and one unique successor, with E6-specific restrictive FK semantics.
- `integration.notification` + `integration.notification_recipient`: preserve the project Feed and parent `read_at`; add per-principal Inbox membership and an explicit unassigned queue.
- `delivery.task_run_process` plus `task_run.active_process_sequence`: Platform-side process identity fence used by Lease Renewal and continuation.
- Platform Worker periodic DB-only orphan scanner: startup scan is an optimization only; B06-D3 direct requeue is removed.
- RabbitMQ remains an existing independent single-instance service without clustering. It is optional for non-authoritative wake-up only and not required for V1 correctness.

These remain candidate specifications. The exact SQL migration, route/consumer changes and API schemas require review; Phase 0 remains Not Started.


## 19. SEM-02G database and API contract draft

[SEM-02G](./sem-02g-database-and-api-contract-draft.md) contains SQL-shaped draft definitions for Task Barrier, HIR discriminator, E6 consultation anchors, Notification Recipient, Process Registry, command sequence reservation, and Platform–SEM/Runner API payloads. It remains a review artifact, not an executable migration.

Phase dependency clarification: Platform-side Process Registry and process-bound Lease Renewal fencing are Phase 0 prerequisites because Interaction continue must safely rotate process identity even before SEM WSS is deployed. During Phase 0 the current Runner control adapter may temporarily call the Platform process-control API; Phase 1 replaces that transitional route with Runner→SEM WSS→Platform HTTPS and removes the direct Runner MCP control path. This temporary migration adapter is not the target architecture.


## 20. SEM-02H DDL integrity review

[SEM-02H — DDL Integrity and Transaction Review](./sem-02h-ddl-integrity-and-transaction-review.md) reviews SEM-02G against the current master schema and identifies concrete SQL integrity defects. SEM-02G remains a draft; do not author migrations from it until the P0/P1 findings, process evidence ledger, E6 atomicity, notification Inbox semantics and global transaction lock graph are closed.

The review also updates the schema evidence baseline to current master `d0e72fa6805aebeadf1b282e430deba493072fd6`. No code or migration changes were made.

## 21. SEM-02I corrected schema/API candidate

[SEM-02I — Corrected Platform Schema and Process API Candidate](./sem-02i-corrected-platform-schema-and-process-api-candidate.md) consolidates the proposed HIR discriminator, Task Barrier, E6 consultation binding, append-only process evidence ledger, per-principal Inbox and process registration/continue/exit/Lease Renewal API shapes.

SEM-02I is a candidate only. Its transaction lock graph is explicitly not approved because current code has Run↔Interaction lock inversion and orphan reconciliation is not atomic. See SEM-02H §7. Do not create migrations or start Phase 0.
