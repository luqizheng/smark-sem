# SEM-02C — 现有代码契约映射与差异审计

> 状态：**只读审计阶段；未修改业务代码、数据库迁移、Compose 或 Worker 主循环。**
>
> 审计基线：master @ 702593fc6a17abeb3378c11c5885ade4566e7bff
>
> 本文区分三类信息：现状事实由当前 master 代码直接确认；目标约束由 ADR-SEM-19–25 规定；尚未冻结的契约必须在 SEM-02D 设计阶段明确，不能当作已实现。

## 1. 审计结论

当前代码尚未实现 Platform–SEM 服务边界。执行链路仍是单体进程内、共享 Platform PostgreSQL 的实现：

1. ai-pm-worker 只读取 DATABASE_URL，创建一个 Platform PostgreSQL pool；同一进程启动业务 Job、Outbox、Run dispatch、进程监控、清理等循环。
2. Run claim、Lease、Generation、Run 状态、审计和执行事件均由 pm-application 直接使用 PgPool 操作。
3. pm-api 的 MCP 服务直接持有 Platform PgPool；Runner 通过 Streamable HTTP MCP 直连 Platform /mcp。
4. 当前代码未发现 SEM 专用 HTTPS API、SEM 数据库连接、Runner–SEM WSS listener/client 或 SEM Inbox。
5. 现有用户/Client 认证路径不能直接充当 SEM 服务认证：业务鉴权明确拒绝 roles=["service"] 的 service token；Client Credential 的现有接受路径限定在 /mcp。

因此，ADR-SEM-19 需要一次真正的服务边界重构，不能只给 ai-pm-worker 增加一个网络地址。

## 2. 当前实现事实映射

| 能力 | 当前代码落点 | 当前事实 | SEM-02C 处理方向 |
|---|---|---|---|
| Platform HTTP 入口 | apps/pm-api/src/main.rs、apps/pm-api/src/routes.rs | pm-api 使用 DATABASE_URL 创建唯一业务 pool；路由中挂载 MCP Streamable HTTP 服务 | 在 Platform 增加专用内部服务 API 路由与服务身份中间件 |
| MCP 服务 | crates/pm-mcp/src/server.rs | PmMcpServer 持有 PgPool；工具直接调用应用层函数；传输为 stateless Streamable HTTP JSON | 保留面向 Harness/Agent 的 MCP 业务入口；不要让 SEM 直接复用数据库连接 |
| Runner HTTP 客户端 | apps/ai-pm-runner/src/mcp.rs | McpClient 使用 reqwest POST 到 Platform MCP URL，Bearer 凭据；无 WSS 连接管理 | 增加 SEM WSS 客户端；逐项确定哪些控制操作迁到 WSS |
| Runner 配置 | apps/ai-pm-runner/src/runner_loop.rs | 配置只有 platform_mcp_url，没有 SEM endpoint / WSS URL | 增加独立 SEM endpoint 配置与连接生命周期 |
| Runner 启动 Harness | apps/ai-pm-runner/src/runner_loop.rs | 向子进程注入 AI_PM_MCP_URL、Lease Token、Generation；Harness 直接调用 Platform MCP | 明确 Harness 业务 MCP 与 Runner 控制 WSS 的边界，不要重复续租/重复 ACK |
| Runner 心跳 | runner_loop.rs::tick | Runner 定期调用 pm_report_progress；该调用是当前 Lease 续租路径 | 区分 Runner Supervisor Heartbeat、Agent Activity、Lease Renewal；一个 Lease 只能有明确的权威续租路径 |
| Runner 命令 | runner_loop.rs::tick、mcp.rs | Runner 定时 pm_poll_commands 并调用 pm_ack_command；当前走 Platform MCP | WSS 可承载实时命令和 ACK，但业务命令状态仍由 Platform API 原子裁决 |
| Worker 主循环 | apps/ai-pm-worker/src/main.rs | 一个 DATABASE_URL pool；Outbox 与 Run 执行循环在同一进程；当前没有 role 过滤或 SEM DB | 拆 Platform/SEM 装配；SEM role 不加载 Platform DB 凭据 |
| Run 调度 | crates/pm-application/src/run_executor.rs | claim_and_start、poll_active_runs、cancel_run、reconcile_orphans 等直接依赖 PgPool | 将业务权威操作改为 Platform API；进程 spawn/poll/terminate 留 SEM |
| Claim 事务 | crates/pm-application/src/run_dispatch/claim.rs | claim_core 在 Platform DB 事务内锁 Project/Run/Task，签发 Lease Token、Generation 并审计；Model A/B 共用事务模板 | 该事务继续只存在于 Platform；SEM 只能请求 claim，不能复制或自行签发 Lease |
| 执行器端口 | crates/pm-application/src/run_dispatch/port.rs | RunExecutor 只抽象 start/poll/terminate，不是 Platform Persistence/API Port | 增加服务 API 客户端端口；不能把现有 RunExecutor 误认为已具备跨服务边界 |
| 命令状态机 | crates/pm-application/src/worker_command.rs | worker_command 位于 Platform DB；命令 issued → delivered → acked/failed，带 claim lease 和 Generation 校验 | Platform 继续拥有命令业务状态；SEM DB 如需投递账本，只记录传输投递事实 |
| Outbox | crates/pm-infrastructure/src/outbox.rs、outbox_worker.rs、outbox_handlers.rs | Platform DB 内 at-least-once；handler 必须幂等；register_all_handlers 目录一致性校验 | Platform Outbox 触发 SEM HTTPS API；SEM 用独立 Inbox 幂等接收；SEM 不消费 Platform Outbox 表 |
| 执行事件 | delivery.task_run_event、pm-application/src/run_events.rs | Run/命令事件写入 Platform DB，幂等键含 Run、事件类型、Generation、dedupe tag | 业务审计事件仍由 Platform 持有；SEM 本机进程观察可先记 SEM 私有证据，再经 API 上报 |
| 设备身份 | apps/pm-api/src/auth.rs、device_claim.rs、devenv.device* | Client Credential cpk_ 当前仅在 /mcp 路径被接受；设备声明 header 仅是归因，不是认证 | WSS 必须定义专用 Runner 身份握手；不能把客户端自报 device id 当认证 |
| 服务身份 | apps/pm-api/src/auth.rs | roles=["service"] 明确被业务端点拒绝；当前没有 SEM 专用服务 API 鉴权契约 | 建立独立的 service-to-service 认证与授权，不放宽普通用户业务端点 |

## 3. Platform 数据权威必须保留的操作

以下操作不能迁成 SEM DB 的本地 SQL，也不能由 SEM 自己生成“看似成功”的状态：

| 业务操作 | 当前实现 | 目标归属 |
|---|---|---|
| Run 候选资格与 Claim | claim_core / claim_once | Platform API 内执行 |
| Lease Token 签发与撤销 | claim_core、Lease helpers | Platform API 内执行 |
| Generation 递增与 fencing | delivery.task_run.lease_generation | Platform API 内执行 |
| Run / Task 状态迁移 | run_executor、状态迁移应用服务 | Platform API 内执行 |
| Run 事件、业务审计 | run_events、audit_run | Platform API 内执行 |
| Worker Command 状态机 | worker_command::poll_commands/ack_command | Platform API 内执行 |
| 交付结果与验收输入 | 现有 MCP/REST 应用服务 | Platform API / MCP 内执行 |
| HIR 与人工审批 | Platform 业务域 | Platform 内执行；SEM 只提交执行侧证据/通知请求 |

SEM 可以持有执行侧私有事实，例如本机 PID/进程句柄、进程退出证据、Runner 连接状态、WSS 消息投递账本、Workspace 路径和本机清理状态。但这些事实不能成为 Run/Lease/Generation 的第二权威。

## 4. Outbox → HTTPS → Inbox 的契约边界

### 4.1 已有能力可复用

- Platform Outbox 已提供事务内追加、领取租约、at-least-once 重试和死信能力。
- Handler 明确要求幂等。
- register_all_handlers 对 EventCatalog 与 handler 注册集合做 fail-fast 一致性校验。
- pm-worker 与 ai-pm-worker 当前共享 Platform Outbox 表，因此任何 Platform Outbox handler 变更必须保持所有 Platform Outbox 消费者装配集合一致。

### 4.2 必须新增的能力

1. Platform 事务提交业务状态和 Outbox 事件；不能先提交业务事务、再单独发 HTTP。
2. Platform Outbox handler 调用 SEM HTTPS API；只有 SEM 已将 event_id 持久化到 SEM Inbox 后，才可返回成功。
3. SEM Inbox 对 event_id 唯一约束；重复投递返回已接收结果，不重复创建执行操作。
4. SEM 处理 Inbox 事件失败时，在 SEM 自己的数据库内记录可重试状态；不能要求 Platform 与 SEM 做分布式事务。
5. Outbox 通知只负责唤醒/触发。SEM 重启后必须能通过 Platform API 对账恢复，不能依赖只存在于内存中的消息。
6. SEM 不连接 Platform PostgreSQL，也不读取 integration.outbox_event。

### 4.3 不允许的实现

- 在 SEM 进程中创建 Platform PgPool。
- 把 Platform DATABASE_URL 作为 SEM 容器环境变量。
- 用 SEM DB 的 Run 副本决定 Lease 是否有效。
- HTTP 200 即认定 Run 已启动、进程已退出或终止成功。
- 只在内存 Channel / WebSocket 队列中保存待执行命令。

## 5. Runner–SEM WSS 映射与待定事项

现有 Runner 的控制动作混合在一个 Platform MCP 客户端中。迁移前必须逐项拆分，不能整体替换 MCP 或同时保留两套写路径。

| 当前 Runner 动作 | 当前路径 | SEM-02C 要求 |
|---|---|---|
| Claim 指定 Task | 当前 pm_claim_task → Platform MCP | **已关闭：SEM 唯一调度入口；SEM 通过 Platform HTTPS API 代表目标 Runner 请求 Claim，Platform 原子授权；Runner 不再直接 Claim** |
| Run Context | pm_get_run_context → Platform MCP | 评估保留 Harness 直连 MCP，或由 Runner/SEM 代理读取；授权语义不变 |
| Agent Progress / Result | Harness → Platform MCP | 默认保留业务工具语义；任何代理路径都必须由 Platform 校验 Lease Token 与 Generation |
| Runner Supervisor Heartbeat | 当前 pm_report_progress → Platform MCP | **迁至 Runner→SEM WSS；只记录 Runner supervisor liveness，不等同 Agent Activity 或进程存活** |
| Runner Lease Renewal | 当前 pm_report_progress → Platform MCP | **正式路径（ADR-SEM-21）：Runner Supervisor 专用 WSS `lease.renew` → SEM → Platform HTTPS API；Platform 唯一校验/提交者；WSS Heartbeat 和 Harness Agent Activity 均不续租。代码尚未迁移** |
| Interaction Marker | Runner → pm_report_interaction | 可保留 Platform 业务 API/MCP；若经 SEM 转发，需保持事件幂等与租约校验 |
| Command Delivery | pm_poll_commands → Platform MCP | **迁至 SEM WSS 推送/投递；SEM 保存传输账本，Platform 保留 worker_command 状态权威；Runner 不再 MCP 轮询** |
| Command ACK / Termination ACK | pm_ack_command → Platform MCP | **迁至 WSS 回传，SEM 转 Platform API；E3 终止证据绑定 Run、Generation、Command、进程身份** |
| Lease Reacquire / Recovery | pm_reacquire_lease → Platform MCP | **由 SEM 协调并调用 Platform API；Platform 原子签发新 Generation；Runner 不自行恢复/接管** |
| Consumption Receipt | pm_report_consumption → Platform MCP | 保留 Platform 证据校验，不得由 SEM 伪造消费证据 |

### 5.1 身份与撤销

- 当前 cpk_ 凭据的合法路径是 /mcp；WSS 握手需要专门的认证入口或短时连接票据。
- WSS 握手不能只信任 Runner 自报的 device id。
- 设备撤销、项目解绑、租约 Generation 变化必须能及时影响已建立连接；不能只在连接建立时校验一次后永久信任。
- lease_client_id 的现有身份绑定不得放宽。
- WSS 断线不代表 Runner 进程死亡，更不代表 Harness 进程死亡。
- 重连后必须进行身份、当前 Generation、活动 Run 和未完成命令同步；不能盲目重放旧 Generation 命令。

### 5.2 连接与消息可靠性

消息至少需要稳定 message_id、schema_version、runner_id/device_id、run_id、generation、command_id（适用时）、发送时间、关联请求 ID。命令消息、普通消息 ACK、进程终止 ACK 是不同语义。

TCP/WebSocket 只提供传输，不提供业务 exactly-once。必须由 Platform 状态机、SEM Inbox/Delivery Ledger、幂等键、ACK 和重连对账共同提供可靠性。

## 6. 认证边界发现

当前 apps/pm-api/src/auth.rs 的普通 Bearer 链路包含身份解析、真人 Principal 映射和激活检查；代码注释明确说明 Service Token 在业务端点被拒绝。Client Credential cpk_ 则由现有 /mcp 通道专门解析，并绑定 Client Registry 与项目授权。

因此目标服务认证必须明确区分：

- **Platform ↔ SEM**：service identity；audience 绑定 SEM/Platform 对端；最小权限 scope；短时凭据/轮换；防重放与请求关联。
- **Runner ↔ SEM**：Client/Device 身份；项目绑定和撤销即时性；WSS 长连接的持续授权校验。
- **Harness ↔ Platform MCP**：现有 Client Credential / Agent 授权语义，不能因新增 SEM 而绕过。

不得通过放宽 resolve_principal 的 Service Token 拒绝逻辑来让服务 token 混入普通业务身份。

## 7. 高优先级现状风险

### R-01：孤儿 Run 仍存在无进程证据自动回收路径

当前 run_executor::reconcile_orphans 对 running 且 Lease 过期超过一小时的 Run，直接把 Run 改回 queued 并释放 Task；该分支没有先取得 E1/E2/E3 进程终止证据。它与 SEM-02A 已确认的执行安全红线冲突。

**处理要求：Phase 0 必须先修复。** 只允许 E1/E2/E3 证明执行端已终止后自动重派；E4 隔离并创建 HIR；E5 保持不确定，禁止自动重派。不能因为改成 HTTP API 或 WSS 而延后。

### R-02：当前 RunExecutor 不是跨服务边界

RunExecutor 只抽象本机 start/poll/terminate；run_executor.rs 本身仍直接读取和写入 Platform DB。角色化装配不能只在 main.rs 过滤循环，必须把业务操作替换为 Platform API port。

### R-03：WSS 与 MCP 当前控制动作重叠

Runner 当前通过 MCP 做 Claim、Lease Renewal、命令轮询/ACK、恢复和交互报告；Harness 也通过 Platform MCP 执行业务读写。若新增 WSS 而不先划定动作归属，会形成重复续租、双命令通道、双 ACK 或绕过身份校验。

### R-04：长连接撤权语义尚未定义

现有 cpk 设计强调每请求查库、撤销即时；WSS 是长连接。必须定义连接存续期间的撤权检测、连接关闭时限、未完成命令处理与重新认证策略。

## 8. 建议的实施分层

| 阶段 | 交付 | 先决条件 |
|---|---|---|
| Phase 0 | 修复 B3-2 / reconcile_orphans，落实 E1–E5 进程证据门禁 | 先于服务拆分，避免把现有双执行风险带入新架构 |
| Phase 1A | 定义 Platform 内部 API 应用服务、DTO、服务身份、错误模型、幂等键 | 明确所有 Run/Lease/Generation 的 Platform 权威写入口 |
| Phase 1B | Platform Outbox → SEM HTTPS Inbox，建立 SEM 独立 DB 与对账 | 不共享 DB、不做分布式事务 |
| Phase 2 | 定义 Runner WSS 消息协议、握手身份、重连、撤权、ACK 和 Generation fencing | 先完成 §5 动作归属表，不保留双写路径 |
| Phase 3 | ai-pm-worker 角色化装配；SEM role 仅有 SEM DB + Platform API Client + WSS listener | Platform 与 SEM 服务 API 契约通过集成测试 |
| Phase 4 | 独立 Docker 部署、空库初始化、故障恢复与多 Runner 验收 | Workspace 仍只作可重建执行资产，不做备份 |

## 9. SEM-02C 初审时列出的设计门槛（由 SEM-02D 继续关闭）

1. Runner 的 Claim 由谁发起：Runner 直接调 Platform，还是 SEM 代表目标 Runner 调 Platform？
2. Runner WSS 承载哪些控制动作；Harness 的 Platform MCP 业务工具保留哪些？
3. Lease Renewal 路径已由 ADR-SEM-21 冻结；仍需定义精确 API/WSS DTO、校验与失败语义。
4. worker_command 业务状态留 Platform 后，SEM Delivery Ledger 的最小字段是什么？
5. SEM DB 的最小表集合与字段所有权是什么？
6. Platform Service Token 的签发、audience、scope、轮换和撤销机制是什么？
7. Runner WSS 如何复用 Client Registry 身份并保持设备撤权即时性？
8. Outbox 哪个业务事务发出 SEM dispatch 事件；如何保证 Run 创建与通知同事务？
9. Platform API 不可达、SEM DB 不可达、WSS 断线、SEM 重启时分别如何保持唯一执行权？
10. 现有 ai-pm-worker 各循环如何拆分；哪些循环继续留在 Platform，哪些执行事实必须在 SEM 主机采集？

**本阶段结论：** 当前代码能够提供业务状态机、Claim 事务、Lease/Generation fencing、Outbox、命令状态机和本机执行器的基础能力；但 Platform–SEM 服务 API、SEM 私有持久化、Runner WSS、服务认证和跨服务恢复均尚未实现。完成 G-01–G-21 架构门槛审查并满足对应 Phase 前置验收后，才具备开始实施的条件。


## 10. ADR-SEM-20 已关闭的控制通道契约

用户已确认 SEM 是 Runner 控制面的唯一派发与接管协调者。Claim 发起方和 Runner 控制轮询归属已关闭；Lease Renewal 唯一路径已由 ADR-SEM-21 冻结：

- SEM Scheduler 选择目标 Runner；`supervised` 必须先完成用户通知与明确选择，`unattended` 默认自动选择。
- SEM 使用专用 service identity 调用 Platform HTTPS Claim API，并显式传入目标 Runner/device identity。Platform 不能信任裸 device_id，必须从注册/绑定记录验证身份、租户、项目、权限、监督策略、Scheduling Shield 和并发条件。
- Claim 成功前禁止向 Runner 派发可执行命令；Claim 成功响应是 Platform 授予执行权的唯一事实。
- Runner WSS 是控制通道唯一入口：Supervisor Heartbeat、Lease Renewal 请求、命令、ACK、取消、E3、重连同步和接管控制。
- Lease Renewal 唯一路径为 Runner Supervisor WSS → SEM → Platform HTTPS API；WSS liveness 和 Harness Agent Activity 均不续租。该路径已由 ADR-SEM-21 冻结，详见 `service-protocol-security-and-persistence.md`。
- Harness Platform MCP 保留业务面：项目/任务上下文、Agent Activity、Interaction、交付/结果与知识业务操作。不得将业务 MCP 整体迁到 SEM。
- 删除 Runner 对 Platform MCP 的 Claim、Lease Renewal、命令轮询/ACK、恢复/接管控制路径；不保留双控制面。迁移必须一次性关闭旧写路径并有集成测试证明无旁路。

当前代码仍未实现上述目标；此处为冻结后的设计契约，不得描述为已交付功能。


## 11. Ratified SEM-02C security and persistence baseline (ADR-SEM-21–25)

The user-ratified target design is recorded in `service-protocol-security-and-persistence.md`:
- Platform↔SEM uses independent service identities, short-lived asymmetric JWTs, audience/scope checks and key rotation; service tokens are not human principals.
- Runner obtains a short-lived single-use WSS ticket from Platform using registered device credentials; SEM consumes the ticket ID and continuously revalidates authorization via Outbox revocation events plus bounded API checks.
- SEM minimum private persistence: Inbox, Runner Connection, Ticket Use, Dispatch Operation, Command Delivery, Platform Delivery and Process Observation.
- Claim dispatch is idempotent across lost HTTP responses; SEM does not persist plaintext Lease Tokens.

These are ratified target architecture decisions, not current-code facts; implementation remains outstanding.

## 8. SEM-02D 十项评审问题代码契约复核（2026-11-25）

本节补充本文件原始 SEM-02C 映射之后的只读复核结论；逐项依据、设计修正见 [`sem-02d-review-findings-corrective-design.md`](./sem-02d-review-findings-corrective-design.md)。

- Interaction 创建事务会持久化 Interaction、human_wait shield、task_waiting、terminate worker_command 和 audit；当前 Runner `tick` 轮询命令，`execute_command` 处理 terminate/continue；continue 创建新 Agent Session 并注入 response。SEM-local CodexExecutor 没有等价的 Interaction continue/reply-injection command consumer。
- Runner 自然退出由本机 reap 观察后记录日志并释放 active；lease-loss cleanup 走本地 terminate/reap 和 cleanup evidence。尚无完整独立的、可在 Lease 失效后可靠上报的 Runner process-exit evidence spool + WSS 路径。
- `recovery.rs` 的 reacquire 路径精确要求 `scheduling_shield='start_wait'`、同一 lease_client_id 和 responded Interaction；它不覆盖执行中途 Runner Detached。
- `codex_executor.rs` 在 PID record 缺失且 logs 目录缺失时可返回 `Done{Lost}`；`run_executor.rs` 将 Done Lost 进入失联恢复。若 Platform 已记录 stage=started，卷丢失不能作为进程死亡证据。
- `integration.notification` 当前无 recipient 字段；Interaction 创建事务没有创建 notification/outbox notification delivery。
- Session Manager 原始设计将 Native Session ID 采集放在 SEM `poll_active_runs`；远端 Runner 的 CODEX_HOME 只能由 Runner 本机访问。Runner continue 当前是 checkpoint/reply 注入 + 新进程，不等于 Native Resume。
- `scheduling_shield` CHECK 只有 none/human_wait/start_wait/timed_out；B06-D3 把 Run 回 queued 后，普通 queued claim 不经过 claimed-only 的 candidate_shield 检查。必须在锁内统一执行 dispatchability predicate。

注意：本节是现状审计，不代表修复已实现。Phase 0 未启动。
