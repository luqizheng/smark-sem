# SEM V1 Architecture Consistency Review — SEM-02E

- 状态：**Changes Required / Review Pending**。
- 本轮基线：[SEM-02E 全量架构收敛](./sem-02e-architecture-convergence.md)。
- 本文件不再声称专题文档“已 stated consistently”；23 份正文同步尚未全部完成。
- 未修改业务代码、Migration、API、WSS、Dockerfile、Compose 或 Runner/Worker 主循环。

## 1. 当前已明确的跨文档不变式

1. SEM 是独立服务，拥有独立数据库和部署单元；不是 Platform Worker 的可选模块。
2. Platform 是 Run/Lease/Generation、HIR、Human Consultation、worker_command 和业务审计权威。
3. SEM 不直连 Platform PostgreSQL；Platform Outbox → HTTPS → SEM Inbox；Runner ↔ SEM WSS。
4. RabbitMQ 已存在，为独立单实例、无集群；不是 SEM 安全关键依赖。权威正确性由 DB Outbox/Inbox、HTTPS API、幂等和对账保障。
5. Task 级 Barrier 阻止所有新 Run 行/Generation 绕过旧执行不确定性。
6. E1/E2/E3 是终止事实；E4/E5 隔离；E6 是人类风险授权，不释放 Barrier。
7. HIR 复用 governance.human_intervention；E6 决定复用 governance.human_consultation；通知复用 integration.notification。
8. Phase 0 有 Platform DB-only 周期孤儿扫描，B06-D3 合并；不依赖 Worker 重启或 Session Manager。
9. Run+Generation 支持有序 Process Identity 序列；Interaction continue 注册新身份；迟到旧证据不关闭新进程。
10. Detached/Reconciling 属于 SEM 执行侧状态，不属于 scheduling_shield，也不由 SEM 直读 Platform DB 投影。
11. 所有 dispatch/recovery/requeue/new Run/handoff/E6 successor 路径共用 Platform 事务内 dispatchability predicate。
12. Workspace 卷丢失不能证明进程死亡；已 started 且证据缺失必须 E5。
13. Interaction 双 adapter（Runner WSS 与 SEM-local CodexExecutor）均必须有 terminate/continue/process evidence/continuation consumer。
14. Native Resume 默认关闭；Fresh Session continuation 与 Native Resume 分开。
15. 唯一 Phase 编号以 SEM-02E §14 为准。

## 2. 23 份文档逐项状态

详见 [SEM-02E Review Package §5](./sem-02e-review-package.md#5-23-份文档同步矩阵)。当前 README、decision-record、protocol-contracts、execution-safety、state-machines、migration-roadmap 和本文件已定向更新；其他专题仍需逐份正文审查和冲突清理。

## 3. 仍需关闭的专项一致性问题

- 数据库：核验现有 human_intervention / human_consultation / notification 的完整 DDL、迁移链、索引、CHECK、FK、routes、读写者；据此决定字段扩展与投递状态持久化。
- HIR：所有旧七态/四态/AwaitingUserAction 描述必须删除或映射到 state-machines.md 的唯一状态域。
- E6：ADR-SEM-04/10 必须以 Proposed Amendment 方式登记；批准前不得写成已 Ratified。
- Barrier：所有 Run 级 Barrier 描述改为 Task 作用域；检查三个新 Run 创建点和所有 claim/requeue 入口。
- WSS：移除 process.terminated 别名；统一 process.exit / reconciled / reconnect_sync / continuation.consumed。
- API：统一 /internal/sem/v1/，删除 /internal/v1。
- Phase：统一 Phase 0–5；旧 Phase 2/4 对调内容必须清除。
- 图表：删除 Done{Lost} 自动重派；加入 Uncertain/E5 和 Task Barrier。
- SEM 独立性：Detached 状态不得依赖 Session Manager 直读 Platform DB。
- 章节编号：检查重复章节并修正所有目录链接。
- RabbitMQ：不得写成“环境没有 RabbitMQ”；不得写成 HA/集群；不得将 broker ACK 作为业务/进程证据。

## 4. Design Complete 门槛

只有在以下条件全部满足时，才可标记 Design Complete：
1. 23 份文档正文完成同步，没有“文末追加，以新节为准”的冲突；
2. 表名、字段、约束、索引、状态域和所有权唯一；
3. 所有协议消息名、API prefix、ACK 语义唯一；
4. 所有状态机和 Phase 编号唯一；
5. 所有流程图符合 E1–E6 与 Task Barrier 语义；
6. 代码映射引用在当前实现 HEAD 重新核验；
7. 全新空库、并发、重复消息、迟到证据、Worker/SEM/Runner/RabbitMQ 重启均有验收标准；
8. 用户完成整体评审并明确冻结。

当前结论：**Changes Required**。Phase 0 Not Started。


## 5. Newly found blockers in SEM-02E internal review

- **ADR-SEM-14 conflict:** prior wording made every ACK depend on OS process-handle exit. Amend it to separate command receipt, command result, E3 process-exit evidence and continuation-consumed receipt. Natural exit has no command_id.
- **ADR-SEM-16 conflict:** old E4 scheduling-shield wording conflicts with the new Task Barrier model. Interaction shield and execution Barrier are distinct and both must be checked by one Platform transaction predicate.
- **Platform process-sequence fence:** SEM owns OS observations, while Platform owns Lease Renewal. The active process sequence must be registered/advanced through an authenticated Platform API and persisted/fenced by Platform; SEM DB-only sequence state is insufficient.
- **HIR carrier semantic fit:** repository evidence says current governance.human_intervention records intervention actions (veto/rollback/freeze), not an open work-item lifecycle. Reuse remains the chosen direction, but implementation must explicitly remodel/extend the table without conflating HIR lifecycle and action history.
- **Notification recipient/delivery:** SEM-02F now specifies preserving `integration.notification` as project Feed and adding `integration.notification_recipient` for per-principal Inbox/unassigned queue. Existing read_at semantics remain unchanged. Exact migration and consumer update remain open.

The review status remains **Changes Required**. These findings are not approved ADRs and do not authorize Phase 0.


## 6. Evidence baseline and unresolved implementation contracts

The schema audit is recorded in [sem-02e-schema-and-protocol-gap-register.md](./sem-02e-schema-and-protocol-gap-register.md), with concrete candidate physical contracts in [SEM-02F](./sem-02f-executable-physical-and-protocol-contracts.md): `human_intervention` discriminator, E6 typed anchors, `notification_recipient`, Task Barrier and Platform process registry. These proposals are not yet approved for migration.

The Platform active process-sequence fence is specified as a candidate in SEM-02F; it remains a P0 approval item until exact DDL, API schemas and lock ordering are reviewed.

Status remains **Changes Required**. The 23-file body audit is not considered complete merely because all files were modified.


## 7. SEM-02F cross-document audit status

The following concepts now have a single candidate physical definition in SEM-02F and are referenced by the domain/state/protocol/roadmap/test documents: Task Barrier, HIR discriminator, E6 consultation anchors, Notification Recipient, Platform process identity sequence, periodic Platform DB-only orphan scan, and RabbitMQ non-authoritative boundary.

Still not closed:
- Full read/write/route audit for every `human_intervention`, `human_consultation` and notification consumer.
- Exhaustive direct Run INSERT inventory and lock-order review.
- Executable SQL migration and API/OpenAPI schemas.
- Historical SEM-02D documents contain intentionally obsolete proposals; each must be clearly marked historical/superseded.
- Final full 23-document scan for stale prose, diagrams, section numbers and Phase references.

Status remains **Changes Required**. No ADR freeze or Phase 0 authorization.


## 7. SEM-02H/02I follow-up and branch-wide terminology check

- SEM-02H added source-level transaction evidence. The current code has a confirmed lock-order inversion candidate: Interaction report is Run→Interaction, while retry/cancel are Interaction→Run. This must be reproduced with two concurrent transactions and fixed before Task Barrier implementation.
- Current `reconcile_orphans` is not atomic with Task state and does not create Barrier/HIR/notification in one transaction; Phase 0 must use a new Platform DB transactional scanner.
- SEM-02I consolidates the corrected schema/API candidate. It remains non-normative until the lock graph, complete DDL, notification/governance reader-writer audit and OpenAPI security contract are closed.
- The review branch has been synchronized with current master; merge base is now `d0e72fa6805aebeadf1b282e430deba493072fd6`. No code or migration changes were introduced.
- A branch-wide scan of the 30 changed architecture documents found no duplicate numbered section headings after fixing the protocol-contract numbering. Legacy strings such as `process.terminated`, `Done{Lost}` and `human_intervention_request` remain only in explicit superseded/historical or prohibition contexts, not as normative contracts.
- This was a terminology/heading scan, not a claim that every business reader/writer or transaction path has completed a semantic audit.

Overall status remains **Changes Required / Review Pending**. PR #9 must remain Draft and must not be merged until the remaining P0/P1 items are resolved.


## 8. SEM-02J Platform transaction and execution-path audit

Read-only source audit against `master@d0e72fa6805aebeadf1b282e430deba493072fd6` is recorded in [SEM-02J](./sem-02j-transaction-and-execution-path-closure-review.md).

Confirmed P0 findings:
- Run ↔ Interaction lock-order inversion: report is Run→Interaction; retry/cancel are Interaction→Run.
- Run ↔ Command lock-order inversion: reacquire is Run→Command; continue ACK is Command→Run.
- Run ↔ Task lock-order inversion: Claim is Project→Run→Task; Task cancellation holds Task before its Interaction/Run linkage.
- Task Barrier bypasses remain in TaskReady, review enqueue/claim/retry, same-Run reacquire and existing orphan recovery paths. Review Runs share `delivery.task_run` and cannot silently bypass a Task-scoped safety fence.
- Review Claim/retry do not consistently participate in the Project activity gate, leaving a Project archive race.

SEM-02J also records current concurrency-test coverage and the deterministic two-connection acceptance matrix. No application code or migration was changed. The final global lock order is deliberately not selected yet; remaining Run INSERT/UPDATE paths, SQL FK/trigger lock side effects, and all background/API entrypoints must be inventoried first.

Overall status remains **Changes Required / Review Pending**. PR #9 remains Draft; no migration authoring, code changes, merge or Phase 0 start is authorized.


SEM-02J follow-up detail:
- The Task dependency graph advisory lock is part of the same lock graph. Its helper requires acquisition before any row lock, but Review finalization can lock a Review Run before invoking terminal Task transition and thereby acquiring the graph lock. This is a lock-order contract violation requiring pairing tests; a universal deadlock cycle is not asserted without the remaining pairing audit.
- Task cancellation holds Task before Interaction/Run linkage, while Claim/recovery paths hold Run before Task. Review retry directly inserts a review Run without Project/Task locking, and Review Claim locks only the Run. These are additional Barrier and Project lifecycle closure items.


## 9. SEM-02J second source-audit pass

- Confirmed Review retry directly inserts a Review Run without Project activity locking, Task row locking or Task Barrier validation; its max-attempt allocation can race and relies on per-kind unique indexes as a final guard.
- Delivery retry-after-failure updates/locks Task before creating a Delivery Run but does not participate in the Project activity gate or Task Barrier.
- Review Claim and stuck-Review recovery still lack consistent Project lifecycle participation.
- Task/Project parent FKs and Run child FKs create implicit key-share/parent-lock edges; partial unique indexes serialize/reject some duplicate inserts but do not enforce Barrier authorization.
- The trigger inventory identifies Review report immutability on task_run and append-only event/failure guards; no cross-aggregate secondary lock acquisition was found in the inspected triggers. This must be revalidated against the current full migration chain.
- The failure-judge standalone Run update commits/releases before its later Task transaction; it is not labeled a proven simultaneous Run→Task lock inversion.

The final global lock order remains unselected. The current migration-chain reconciliation, exhaustive write-path inventory, API/background route audit and deterministic pair tests remain open. No implementation or Phase 0 is authorized.


## 10. SEM-02J third source-audit pass

- Normal Run business writes add Run→Task edges: progress first-start, delivery submit, Worker spawn confirmation and Review completion. These must be included in the same lock graph as Claim and Task cancellation.
- The current code still has Runner-facing MCP Claim/reacquire/command poll/ACK and a Platform Worker dispatch loop. These are legacy control paths to remove/fail-closed during SEM cutover; Harness business MCP operations remain distinct and must be retained.
- `governance.human_intervention` currently stores seven intervention-action types and has no HIR lifecycle. Extending it requires a record discriminator and preservation of existing action readers.
- `governance.human_consultation` is a generic formal decision workflow; its current create/transition paths lock Consultation and update Task waiting without Project activity or Task row locks. E6 requires typed anchors and cannot be inferred from generic consultation status.
- `integration.notification` remains a project Feed without per-principal recipient ownership; proposed Inbox rows must remain non-authoritative.
- `delivery.task_waiting`, Interaction scheduling shield and Task Execution Barrier are distinct gates; one Platform transaction predicate must evaluate all applicable gates.

The global lock order remains unfrozen. Remaining work includes migration-chain reconciliation, exhaustive route/reader/writer inventory, exact API security contracts and deterministic two-connection concurrency tests. No implementation or Phase 0 is authorized.


## 11. SEM-02J fourth source-audit pass

- Interaction report/retry/response/consume, Continue/Terminate ACK, Continuation lifecycle hooks and progress/renewal paths were traced.
- Confirmed the connected lock graph includes Project, Run, Task, Interaction, Command and Continuation. Task cancellation locks Task before Interaction/Run; normal execution and ACK paths include Run/Command before Task.
- Continue ACK and mark_consumed both mutate delivery/continuation/interaction/task effects; idempotent predicates alone do not prove deadlock freedom.
- Continuation generation allocation relies on the caller holding the Run lock; future callers must preserve this or use a DB-enforced allocator.
- Cleanup ledger locks are separate from Run authority and must not be treated as E3 process-exit evidence.
- Added deterministic concurrency cases J11–J18. No global lock order selected.

The full lock graph, migration-chain reconciliation, API/background route inventory and pair tests remain open. No implementation or Phase 0 is authorized.


## 12. SEM-02J fifth migration audit pass

- Current master migration head is 0059. The checked-in 2026-11-15 schema inventory predates late PA-08 migrations and cannot certify current schema constraints/triggers.
- 0046 Consultation has generic state and a single Task FK with `ON DELETE SET NULL`; it lacks composite tenant/project/task identity and typed E6 anchors.
- 0053 adds one active Run per `lease_client_id` for claimed/running. It does not model Runner process/connection epoch or resource reservation.
- 0054 cleanup claim fencing and 0055–0057 workspace reclamation remain derived-resource ledgers, not process-exit authority.
- 0058/0059 do not directly alter Run ownership in the inspected DDL.

Full migration-chain replay, catalog capture, baseline trigger/constraint audit and comparison against the exact 0059 head remain open. No implementation or Phase 0 is authorized.
