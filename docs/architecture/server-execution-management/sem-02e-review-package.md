# SEM-02E — 全量架构收敛评审包

- 状态：**Review Pending — Changes Required**
- 主基线：[sem-02e-architecture-convergence.md](./sem-02e-architecture-convergence.md)
- 分支：`docs/sem-02e-architecture-convergence`
- 本包不是 ADR 冻结，也不是 Phase 0 实施授权。

## 1. 本轮评审输入与裁决

已接受上一轮审查结论：原十项问题中 #3/#5/#8/#9 已闭合；#1/#2/#6/#7/#10 方向正确但仍有缺口。另新增 P0 A/B/C、P1 D/E/F/G 和 P2 状态问题。本轮以 SEM-02E 主基线统一修订。

### 用户已明确裁决

| 事项 | 决策 |
|---|---|
| E6 | 作为 ADR-SEM-04/10 的正式修订提案；E6 是人类风险接受，不是终止证据，不释放旧 Barrier，只授权唯一 successor |
| HIR | 复用并扩展 `governance.human_intervention` |
| E6 决定 | 复用并扩展 `governance.human_consultation` |
| 通知 | 复用并扩展 `integration.notification`，保留项目 feed/read_at；投递状态和 recipient 需完整设计 |
| Barrier | Task 作用域；新 Run 行不得绕过旧 Task Barrier |
| RabbitMQ | 已有独立单实例服务、无集群；不作为 SEM 安全关键依赖，不等于不存在，也不假设 HA |

## 2. P0 关闭标准

### A — 周期性孤儿检测
Phase 0 Platform DB-only 周期扫描；候选包括 claimed/running + lease expired + grace + shield none + 无 E1–E3。锁内同事务创建/复用 Task Barrier、HIR、audit 和 notification Outbox。B06-D3 并入同一机制。不能依赖 Worker 重启、Session Manager 或 SEM 上线。

### B — Task 级 Barrier + E6 授权实体
Barrier 作用域 Task；唯一 active 约束；所有新 Run 行创建、claim、requeue、retry、handoff、E6 successor 均检查。E6 决定复用 human_consultation，绑定 HIR、Barrier、Task、操作者、时间、理由、风险摘要和唯一 successor_run_id。授权与 successor 预分配必须原子完成。

### C — Run+Generation 进程身份序列
支持 initial_start、interaction_continue 等多个有序 process identity。continue 消耗回复后登记新序列。续租校验当前活动序列；迟到的旧进程退出证据不得关闭新进程。必须增加 late-terminate-evidence-after-continue 测试。

## 3. P1 关闭标准

- D：SEM-local terminate/awaiting-continue 等待期与 Worker restart 不得错误终态化；续租、shield 和 awaiting-continue 恢复语义写入 adapter 契约。
- E：ADR-SEM-04/10 正式提出修订，审批前仍标 Review Pending。
- F：完整审计既有三张表、所有迁移、FK/CHECK/索引、routes 和消费者；复用优先，禁止平行重复主表。
- G：所有 23 份专题文档正文同步；不允许“文末追加，以新节为准”。

## 4. 跨文档强制统一

| 维度 | 唯一规范 |
|---|---|
| API prefix | `/internal/sem/v1/`；删除 `/internal/v1` 备选 |
| WSS process events | `runner.process.exit`、`runner.process.reconciled`、`runner.reconnect_sync` |
| Continuation receipt | `continuation.consumed` |
| HIR 状态 | 只在 state-machines.md 定义一套状态域 |
| Detached / Reconciling | SEM 私有持久状态；不是 scheduling_shield 值 |
| Barrier | Task 级 Platform 权威 |
| Process Identity | Run+Generation 内有序序列，不是单 PID |
| Unknown/lost process | E5/Uncertain，不得 Done{Lost} 后自动重派 |
| Dispatchability | 所有 claim/recovery/requeue/create/handoff 路径共用事务内谓词 |
| Phase | 0 Safety+Minimum HIR；1 Control Plane+E3+Detached；2 Independent Deployment+Full Interaction；3 Session Continuity；4 Advanced HIR/Handoff/E6；5 Chaos |
| RabbitMQ | 已存在单实例；非权威、非安全关键、非 HA；可选唤醒加速需另批 |

## 5. 23 份文档同步矩阵

| 文档 | 必须核验的正文内容 | 状态 |
|---|---|---|
| README | 独立 SEM、RabbitMQ 现状、Task Barrier、阶段入口 | Updated |
| decision-record | ADR-04/10/12/19 修订提案与状态 | Updated |
| deployment-topology | SEM 独立服务、RabbitMQ 非依赖、数据边界 | Updated (targeted rewrite; final cross-check pending) |
| worker-role-separation | Platform DB scanner、SEM local adapter、Outbox 单消费者 | Updated (targeted rewrite; final cross-check pending) |
| session-manager-design | SEM 私有 Detached 状态；process sequence；Native Resume 限制 | Updated (targeted rewrite; final cross-check pending) |
| execution-safety | Task Barrier、E5、E6、周期 scanner、Uncertain | Updated (targeted rewrite; final cross-check pending) |
| runner-supervision-and-handoff | process sequence、E6、HIR、handoff | Updated (targeted rewrite; final cross-check pending) |
| domain-model | HIR/consultation/notification 复用、Task Barrier、process identity | Updated (targeted rewrite; final cross-check pending) |
| protocol-contracts | API/WSS 名称、ACK、spool、sequence、RabbitMQ | Updated |
| state-machines | 唯一 HIR/Barrier/Detached/Process state machines | Updated (targeted rewrite; final cross-check pending) |
| failure-recovery | 周期 orphan scanner、Detached、迟到证据、卷丢失 | Updated (targeted rewrite; final cross-check pending) |
| security-model | E6 权限、服务身份、证据完整性、RabbitMQ边界 | Updated (targeted rewrite; final cross-check pending) |
| operational-runbook | scanner、spool、RabbitMQ 单实例降级、HIR | Updated (targeted rewrite; final cross-check pending) |
| testing-and-acceptance | A/B/C/D 回归与混沌验收 | Updated (targeted rewrite; final cross-check pending) |
| migration-roadmap | 唯一 Phase 0–5 编号及 schema 前置依赖 | Updated (targeted rewrite; final cross-check pending) |
| consistency-review | 23 份正文逐项审查，未完成不得 Complete | Updated (targeted rewrite; final cross-check pending) |
| code-contract-mapping | 代码路径、事务边界、adapter、scanner | Updated (targeted rewrite; final cross-check pending) |
| sem-02d-closure-design-proposal | 删除旧独立 HIR 表提案、更新 Barrier/E6/Phase | Updated (targeted rewrite; final cross-check pending) |
| sem-02d-review-package | 历史评审状态指向 SEM-02E | Updated (targeted rewrite; final cross-check pending) |
| sem-02d-final-architecture-review | 撤回旧 Design Complete 与阶段冲突 | Updated (targeted rewrite; final cross-check pending) |
| resource-aware-runner-scheduling | 不把资源/ broker 状态当终止证据 | Updated (targeted rewrite; final cross-check pending) |
| service-protocol-security-and-persistence | API prefix、process evidence、独立 DB、RabbitMQ | Updated (targeted rewrite; final cross-check pending) |
| sem-02d-review-findings-corrective-design | 修订为历史记录并链接本规范 | Updated (targeted rewrite; final cross-check pending) |

> Updated 仅表示已对该文件进行本轮定向修改，不代表全量正文审计已通过。Pending 文档仍是冻结阻断项。

## 6. 最终冻结门槛

只有当 23 份文档逐份完成正文重写/冲突清除，并通过以下检查，才可提交最终架构冻结：
- 所有实体/表名/约束/外键/唯一性一致；
- 所有状态机的状态域、转移和终态语义唯一；
- 所有协议消息名、字段、ACK 层级、API prefix 唯一；
- 所有流程图不含危险 Done{Lost} 重派；
- 所有 Phase 依赖一致；
- 章节编号唯一；
- 代码映射中的路径和当前代码现状经过重新只读核验；
- 全新空库初始化、并发、重复事件、迟到证据、Worker/SEM/Runner 重启、RabbitMQ 停机均有验收用例。

本轮仍为 Changes Required。Phase 0 未启动。


## 7. Additional schema/protocol blockers found after the first rewrite

The current migration baseline proves that the selected reuse direction is not a drop-in mapping. SEM-02F now proposes the concrete shape: `human_intervention` discriminator `record_kind=action|hir`; typed E6 anchors on `human_consultation`; `notification_recipient` as a child of the existing project Feed; Task Barrier table; and Platform process identity registry. See [SEM-02F](./sem-02f-executable-physical-and-protocol-contracts.md) and [schema gap register](./sem-02e-schema-and-protocol-gap-register.md).

Platform-side active process-sequence fencing remains a P0 approval item. SEM-02F specifies the candidate registry, active sequence pointer, continuation reservation and process-bound Lease Renewal contract; exact migration DDL, API schemas and lock order still need review.

The PR remains **Changes Required**. No Phase 0 authorization.


## 8. SEM-02F implementation-specification progress

SEM-02F turns the prior open design gaps into concrete candidate contracts:

- Task Barrier: one unreleased row per Task, with an exact E6 successor exception.
- HIR: existing `human_intervention` with a record discriminator; action history remains distinguishable from HIR lifecycle.
- E6: typed anchors on `human_consultation`, one E6 per Barrier and one successor.
- Notification: existing project Feed remains unchanged; `notification_recipient` stores per-principal Inbox and unassigned queue.
- Process identity: Platform-owned `task_run_process` and active sequence fence.
- Orphan scanner: periodic Platform DB-only loop; no dependency on SEM, Runner or RabbitMQ.
- Dispatchability: a single transaction-scoped predicate covers Run creation, claim, recovery and requeue.

These are candidate contracts, not Ratified ADRs or implementation authorization. Remaining blockers: exact DDL and lock-order review; exhaustive direct Run INSERT/notification route audit; API/OpenAPI schemas; and full cross-document conflict elimination.


## 9. SEM-02H DDL integrity review

SEM-02H has identified P0 relational defects in SEM-02G: HIR Run-to-Task FK mismatch, missing unique target for the E6 HIR composite FK, a PostgreSQL CHECK NULL loophole allowing Barrier release without an evidence class, and no mandatory formal E6 consultation reference on a risk-accepted Barrier. It also specifies an append-only process evidence ledger, notification Inbox normalization, event-id persistence, continuation race serialization and a required global lock graph.

The review baseline is current master `d0e72fa6805aebeadf1b282e430deba493072fd6`; SEM-02G's original `4bc78620` declaration was stale. **Changes Required** remains the overall status. No migration or Phase 0 authorization.

## 10. SEM-02I corrected schema/API candidate

SEM-02I consolidates the corrected relational model and process API shapes. It does not close the implementation gate: the source-level audit found an existing Run↔Interaction lock inversion (`report_interaction` Run→Interaction vs `retry_interaction` Interaction→Run), and `reconcile_orphans` still performs Run/Task recovery without a single Barrier/HIR transaction. These must be corrected and concurrency-tested before migration authoring.
