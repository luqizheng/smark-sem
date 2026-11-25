# SEM-02D — 架构评审包（D-01–D-13 + Corrective Findings）

- 状态：**Design In Progress — Corrective Design Review Pending**
- 日期：2026-11-25
- 仓库：`luqizheng/ai-pm`，分支：`master`
- 性质：候选架构设计与评审记录；上一轮完整性结论已撤回，修正设计仍待评审；不是实施授权。
- 适用范围：SEM V1 的 Platform、Server Execution Management（SEM）、Client Runner、Harness 之间的服务边界、数据权威、协议、安全、故障恢复、资源调度和分阶段实施。
- 当前状态：**只写设计文档；没有修改业务代码、数据库 Migration、Dockerfile、Compose、API、WSS 实现或 Runner/Worker 主循环；Phase 0 未启动。**

## 1. 本次批量交付内容

本评审包将 SEM-02D 的 D-01–D-13 统一整理为可评审设计。详细字段、消息契约和状态语义以各专题文档为准，本文件负责给出完整决策目录、依赖关系和评审入口。

| 阻断项 | 本批次推荐设计 | 优先级 | 状态 |
|---|---|---:|---|
| D-01 执行不确定性屏障 | Platform 独立 `delivery.run_execution_barrier`；与 Interaction scheduling shield 分离；所有派发路径统一检查 | P0 | Review Pending |
| D-02 HIR 物理模型 | Phase 0 创建正式 `governance.human_intervention_request` 最小实体；Phase 4 扩展同一实体 | P0 | Review Pending |
| D-03 Platform–SEM API | 版本化 HTTPS `/internal/v1`；服务 JWT；统一 envelope、错误、幂等与超时语义 | P0 | Review Pending |
| D-04 Runner–SEM 协议 | WSS 双向控制协议；版本化 envelope、connection epoch、ACK 分层、重连对账 | P0 | Review Pending |
| D-05 SEM DB | 七张 SEM 私有表；不复制 Platform Run/Lease/Generation/HIR/Command 权威 | P0 | Review Pending |
| D-06 应用层边界 | Platform-owned 与 SEM-owned Ports/Adapters 分离；SEM 不持 Platform PgPool | P0 | Review Pending |
| D-07 密钥生命周期 | Platform/SEM service key 与 Runner Ticket key 分离；短期密钥轮换、撤权与 fail-closed | P1 | Review Pending |
| D-08 Claim 幂等恢复 | Platform Claim 与幂等结果同事务；加密保存可恢复响应；相同 key 重试/查询 | P1 | Review Pending |
| D-09 进程身份与 E3 | Windows/Linux/macOS 各自稳定进程身份；无法验证降级 E5；明确 V1 信任边界 | P1 | Review Pending |
| D-10 命令双层状态 | Platform worker_command 是业务状态；SEM command_delivery 是传输账本；receipt ACK 不等于终止 | P1 | Review Pending |
| D-11 HIR 状态机 | 通知、用户选择、接管、解决、关闭分层；HIR 关闭不自动解除 barrier | P1 | Review Pending |
| D-12 Harness 凭据 | WSS/Service/Lease/Git/LLM/MCP/Device 凭据持有者、注入、撤销、脱敏边界 | P1 | Design Defined; pre-implementation inventory required |
| D-13 资源感知调度 | CPU、内存、Workspace 实际磁盘卷；资源画像与原子预留；未知/过期阻止新派发 | P1 | Ratified as ADR-SEM-26 |

## 2. 已冻结的上位架构约束（本批次不重开）

1. Platform 与 SEM 使用版本化 HTTPS API，各自独立数据库；SEM 不直连 Platform PostgreSQL。
2. Platform PostgreSQL 是 Run、Lease、Generation、HIR、worker_command 业务状态和业务审计的唯一权威。
3. SEM 是 Runner 控制面的唯一派发与接管协调者；Runner 不再通过 Platform MCP 轮询 Claim、命令或恢复控制。
4. Platform Outbox → HTTPS → SEM Inbox；SEM Inbox 对 event_id 幂等。Platform 是 Outbox 唯一消费者。
5. Runner 主动连接 SEM WSS；Harness 继续通过 Platform MCP 使用项目/任务上下文、Interaction、Agent Activity 和交付业务能力。
6. Lease Renewal 唯一路径为 Runner Supervisor → WSS → SEM → Platform HTTPS API；Heartbeat、资源报告、Harness Activity 均不续租。
7. Runner 默认 unattended；只有显式 supervised 才要求用户在派发前选择。
8. Workspace/Worktree/Git Mirror 是可重建执行资产，不做备份；丢失不构成进程死亡证据。
9. 每个 Repository 只有一个权威 Git origin。
10. 不引入 Redis、Kafka、RabbitMQ；不做分布式事务。
11. Harness Resume 默认关闭，只有针对精确 Harness/版本的真实恢复验收通过后才可启用。
12. E1/E2/E3 是允许自动回收/重派的终止证据类别；E4 隔离并创建/关联 HIR；E5 保持不确定，绝不自动回收。

## 3. 核心安全模型

### 3.1 两种 Shield 必须分开

- Interaction scheduling shield：保护用户交互等待、人工决策等业务调度语义。
- Run execution barrier：保护旧执行进程是否仍可能运行这一物理执行安全事实。
- 两者不是同一实体，不互相替代。Platform dispatchability predicate 必须同时检查两者及设备/项目授权、Run 状态、Generation 和并发约束。
- ADR-SEM-16 中“E4 持久化 scheduling shield”描述的是持久隔离语义；本设计将其物理执行不确定性载体明确化为独立 execution barrier，避免与 Interaction shield 混淆。

### 3.2 唯一执行权与证据

- Claim 是 Platform 事务；SEM 的调度选择不授予执行权。
- Claim 成功后才允许 SEM 向目标 Runner 派发。
- 任何超时/断线/Workspace 丢失/Heartbeat 丢失均不能推断进程已退出。
- 命令 receipt ACK、业务 command ACK、进程终止 E3 是三种不同事实。
- HIR 的解决/关闭与 barrier 释放是两个独立状态变化；HIR 关闭不得自动解除 barrier。
- E4/E5 不因人工风险接受而伪装成 E1/E2/E3。

## 4. 协议与数据模型评审入口

| 专题 | 权威文档 | 评审重点 |
|---|---|---|
| D-01/D-02 | `sem-02d-closure-design-proposal.md` §§1–2 | barrier/HIR 表关系、事务边界、唯一活动约束 |
| D-03 | 同文 §3 | 路由、身份、幂等、错误码、Claim timeout |
| D-04 | 同文 §4 + `protocol-contracts.md` | WSS 消息、epoch、ACK、重连、背压；须包含 `runner.resource.report` |
| D-05 | 同文 §5 | 七表字段、状态、索引、清理策略；资源快照复用 runner_connection，预留复用 dispatch_operation |
| D-06 | 同文 §6 + `worker-role-separation.md` | PgPool 所有权、应用层 ports、composition root |
| D-07/D-08 | 同文 §§7–8 + `security-model.md` | 密钥分离、轮换、Claim 响应加密和保留期 |
| D-09 | 同文 §9 + `execution-safety.md` | OS 进程身份、E3 信任假设、E5 降级 |
| D-10/D-11 | 同文 §§10–11 + `state-machines.md` | 业务状态/传输账本、HIR 状态与 barrier 解除条件 |
| D-12 | 同文 §12 + `security-model.md` | 凭据注入边界；Phase 0 前代码级凭据盘点 |
| D-13 | 同文 §15 + `resource-aware-runner-scheduling.md` | 资源快照新鲜度、资源画像、原子预留和并发准入 |

## 5. 资源感知调度补充约束

ADR-SEM-26 已批准。为避免协议文档漏项，WSS V1 消息集合必须包括 `runner.resource.report`。资源报告至少包含 Runner/boot identity、单调 sample sequence、采样时间、CPU 容量/利用率、内存总量/可用量/压力，以及 Workspace 实际所在卷的总量/可用量。SEM 只接受当前已认证连接身份的报告；过期、乱序或重复样本不得覆盖新快照。资源预留必须在同一 SEM DB 事务内原子完成，并绑定 dispatch operation / Run+Generation。资源未知或过期只阻止新派发，不影响现有任务，也不作为终止证据。

## 6. D-12 凭据盘点的明确边界

D-12 的目标架构边界已经定义，但“当前实现中实际如何注入/继承/记录凭据”必须在 Phase 0 任何代码改动前做一次只读代码级盘点。盘点范围至少包括 Codex 及其他 Harness 启动器的环境变量、命令行、配置文件、子进程继承、stdout/stderr、executor-events、crash dump、临时 SSH 文件、日志和 tracing。盘点结果应逐项列出凭据来源、持有进程、注入方式、作用域、TTL、撤销方式、可能泄漏面及测试证据。此项是实施前安全门槛，不应被误报为已经完成的代码审计。

## 7. 实施阶段与硬门槛

- **Phase 0**：D-01/D-02 评审通过后，执行证据前置、正式 HIR/barrier 持久化、凭据盘点及安全修复。
- **Phase 1**：D-03–D-08 评审通过后，完成 Platform/SEM API、WSS、独立 DB、七表、Ports/Adapters、服务身份和 Claim 幂等恢复。
- **Phase 2**：独立 Docker 主机部署与故障恢复验收；SEM 不持有 Platform DB 凭据。
- **Phase 3**：Session Manager 与 Harness Native Session 采集；Resume 仍默认关闭。
- **Phase 4**：HIR 通知、supervised 选择、Runner handoff、E3 证据与受控人工处置。
- **Phase 5**：真实多 Runner、多 OS、网络分区、服务重启、资源压力、凭据撤销和无双重执行验收。

任何阶段开始前必须先通过上一阶段的安全门槛。设计文档提交不代表授权执行。用户完成评审并明确批准后，才更新决策状态并进入实施准备。

## 8. 本次评审建议重点拍板的事项

1. D-01：独立 execution barrier 表及其与 Interaction shield 分离的模型。
2. D-02：正式 HIR 表在 Phase 0 创建、Phase 4 扩展的策略。
3. D-03/D-04：HTTPS/WSS 路由、envelope、消息命名和超时边界。
4. D-05/D-06：七表结构及 Platform/SEM Ports 所有权。
5. D-07/D-08：Ticket/service key 分离、Claim 幂等响应加密和 24h TTL。
6. D-09：V1 信任已注册且未撤权的 Runner Supervisor；不提供硬件证明；无法稳定验证进程身份时降级 E5。
7. D-10/D-11：命令双层状态、HIR 状态推进和 barrier 释放规则。
8. D-12：凭据目标边界是否符合预期；实施前只读凭据盘点不可省略。
9. D-13：已按 ADR-SEM-26 批准，不再作为待评审事项；如评审中提出变化，应另行修订 ADR。

## 9. 明确不包含的内容

本批次没有授权或执行：
- Phase 0–5 的任何代码实现；
- Platform 或 SEM 数据库 Migration；
- API endpoint、WSS server/client 或 Runner 控制循环改造；
- Dockerfile、Compose、镜像或部署环境修改；
- Workspace 备份、多 Git origin、消息中间件；
- 任何把 E4/E5 自动降级为可重派的行为。

## 10. 评审结论记录

评审后应在本文件补充：
- 用户评审日期与结论；
- D-01–D-12 每项 Ratified / Revised / Rejected 状态；
- 对应 ADR 编号（仅在用户明确批准后分配）；
- 被修改的权威文档清单；
- 是否满足 Design Complete 门槛。

在此之前，本评审包保持 **Review Pending**，Phase 0 保持 **Not Started**。


## 11. 新一轮评审发现（2026-11-25）

用户对本评审包提出 10 项 P0/P1/P2 问题。只读复核确认这些问题整体成立，尤其是 Interaction 执行闭环、Phase 0–3 HIR 可操作性、Runner E3 进程退出证据、Detached 同设备恢复、Workspace 丢失误判、E6 人工风险授权、通知收件人、Session 连续性、Detached 状态载体及统一 dispatchability predicate。

新增修正设计文档：[`sem-02d-review-findings-corrective-design.md`](./sem-02d-review-findings-corrective-design.md)。该文档给出十项核验、对象关系、Execution Control Port、E3/E5/E6、通知模型、Detached → Active、统一派发谓词和重排后的 Phase 0–5。它覆盖并修正本评审包中与上述内容冲突的旧表述。

因此本评审包仍是 Review Pending，且**上一轮“Design Package Complete”结论撤回**；当前状态为 **Design In Progress — Corrective Design Review Pending**。Phase 0 未启动。
