# SEM-02D — 最终架构一致性审查

- 日期：2026-11-24
- 审查对象：`master` 当前 SEM V1 架构文档与关键实现代码
- 审查性质：只读架构/代码复核；本报告及同步文档除外，未修改业务代码、数据库迁移、Dockerfile、Compose、Worker 主循环或 Runner 实现
- 结论：**Design In Progress；当前不具备开始 Phase 0 的完整设计条件**
- 决策状态：ADR-SEM-01 至 ADR-SEM-25 中已由用户确认的决策继续有效；本报告不擅自新增 ADR 或冻结尚未确认的物理 Schema/接口字段

## 1. 执行摘要

本次复核确认，SEM 的总体职责边界已经清楚：

- Platform 是 Run、Lease、Generation、命令业务状态、HIR 和业务审计的唯一权威。
- SEM 是 Runner 控制面的唯一调度、派发和接管协调者，拥有独立数据库。
- Runner 通过 WSS 接入 SEM；Harness 通过 Platform MCP 使用业务能力。
- Platform 与 SEM 通过版本化 HTTPS API、Transactional Outbox / SEM Inbox、幂等和对账协作。
- Workspace/Worktree/Git Mirror 不做备份；每个 Repository 只有一个权威 Git origin。
- 不引入 Redis/Kafka/RabbitMQ，不通过共享 SQL 解耦服务。

但「架构方向已冻结」不等于「可直接实施」。复核发现仍有若干阻断项：旧代码的双重执行回收风险未修复；部分文档仍有过时协议表述；Scheduling Shield 与 HIR 的物理状态模型及 Phase 顺序不完整；Platform–SEM API、WSS wire schema 和 SEM DB 仍停留在逻辑清单；Worker 当前应用层直接依赖 Platform PgPool，不能只通过 main.rs 角色过滤实现独立 DB 边界。

因此，本轮不宣布 Design Complete，不启动 Phase 0。先关闭第 4 节列出的设计项，再做一次小范围复核。

## 2. 本次核验的当前代码事实

以下是对当前 master 代码的直接读取结果，不是目标架构描述：

1. `apps/ai-pm-worker/src/main.rs` 启动时直接读取 `DATABASE_URL` 创建 Platform PostgreSQL pool；当前同一进程装配 Outbox、业务 Job、Run 调度、进程监控和清理循环。尚无 SEM 独立 DB/API 装配边界。
2. `apps/ai-pm-runner` 当前通过 Streamable HTTP MCP 访问 Platform；`runner_loop` 仍负责 Claim、心跳/续租、命令轮询和 ACK。尚无 Runner–SEM WSS 客户端。
3. `crates/pm-mcp` 的 `pm_claim_task`、`pm_report_progress`、`pm_poll_commands`、`pm_ack_command` 仍可承载当前控制面行为。迁移完成后必须删除 Runner 对这些控制能力的调用，但保留 Harness 所需的业务 MCP。
4. `apps/pm-api/src/auth.rs` 当前明确拒绝普通业务端点上的 service token。SEM 内部 API 和设备 connect-ticket 必须建立专用认证/授权入口，不能放宽普通用户身份解析。
5. `run_executor.rs`、`run_dispatch/claim.rs`、`worker_command.rs`、执行事件及 `codex_executor.rs` 多处直接使用 Platform `PgPool`。将 SEM 与 Platform 数据库隔离，需要应用层 ports/API adapter 重构，不是只过滤 `tokio::spawn`。
6. `claim.rs` 的 B3-2（已启动、租约过期）分支当前仍直接进入 `recover_lost_run`，没有 E1/E2/E3 终止证据前置。
7. `run_executor.rs::reconcile_orphans` 当前仍对运行超过一小时且租约过期的 Run 直接回 queued、释放 Task；该路径没有先验证进程终止，也没有按目标设计应用 Runner 排除。
8. 当前 `delivery.task_run.scheduling_shield` 已存在，当前产品语义包含 `none / human_wait / start_wait / timed_out`，用于 Interaction/Continuation 调度保护。它不是已完成的 E4/E5 执行不确定性状态模型。
9. 当前 Runner/Executor 有本机进程记录和 identity hint，但这些记录尚未构成目标 WSS E3 协议；不能据此声称远程 E3 已实现。
10. 当前没有 SEM HTTPS API、SEM Inbox/私有数据库、Runner WSS Listener/Client 或 Platform–SEM service JWT 集成。

## 3. 文档一致性问题（必须修复）

### 3.1 Lease Renewal 已冻结，但旧文档仍写成待决定

复核时发现：
- `protocol-contracts.md` 曾将 Lease Renewal 标为「建议方案」；
- `runner-supervision-and-handoff.md` §7 曾写「传输路径尚待冻结」；
- `code-contract-mapping.md` 的现状/目标对照表仍保留「待用户确认」。

这些内容与 ADR-SEM-21 冲突。本轮已将可定位的旧表述统一修正为：Runner Supervisor → WSS → SEM → Platform HTTPS API；Heartbeat 与 Harness Agent Activity 均不续租。

### 3.2 API 与持久化契约被错误地推迟到实施阶段

部分文档仍写「具体 Route/DTO 在实施时确定」。这与一致性门槛「实施前冻结接口契约」冲突。本轮已明确：精确 Route、DTO、状态码、错误信封、重试分类必须在 SEM-02D 设计阶段完成，不能留给 Phase 1 边写代码边决定。

## 4. 尚未关闭的设计阻断项

### D-01（P0）E4/E5 执行安全屏障的物理模型

当前 `scheduling_shield` 已承载人工交互等待、回复投递等待和超时冻结等既有语义。E4/E5 的进程不确定性是另一种安全事实，不能未经设计就把它映射成现有 `timed_out` 或其他 Interaction 状态。

必须明确：
- E4/E5 屏障的物理载体（独立列/独立表/明确扩展后的状态域）；
- 每个 Run + Generation 的唯一活动屏障约束；
- 触发原因、证据类别、首次发生时间、最近观察、HIR 关联、解除人/解除原因；
- 所有 Claim、B3-2、B06-D3、orphan reconciliation、retry/requeue 路径共同检查的谓词；
- 解除屏障与终止证据、HIR 处置、Generation 变化之间的事务边界。

**建议方向（待确认，不是已冻结 ADR）：** 将「执行不确定性屏障」与现有 Interaction `scheduling_shield` 分开建模，避免把两种生命周期塞入同一枚举。所有自动领取/回收路径统一检查两者。

### D-02（P0）Phase 0 与 HIR 的依赖顺序冲突

当前执行安全设计要求 E4/E5 挂起时创建或关联 HIR；但路线图把 HIR 独立表、域服务和 API 全部放在 Phase 4。这样 Phase 0 无法兑现「E4 屏障 + HIR 出路」的目标。

必须二选一并写入路线图：
- 推荐：Phase 0 建立 HIR 最小持久化实体、唯一活动请求约束和最小审计写入；Phase 4 再实现完整 HIR 用户界面、通知、选择、处置和跨 Runner 工作流。
- 或明确 Phase 0 只建立安全屏障和可审计的待处置记录，Phase 4 再迁移为 HIR；但这会产生临时模型及额外重构，不如前者直接。

### D-03（P0）Platform–SEM HTTPS API 尚无可实现的 wire contract

目前已有逻辑操作清单，但缺少可直接生成服务端/客户端实现的规范。至少必须冻结：
- 精确 Route、HTTP Method、请求/响应 DTO、必填字段和字段类型；
- API 版本策略、错误码/错误信封、HTTP 状态码和 retryable 分类；
- Claim-for-Runner 的目标身份绑定、候选条件、并发锁、Scheduling Shield 检查、返回 Grant 的字段；
- Lease Renewal 的精确请求/响应、token proof、process identity 与 supervisor session 的可信来源；
- command read / receipt ACK / E3 evidence submit 的事务与幂等边界；
- execution report、Runner authorization check、connect-ticket 的 API 所属服务和鉴权策略；
- 限流、超时、重试预算、请求大小、审计字段和兼容版本策略。

### D-04（P0）Runner–SEM WSS 消息协议尚无完整 wire schema

必须为下列消息定义 JSON/二进制 envelope、字段、必填性、版本、幂等键、错误响应、ACK 语义和状态迁移：
- connect / authenticated session established；
- supervisor heartbeat；
- lease.renew；
- execution dispatch / dispatch accepted / dispatch rejected；
- command delivery / command.received；
- command result / command.failed；
- process.terminated（E3）；
- runner.reconnect_sync；
- connection revoked / drain / server shutdown。

还需冻结连接 epoch、消息去重窗口、重连后对账顺序、最大消息尺寸、心跳间隔/超时、并发消息上限、背压与发送队列持久化规则。WSS 消息 ACK 不能代替 OS 进程退出 ACK。

### D-05（P0）SEM 七张私有表目前只是概念字段清单

ADR-SEM-24 已冻结七张表的职责，但当前文档未给出完整 DDL。实施前至少需要：
- 主键/FK（对外部 Platform ID 使用何种引用约束）、唯一约束和检查约束；
- `inbox_event`、`dispatch_operation`、`command_delivery`、`platform_delivery` 的状态枚举与合法迁移；
- 幂等唯一键、重试索引、领取锁/并发控制策略；
- `runner_connection` 的多连接/epoch 唯一性规则；
- `runner_ticket_use` 的过期清理和 replay retention；
- `process_observation` 的证据不可变性、去重和保留策略；
- 每张表的数据保留/清理策略、租户隔离和最小必要数据原则；
- SEM DB 空库初始化、迁移所有权和部署启动门槛。

### D-06（P0）Worker 角色拆分的工作量与真实服务边界不一致

`worker-role-separation.md` 中「角色装配集中在 main.rs」容易被理解为服务解耦只需改 main.rs。实际应用服务直接依赖 Platform `PgPool`，SEM 不得连接 Platform DB 的 ADR-SEM-19/20 要求意味着需要：
- 将 Run/Lease/command/event 等应用操作抽象成 ports；
- Platform 提供 SQL-backed adapter/API handler；
- SEM 提供 HTTPS client adapter；
- 本机进程、Workspace、PID、日志和 cleanup ledger 留在 SEM infrastructure；
- 对所有 SQL 读写做归属矩阵，保证 SEM 没有隐式 Platform pool；
- 保留 Platform Outbox 单消费者，新增的 SEM 投递必须作为 Platform 侧 handler 调用 SEM Inbox API。

角色开关只负责装配边界，不替代应用层依赖反转。路线图和工作量必须按此范围估算。

### D-07（P1）Service JWT 与 WSS Ticket 的密钥生命周期未闭合

ADR-SEM-22/23 已冻结认证机制，但尚需明确：
- service_id/device_id 的注册、批准、禁用和恢复流程；
- 私钥保存位置、访问主体、轮换/吊销和紧急泄漏处置；
- 公钥发布/分发、kid 缓存刷新、时钟偏差容忍和未知 kid 处理；
- JWT `jti` replay 防护的作用范围和保留窗口；
- WSS Ticket 签名密钥与 Service JWT 密钥是否分离；
- Ticket 的 audience/scope/device/credential binding 精确 claims；
- 30 秒授权新鲜度窗口如何计时，Platform 不可达时连接关闭与活动 Run 处置顺序。

### D-08（P1）Claim 幂等结果加密存储的密钥与保留策略未闭合

ADR-SEM-25 依赖 Platform 在 Claim 事务中保存可恢复的加密响应，以处理「Claim 已提交但 HTTP 响应丢失」。必须明确：
- 加密算法/信封加密或等效机制；
- 加密密钥由谁持有、如何轮换和撤销；
- 明文只在响应时短暂解密，日志/Tracing/错误体绝不包含 token；
- 幂等记录 TTL、清理、冲突重用和审计；
- 过期后 SEM 如何查询当前 Claim/Lease 状态，避免重新 Claim。

### D-09（P1）E3 的信任模型和进程身份定义不完整

E3 是远程 Runner 观察并上报的 OS 事实，不是 Platform 能独立探测的事实。需要明确 V1 信任假设：已注册且未被撤权的 Runner Supervisor 被视为可信进程观察者；设备被攻陷时 E3 不构成防恶意设备的硬件证明。

还需冻结跨 OS 的 process identity 结构（PID 之外的启动时间/进程句柄锚点/父子进程组或 Windows Job Object 标识）、PID reuse 处理、进程树退出判据、Runner 重启后如何恢复观察，以及 E3 报告与命令/Run/Generation/connection epoch 的绑定。证据缺失或不一致必须降级 E4/E5。

### D-10（P1）Platform 命令业务状态与 SEM 传输状态的映射不够精确

Platform `worker_command` 是业务命令权威，SEM `command_delivery` 只是传输账本。必须明确：
- Platform `issued → delivered → acked/failed` 各状态由哪一个 API 请求触发；
- SEM 的 queued/sent/received/expired/retry 等传输状态与 Platform 状态的映射；
- Runner 收到命令但 SEM 未收到 ACK、SEM 已落 ACK 但 Platform API 不可达、重复 ACK、迟到 ACK 的处理；
- terminate receipt 与 E3 process termination evidence 的差异，不能把当前 MCP ACK 的业务回执直接等同于 E3。

### D-11（P1）HIR 状态机和人工解除屏障条件需要统一

当前 HIR Mermaid、通用 state-machine 文档和 handoff 安全不变式在「自愈关闭」「Accepted」「InProgress」「Resolved」的触发条件上仍不够精确。需要统一：
- HIR 创建/通知/用户选择/Runner 接受/Platform Claim 成功/首次执行活动/Run 终态之间的状态推进者；
- 用户选择 Runner 只是意愿，不得推进为执行权已接管；
- 只有 Platform Claim 成功并确认 generation+1 才能标记 handoff accepted；
- E4/E5 在没有 E1/E2/E3 时不得因用户选择或 HIR 关闭而自动解除屏障；
- 人工接受风险解除必须有明确授权、风险确认、旧进程处置策略和审计字段；
- 原 Run 自愈与 HIR 关闭必须使用可证明的条件，迟到心跳不能自动清除执行屏障。

### D-12（P1）当前 Harness 凭据路径需要逐种类清点

现有代码会向 Harness 子进程注入 MCP URL、Lease Token，并存在 Git SSH 临时凭据等执行路径。Phase 0 的凭据要求不能只写原则。需按 Codex/其他 Harness 分别列出：
- 注入的 Platform 业务凭据、Lease Token、Git 凭据和 LLM 凭据；
- 凭据生命周期、最小权限、撤销方式及无法即时撤销时的外部副作用；
- 哪些凭据只应给 Runner Supervisor，哪些必须给 Harness；
- 环境变量、命令行、配置文件、日志、事件和 crash dump 的泄漏面。

## 5. Phase 0–5 路线图修订要求

1. Phase 0：先关闭 D-01/D-02 的物理状态与最小 HIR 持久化设计；修复 B3-2、B06-D3、orphan reconciliation；E3 尚未通过验收时，远程 Runner 只能 E4 隔离，不得自动重派。
2. Phase 1：先完成 D-03/D-04/D-05/D-06/D-07/D-08 的契约与 Schema 冻结，再实施 ports、Platform API、SEM API、双 DB、Outbox/Inbox 和 WSS。
3. Phase 2：独立 Docker 主机部署、SEM DB 初始化、Workspace 运行期持久卷和故障演练；不增加 Workspace 备份。
4. Phase 3：Session Manager 与 Harness Native Session 采集；Resume 对每个 Harness/版本继续默认关闭，只有真实验收通过才启用。
5. Phase 4：在 Phase 0 的最小 HIR 基础上完成通知、用户选择、HIR 处置 UI、完整 handoff 流程；不重复创建 HIR 表。
6. Phase 5：双 Runner、多 OS、网络分区、SEM/Platform DB 故障、密钥撤销和并发执行验收。

## 6. Design Complete 的客观门槛

以下全部完成后才可将 README 状态改为 Design Complete：

- [ ] D-01：执行安全屏障物理模型及所有入口守卫已冻结。
- [ ] D-02：Phase 0 最小 HIR 与 Phase 4 完整 HIR 的分工已冻结。
- [ ] D-03：Platform–SEM HTTPS API 路由/DTO/错误/重试契约已冻结。
- [ ] D-04：Runner–SEM WSS envelope、消息、ACK、重连与背压契约已冻结。
- [ ] D-05：七张 SEM 表的 DDL、约束、索引、状态机、保留策略和迁移所有权已冻结。
- [ ] D-06：Platform/SEM 应用层 ports、adapter 和 SQL 归属矩阵已冻结。
- [ ] D-07：服务身份、Ticket、密钥轮换/撤销/引导流程已冻结。
- [ ] D-08：Claim 幂等响应加密存储和 TTL 方案已冻结。
- [ ] D-09：E3 信任模型、跨 OS 进程身份和进程树判据已冻结。
- [ ] D-10：Platform 命令状态与 SEM 传输账本映射已冻结。
- [ ] D-11：HIR 状态机、人工解除屏障和 handoff 触发条件已统一。
- [ ] D-12：Harness 凭据清单与撤销/脱敏边界已完成。
- [ ] 旧代码阻断项已有明确 Phase 0 修复范围与验收；文档中的代码事实锚点在实施前再次对照 HEAD。

## 7. 明确不在本轮重开的话题

以下决策继续冻结，不因本次发现而重开：
- Workspace/Worktree/Git Mirror 不备份。
- 每个 Repository 只有一个权威 Git origin。
- 不引入 Redis/Kafka/RabbitMQ。
- Platform 与 SEM 不共享数据库，SEM 不直连 Platform PostgreSQL。
- SEM 是 Runner 控制面唯一派发/接管协调者。
- Lease Renewal 唯一路径按 ADR-SEM-21。
- Runner 默认 unattended；supervised 需明确用户选择。
- Harness Resume 默认关闭，实测通过后才可启用。

## 8. 最终结论

**本次最终审查结论：不通过 Design Complete 门槛，但没有发现需要推翻 ADR-SEM-19 至 ADR-SEM-25 总体架构方向的理由。**

当前最重要的下一步是先确定 D-01 的执行安全屏障物理模型。建议将 E4/E5 执行屏障与现有 Interaction `scheduling_shield` 分开建模，并将 HIR 最小持久化提前到 Phase 0；这两项确定后，再把精确 API/WSS/SEM DDL 契约作为一个集中设计批次完成。**Phase 0 仍未启动。**


## 9. Follow-up: closure design proposal (2026-11-25)

A separate proposed design package has been added at `sem-02d-closure-design-proposal.md`, covering candidate resolutions for D-01–D-12. This is a design proposal only: it does not alter the original review findings, does not create or ratify new ADRs, and does not mark any blocker closed. The explicit decisions in §14 of that proposal require user confirmation. D-12 additionally requires a current code-level credential inventory. Until the proposal is ratified and a final cross-document review passes, the architecture remains `Design In Progress` and Phase 0 remains not started.


## 10. 批量设计包后续状态（2026-11-25）

用户要求将剩余设计一次性提交、后续集中评审。D-01–D-12 的候选设计现已整理为完整评审包：`sem-02d-review-package.md`，专题提案：`sem-02d-closure-design-proposal.md`。本次仅完成文档设计，不代表 D-01–D-12 已获批准，不修改原始代码审计结论，不新增已 ratified ADR。D-13 仍为已批准 ADR-SEM-26。

本轮一致性处理要求：Interaction scheduling shield 与 Run execution barrier 分开建模；前者处理业务交互等待，后者处理执行进程不确定性。两者共同参与 Platform dispatchability predicate。WSS 协议必须包含资源报告消息 `runner.resource.report`，但它不承担 Heartbeat、Lease Renewal 或终止证据职责。

D-12 设计边界已完成；当前 Harness 启动链路的实际凭据注入/继承/泄漏面仍须在 Phase 0 代码变更前完成只读盘点。当前结论：**Design In Progress / Review Pending；Phase 0 Not Started**。


## 11. 2026-11-25 新增十项 P0/P1/P2 评审问题

用户追加十项具体问题后，对当前 master 代码与相关设计文档进行只读复核。结论：十项问题整体成立，且改变了 Phase 0–5 的依赖关系。详见 [评审问题核验与修正设计](./sem-02d-review-findings-corrective-design.md)。

本次尤其确认：
- `interaction.rs` 创建 terminate command，但现有 Runner 是 terminate/continue 的命令消费者；SEM-local `CodexExecutor` 没有等价的回复注入闭环。
- Runner 自然退出和 lease-loss cleanup 缺少独立 E3 证据上报；租约丢失时命令轮询不构成替代。
- Runner restart recovery 只覆盖 start_wait + responded Interaction；必须增加 Detached → Reconciling → Active/Terminated/Quarantined。
- started Run 的 PID/logs/Workspace 同时缺失必须是 E5；`Lost` 不能作为终止证据。
- E6 Human Risk Acceptance 必须与 E1/E2/E3 终止证据分离。
- HIR + recipient/notification 必须在 Phase 0 可操作；Phase 4 只能扩展高级 handoff。
- Detached 不扩展 scheduling_shield；B06-D3、queued claim 和所有自动重派入口必须统一检查 Interaction shield + Execution Barrier。

因此此前“SEM-02D 完整设计包”的判断正式撤回。当前结论为 **Design In Progress — Corrective Design Review Pending**。本轮仅提交修正设计，不改代码/Migration/API/WSS/部署；Phase 0 未启动。旧报告中与 corrective-design 冲突的阶段或状态描述以该修正设计为准。
