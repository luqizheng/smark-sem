# 架构决策记录、已关闭问题与验证门槛（decision-record）

- 性质：Server Execution Management Architecture V1 的正式决策登记。
- 规则：每条决策 = 结论 + 依据 + 何时可重启/推翻。

## A. 已裁决（本 V1 生效）

| # | 决策 | 依据 | 推翻条件 |
|---|---|---|---|
| ADR-SEM-01 | 循环 1/2/3/5/6/7/8 + pm-worker + pm-api audit listener 留 Platform；循环 4 执行子步迁 SEM | SEM-01 + 本轮复核（`worker-role-separation.md` §1） | 出现新的执行型循环且不 spawn 进程 |
| ADR-SEM-02 | Outbox 单消费者：循环 3 只在 Platform 运行；SEM 角色不装配 handler，误配 fail-fast | `register_all_handlers` 全集装配（`outbox.rs:394`）；单消费者消解集合分叉面 | 引入真正的消息中间件（当前禁止） |
| ADR-SEM-03 | 角色开关 `AI_PM_WORKER_ROLE=platform\|execution\|all`，默认 all；Phase 1 不拆新二进制 | 单文件改动、开发态零漂移 | execution 角色膨胀出独立调度需求时派生 `apps/ai-pm-execution-worker` |
| ADR-SEM-04 | 回收必须以终止证据为前提（E1/E2/E3 才可重派；E4 只隔离；E5 永不回收） | DB 租约 ≠ 进程死亡；代码证据 `claim.rs:574-674`、`run_executor.rs:489-583` | 出现比三证据/心跳更可靠的进程事实源 |
| ADR-SEM-05 | Workspace 唯一所有权：一区一进程；新 Attempt 永远新工作区 | 双写冲突不可由 DB fencing 防护（fencing 盲区） | 工作区改为无状态对象存储（远超 V1 范围） |
| ADR-SEM-06 | Session Manager = `pm-application` 逻辑模块，非微服务；Attempt = task_run 行链（attempt_no + supersedes_run_id），不新增 execution 表 | 现有模型已表达 attempt 血缘；Greenfield 审慎新增 | attempt 维度出现独立查询/权限需求 |
| ADR-SEM-07 | Harness Native Session 以 `task_run.harness_session_id` + `harness_kind` 两列采集；能力表在代码（const），不进 DB | 能力是编译期事实；`executor_session` 语义不得混用（任务明令） | 能力需要按租户/项目动态配置时 |
| ADR-SEM-08 | Platform PostgreSQL 是业务 Run/Lease/Generation 的唯一权威源；宿主机文件系统是本机进程证据；不引入 Redis/Kafka/RabbitMQ | 执行权必须由业务权威方仲裁；服务边界另由 ADR-SEM-19 定义 | 业务权威存储策略改变时复审 |
| ADR-SEM-09 | 跨 Runner 接管 = 新设备全新合法 claim（generation+1、token 重签）；不放宽 `lease_client_id` 校验 | 任务硬约束；正门 claim 已具备全部仲裁能力 | 「预授权转移」真实需求出现（另立迁移+校验） |
| ADR-SEM-10 | HIR 决策 Q1=B / Q2=B / Q3=A；E4/E5 挂起的 Run 以 HIR 为唯一自动出路 | 用户已确认三项决策 | 用户改裁 |
| ADR-SEM-11 | Greenfield 政策适用：可直接重构 Schema/接口，不为未发布行为保留兼容层；执行安全不降低 | `engineering-lifecycle-policy.md` | 项目进入有客户/生产数据阶段时复审 |
| ADR-SEM-12 | HIR 使用独立实体 `governance.human_intervention_request`，关联 Run/Attempt/Project/Runner；不复用审计事件承载业务生命周期 | 需要可查询、可处置、可统计的独立生命周期 | HIR 被证明不需要独立查询/状态/授权时 |
| ADR-SEM-13 | Harness Resume 能力默认关闭；能力声明与真实恢复成功分离，未完成版本化实测不得启用 | 当前没有充分实测证据；失败必须降级为 Fresh Attempt | 对具体 Harness 版本完成可重复恢复验收 |
| ADR-SEM-14 | Runner 命令与 ACK 通过 Runner 主动建立的认证 WSS 长连接传输；ACK 必须绑定 run/attempt/generation，并由 Runner 在 OS 进程句柄确认退出后发送 | WSS 是 SEM↔Runner 的唯一实时控制通道；普通消息 ACK/命令送达不构成终止证据 | 若 WSS 在特定环境不可用，需另立 ADR 定义安全降级通道 |
| ADR-SEM-15 | Runner 默认 `unattended`；仅显式配置为 `supervised` 才要求领取前用户确认 | 用户明确决策；监督模式与在线/忙碌状态正交 | 用户明确改变产品默认值 |
| ADR-SEM-16 | E4 Run 进入持久化 scheduling shield：不进入普通 claim 候选集、不因租约过期自动重派；由 HIR 处置；只允许受控人工/证据驱动解除 | 避免 E4 被其他回收路径重新领取；必须有可审计解除条件 | 状态模型重构时，以等价或更强的持久化隔离替代 |
| ADR-SEM-17 | Workspace/Worktree/Git Mirror 不做备份；运行期间仍使用持久卷，丢失后按 E4/E5 安全隔离，不得推断进程死亡 | 用户明确决策；这些内容可由唯一 origin 重建，运行现场不作为备份目标 | 产品未来明确要求灾难恢复现场 |
| ADR-SEM-18 | 每个 Repository 仅配置一个权威 Git `origin`；SEM 不管理 Git 远端同步或双远端合并 | 用户明确决策；Git Mirror 是可重建缓存 | 仓库管理策略另行改变 |
| ADR-SEM-19 | **Platform 与 SEM 通过版本化 HTTPS API 通信，各自管理数据库；禁止 SEM 直连/共享 Platform PostgreSQL。** Platform 是 Run、Lease、Generation、业务状态的权威方；SEM 通过 API 请求认领、取消、查询并上报执行状态/事件。Platform 使用 Transactional Outbox 触发派发，SEM 以幂等方式接收；SEM 可通过 API 拉取/对账补偿。Runner 与 SEM 使用 WSS。V1 不引入消息代理。 | 用户于 2026-11-24 明确确认方案 A；服务独立部署需要明确 API 契约和数据所有权 | API 吞吐/可靠性需求证明 HTTP + Outbox 不足时，另立决策评估消息代理；不得恢复共享数据库耦合作为默认方案 |
| ADR-SEM-20 | **SEM 是 Runner 控制面的唯一派发与接管协调者。** Runner 不再主动轮询 Platform MCP Claim、命令或恢复接口；SEM 选择/确认目标 Runner 后，代表该 Runner 调用 Platform HTTPS API 请求 Claim，Platform 在权威事务中校验目标设备/项目授权/可执行性并签发 Lease、Generation。成功后 SEM 才能经 WSS 派发。Harness 保留 Platform MCP 业务访问。 | 用户于 2026-11-24 明确确认；避免 Runner 直连 Claim 与 SEM 调度形成双控制面 | 若未来需 Runner 直连 Platform 控制面，必须另立 ADR；不得静默恢复双路径 |
| ADR-SEM-21 | **Lease Renewal 唯一路径：Runner Supervisor → WSS → SEM → Platform HTTPS API。** WSS Heartbeat 与 Harness Agent Activity 均不续租；只有 Platform 校验通过并提交后才更新 Lease。 | 用户于 2026-11-24 确认；区分 Runner 存活、执行权续租和 Agent 业务活动 | 若未来更换监督/租约模型，另立 ADR；不得增加第二续租通道 |
| ADR-SEM-22 | **Platform↔SEM 使用双向独立服务身份与短时非对称签名 JWT。** TLS、issuer/audience/scope/kid/jti 校验、密钥轮换；服务身份不得映射为 human principal；mTLS 可作为额外防护。 | 最小权限、可撤销、避免共享静态密钥和服务身份混入用户身份 | 若部署身份基础设施发生变化，另立 ADR；不得退回无身份内网信任 |
| ADR-SEM-23 | **Runner 使用 Platform 签发的短时、一次性、绑定设备的 WSS connect ticket。** SEM 原子消费 jti；撤权通过 Outbox 事件主动关闭连接，并以有界周期 API 重验证兜底；授权新鲜度过期则 fail closed。 | 设备身份由 Platform 权威验证；长连接必须支持持续撤权 | 若连接认证/撤权协议升级，另立 ADR；不得仅依赖握手时认证 |
| ADR-SEM-24 | **SEM DB 采用最小执行/传输私有数据模型。** `inbox_event`、`runner_connection`、`runner_ticket_use`、`dispatch_operation`、`command_delivery`、`platform_delivery`、`process_observation`；不复制 Platform Run/Lease/Generation/HIR/命令业务权威。 | 独立数据库和单一业务权威；SEM 只持有传输与执行侧事实 | 表结构可在不改变所有权边界前提下调整；新增业务状态副本须另立 ADR |
| ADR-SEM-25 | **Claim 与跨服务副作用必须幂等、持久化并可恢复。** SEM 先持久化 dispatch operation；Platform Claim 与幂等结果同事务；丢失响应使用同一 `claim_request_id` 取回同一结果；SEM 不持久化明文 Lease Token。 | 避免网络超时/SEM 重启造成重复 Claim、重复执行或秘密泄漏 | 若采用具备等价保证的新协议，另立 ADR 并通过故障注入验收 |


| ADR-SEM-26 | **Runner 资源感知与同机并发准入。** Runner Supervisor 通过认证 WSS 定期上报 CPU、内存及 Workspace 实际所在磁盘卷容量；SEM 使用新鲜资源快照、任务资源画像和原子资源预留，决定同一台 PC 是否接收多个并发 Run。资源未知/过期时停止新派发；资源压力不自动终止现有 Run；资源数据绝不作为 E1/E2/E3 进程终止证据。 | 用户于 2026-11-25 明确要求统一 Runner CPU、内存、磁盘资源上报，并让 SEM 据此决定同机多任务派发；资源预留避免并发调度超额承诺 | 任务资源画像、采样策略或准入算法可随真实压测调整，但不得取消原子预留、资源未知 fail-closed、新任务准入与进程终止证据分离 |

## B. SEM-01 结论修正（相对 SEM-01 文本的两处精化）

1. **outbox「handler 集合一致」→「单消费者」**：SEM-01 的表述是必要不充分条件的保守版；本 V1 收敛为单消费者约束（更强、更简单）。SEM-01 无错误，属精度提升。
2. **reconcile_orphans 风险上调**：SEM-01 称「>1h 回收不带 runner 排除」；复核确认 B06-D3 直改 DB（绕过 claim 候选发现的 runner 排除），**同时缺进程证据**——与 B3-2 同根同罚，Phase 0 一并修复（`execution-safety.md` §3.2）。

## C. 已关闭问题与实施门槛

| OQ | 正式裁决 | 实施约束 / 验收门槛 |
|---|---|---|
| OQ-1 HIR 载体 | **候选修正：采用独立表** `governance.human_intervention_request` | Phase 0 建立最小可操作 HIR、收件人、通知与受控处置；Phase 4 只扩展高级 handoff；HIR 不替代 `task_interaction` |
| OQ-2 Codex Resume | **设计关闭，能力验证门槛保留**：默认 `supports_resume=false` | 每个 Harness/版本需在真实环境通过采集、重启、恢复、上下文连续性测试后，才可单独启用；未通过一律 Fresh Attempt |
| OQ-3 E3 进程证据 | **候选修正：通过认证 WSS 承载 Runner 进程退出事实** | 自然退出、主动终止、lease-loss cleanup、startup cleanup、boot transition 均上报；命令 receipt ACK、command result、E3、continuation consumed 四者分离 |
| OQ-4 监督模式 | **关闭：默认 `unattended`** | 注册持久化字段；首次注册未提供值时取 unattended；supervised 必须在领取前取得用户确认；在线状态不推导监督模式 |
| OQ-5 E4 租约卫生 | **候选修正：持久化 Execution Barrier** | Interaction scheduling_shield 保持四值；Execution Barrier 独立承载 E4/E5；E6 是人工风险授权，不是终止证据，旧 Barrier 不释放 |
| OQ-6 凭据面 | **关闭：纳入执行安全基线并前移至 Phase 0** | 最小权限、短时凭据、可撤销、日志脱敏；终止旧进程后才可确认其进程内凭据失效；无法即时撤销的凭据必须按最坏情况评估外部副作用 |
| OQ-7 Workspace 备份 | **关闭：不备份 Workspace/Worktree/Git Mirror** | 运行期间单一持久卷；日志/审计/执行状态按各自保留策略持久化；卷丢失不等于进程死亡，所有无法确认的活跃 Run 进入 E4/E5 |
| OQ-8 双远端 | **关闭：每个 Repository 只有一个权威 `origin`** | SEM 不配置、不同步、不合并第二远端；Git Mirror 从唯一 origin 重建；远端托管/镜像策略不属于 SEM V1 |

## D. 用户已确认的产品决策

1. Workspace、Worktree、Git Mirror 不需要备份；不设 RPO/RTO，不建设快照恢复系统。
2. Runner 默认无人值守（`unattended`）。
3. 每个 Repository 只有一个权威 `origin`；SEM 不讨论或实现双远端同步。
4. 用户尚未完成的“4.”不作推断；如后续补充，作为新决策输入。

## E. 仍需实测但不阻塞设计冻结的验证项

- Codex 原生 Session Resume：默认关闭，需在目标 CLI 版本上完成可重复的真实恢复验收。
- Runner E3 ACK：Phase 0 可先让远程 Runner 全部走 E4 安全挂起；E3 通道实现必须满足 OQ-3 的证明标准后才允许作为 E3。
- E4 scheduling shield：必须通过并发 claim、过期租约、迟到心跳、重启恢复和人工解除测试。

## F. Platform–SEM API 边界实施约束

1. SEM 不持有 Platform PostgreSQL 凭据，不执行跨服务 SQL，也不直接读写 `delivery.task_run`。
2. Platform API 是 Run/Lease/Generation 的唯一写入口；SEM claim 请求必须由 Platform 在事务内完成授权、并发仲裁、generation 递增、token 签发和审计。
3. Platform 的 Transactional Outbox 只负责可靠触发；事件不作为业务状态权威。SEM 接收必须有幂等键、持久化接收记录和重试/对账机制。
4. SEM 数据库仅保存执行侧私有状态，例如命令投递账本、连接会话元数据和执行侧协调状态；不得复制并形成第二套 Run/Lease 权威状态。具体表结构在 SEM-02C 定义。
5. 两侧不做分布式事务。跨服务操作采用明确状态机、幂等 API、超时重试、对账与补偿。
6. API 使用服务身份认证、最小权限、TLS、请求签名或等效防重放机制；所有写请求绑定 request/idempotency ID、Run ID 和 generation。

## G. 政策合规自查（`engineering-lifecycle-policy.md` §3/§4）

- ✅ 事务完整性与并发安全：Phase 0 全部走现有 `claim_core` 事务模板/锁序，不新开旁路。
- ✅ 唯一执行权与安全进程/工作区生命周期：ADR-SEM-04/05 即为此设立。
- ✅ 凭据与权限安全：token 明文一次性下发、库内 hash、卷内无凭据（`deployment-topology.md` §6）。
- ✅ 关键状态迁移可审计：HIR/回收/接管全链路审计行（`runner-supervision-and-handoff.md` §4.2 ⑧）。
- ✅ 空库完整初始化：Phase 2/3 的 Schema 增量走迁移链，验收含空库初始化。
- ✅ 本政策不授权实施：本文档仅为设计，实施待架构复审批准。


## ADR-SEM-20 的强制协议约束

1. SEM 是唯一 Runner 调度入口；Platform 是唯一执行权授予者。SEM 的调度选择不构成执行权，必须等待 Platform Claim 成功响应。
2. Claim 请求必须包含经认证的目标 Runner/device identity。Platform 自行校验设备注册、租户/项目绑定、权限、监督策略、Scheduling Shield 与并发条件；不得信任 SEM 或 Runner 自报的裸 device_id。
3. Runner WSS 控制面唯一承载 Claim 协调、Runner Supervisor Heartbeat、Lease Renewal 请求、命令投递/ACK、取消、恢复/接管控制。Harness Platform MCP 保留业务上下文、Agent Activity、交互和交付/结果操作。
4. Lease Renewal 只由 Runner Supervisor 经 WSS 发起，SEM 通过服务 API 转发给 Platform 校验并提交；Harness Agent Activity 不续租。WSS liveness、Lease Renewal、Harness Activity 是三种不同事实。
5. Runner 不得直接轮询 Platform MCP Claim、命令、ACK 或恢复控制接口。迁移完成后删除这些旧控制写路径，不保留双通道；Harness MCP 业务能力不受影响。
6. `supervised` Runner 的用户确认由 SEM 调度流程收集；用户选择只是授权意图，Platform Claim 成功才授予执行权。默认 `unattended`，按策略自动选择。
7. SEM DB 仅保存 Runner 连接、Inbox、WSS 投递账本、进程观察和本地执行协调状态；不复制 Run/Lease/Generation/worker_command 的业务权威状态。


## H. SEM-02D 批量设计评审状态（2026-11-25）

用户要求将剩余设计一次性提交、后续集中评审。D-01–D-12 已形成完整候选设计包，统一为 Review Pending，详见 `sem-02d-review-package.md` 与 `sem-02d-closure-design-proposal.md`。本节不是 ADR，不改变 A 节已裁决项，也不把候选设计标记为 Ratified。D-13 已由用户批准并登记为 ADR-SEM-26。

评审通过后，仅将用户明确批准的项目登记为新的 ADR；如用户要求修订，先更新设计和所有引用，再记录批准状态。Phase 0 仍未启动。D-12 的代码级凭据注入/继承/泄漏面盘点是 Phase 0 前的强制只读门槛。


## I. 十项评审问题的修正状态（2026-11-25，Review Pending）

十项问题经只读核验整体成立。修正设计见 `sem-02d-review-findings-corrective-design.md`。特别注意：本节对 OQ-1/OQ-3/OQ-5 的改写是候选修正，**尚未批准，不改变 ADR-SEM-01–26 已确认记录**。HIR 最小可操作闭环前移 Phase 0；E3 进程退出报告与 Detached reconnect 放入 Phase 1；E6 不是终止证据；Detached 不加入 scheduling_shield；所有派发路径统一 dispatchability predicate。


## J. ADR-SEM-14 ACK 语义澄清提案（Review Pending）

ADR-SEM-14 中“ACK 必须由 Runner 在 OS 进程句柄确认退出后发送”仅适用于**终止确认 ACK / E3**，不能解释为普通命令 receipt ACK 也必须等到进程退出。新协议将以下事实分开：

1. `command.received`：Runner 已持久接收命令；
2. `command.result`：命令执行成功/失败；
3. `runner.process.exit`：OS 观察到精确进程身份已退出，满足条件时才构成 E3；
4. `continuation.consumed`：用户回复已注入且新 Agent 已启动。

自然退出、lease-loss cleanup、startup orphan cleanup 和 boot transition 也可产生 E3 process-exit evidence，不要求先有 cancel command。该澄清尚待评审，不新增或改写已批准 ADR。
