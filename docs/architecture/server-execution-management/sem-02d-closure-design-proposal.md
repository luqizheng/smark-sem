# SEM-02D — 阻断项关闭设计提案（D-01–D-13）

- 状态：**Corrective Design In Progress；D-01–D-12 Review Pending；D-13 已由用户确认并正式冻结为 ADR-SEM-26**
- 日期：2026-11-25
- 基线：当前 master 的 SEM-02D 审查报告及 ADR-SEM-01–26
- 范围：D-01–D-13 候选设计及十项评审问题的修正；上一轮完整性结论已撤回，当前以 corrective-design 为补充设计主文档。
- 明确边界：本文件只提出设计，不代表已修改代码、Migration、API、WSS、Docker 或运行配置；Phase 0 仍未启动。
- 不重开：独立 DB、单一 Git origin、不备份 Workspace、不引入消息中间件、SEM 唯一 Runner 控制面、Lease Renewal 唯一路径、Runner 默认 unattended 等已确认决策。

## 0. 设计总原则

1. Platform PostgreSQL 是 Run、Lease、Generation、HIR、命令业务状态及业务审计的唯一权威。
2. SEM DB 只记录执行侧与传输侧事实；不得以本地副本授权执行或解除 Platform 安全屏障。
3. 对所有自动 Claim、重派、回收和 retry/requeue，使用同一个 Platform 侧执行安全屏障谓词。
4. 任何不确定的进程状态都 fail closed：保留隔离、创建/关联 HIR，不自动重派。
5. HTTP/WSS 采用显式版本、稳定幂等键和可恢复状态；传输 ACK 不等于业务完成，命令 receipt 不等于进程终止。
6. D-01–D-12 已完成成套设计，状态统一为 Review Pending；用户评审通过后才可从 Proposed 转为 Ratified。D-13 已按 ADR-SEM-26 冻结。代码事实仍须在 Phase 0 前按最新 HEAD 复核。

## 1. D-01（P0）执行不确定性屏障物理模型

**建议：在 Platform 新增独立表 `delivery.run_execution_barrier`，不复用现有 Interaction `scheduling_shield`。**

建议字段：
- `id uuid PK`
- `tenant_id uuid NOT NULL`
- `project_id uuid NOT NULL`
- `task_run_id uuid NOT NULL`
- `lease_generation bigint NOT NULL`
- `barrier_kind text NOT NULL`（V1 固定 `execution_uncertain`）
- `state text NOT NULL`（`active` / `released`）
- `evidence_class text NOT NULL`（`E4` / `E5`）
- `reason_code text NOT NULL`
- `first_detected_at timestamptz NOT NULL`
- `last_observed_at timestamptz NOT NULL`
- `hir_id uuid NOT NULL`
- `released_at timestamptz NULL`
- `released_by uuid NULL`
- `release_reason text NULL`
- `release_evidence_ref text NULL`
- `version bigint NOT NULL DEFAULT 1`

约束与语义：
- 以 `(tenant_id, project_id, task_run_id, lease_generation)` 为范围；同一 Run+Generation 最多一条 active barrier（partial unique index）。
- `hir_id` 外键指向 Platform HIR；创建 HIR 与 barrier 必须同一事务提交。
- barrier 不覆盖、不改写 Interaction shield；自动调度必须同时满足“无活动 Interaction shield”与“无活动 execution barrier”。
- 唯一检查入口封装为 Platform domain predicate，例如 `is_run_dispatchable(run_id, generation)`；claim、B3-2、B06-D3、orphan reconciliation、retry/requeue、handoff claim 全部调用同一语义。
- E1/E2/E3 证据通过验证后，Platform 在单事务内记录证据引用、终态化/回收旧 Run、释放 barrier 并生成下一 Attempt；不得先释放后回收。
- E4/E5 不允许自动释放。人工风险接受是独立的高权限处置路径，必须显式风险确认、记录旧进程/凭据处置策略，并且**不能把人工接受风险伪装成 E1/E2/E3**。

## 2. D-02（P0）Phase 0 最小 HIR 与 Phase 4 完整 HIR

**建议：Phase 0 创建正式 HIR 主表，Phase 4 扩展同一实体，不做临时表或二次迁移替换。**

Phase 0 最小字段：
- `id uuid PK`、`tenant_id`、`project_id`、`task_run_id`、`lease_generation`
- `reason_code`、`evidence_class`（E4/E5）、`status`（`open` / `resolved` / `closed`）
- `created_at`、`updated_at`、`version bigint`
- `resolution_code NULL`、`resolved_at NULL`、`resolved_by NULL`、`resolution_evidence_ref NULL`

约束：
- 同一 tenant + Run + Generation 最多一个活动 HIR（partial unique index）。
- HIR 的创建、execution barrier 创建、Run 安全状态/审计写入必须在同一 Platform 事务中。
- HIR 使用乐观并发版本 `version`；每次状态变化写审计事件，禁止只改当前行而无历史。
- Phase 0 只需内部创建、查询、受控关闭接口；没有通知 UI、Runner 选择 UI 或自动 handoff。
- Phase 4 在同一实体上增加通知投递、assignee、用户选择意图、处置步骤、关闭原因及完整 UI/API；不能因 Phase 4 再建一张 HIR 表。
- HIR 关闭本身不解除 execution barrier；只有符合 D-01 的安全事务可以解除。

## 3. D-03（P0）Platform–SEM HTTPS API wire contract

**建议：所有内部接口置于 `/internal/v1`，JSON DTO，RFC 3339 UTC 时间，UUID 标识；统一错误 envelope。**

建议路由：

| Method / Route | 调用方 | 用途 / 幂等 |
|---|---|---|
| POST `/internal/v1/sem/inbox/events` | Platform → SEM | 接收 Outbox 事件；`event_id` 唯一 |
| POST `/internal/v1/sem/dispatch/operations` | SEM → Platform | 读取当前候选/资格并请求指定 Runner Claim；`claim_request_id` |
| GET `/internal/v1/sem/dispatch/operations/{claim_request_id}` | SEM → Platform | 查询同一 Claim 幂等结果，不创建新 Claim |
| POST `/internal/v1/sem/leases/renewals` | SEM → Platform | Lease Renewal；`request_id` |
| GET `/internal/v1/sem/runners/{runner_id}/authorization` | SEM → Platform | 授权重验证；不得仅凭 SEM 缓存授权 |
| GET `/internal/v1/sem/commands` | SEM → Platform | 按 Runner/Run/Generation 读取待投递命令 |
| POST `/internal/v1/sem/commands/{command_id}/receipt` | SEM → Platform | 记录 Runner receipt ACK；幂等 |
| POST `/internal/v1/sem/executions/reports` | SEM → Platform | 执行观察/状态报告；幂等 |
| POST `/internal/v1/sem/executions/termination-evidence` | SEM → Platform | 提交 E3；按 Run+Generation+command+process identity 幂等 |
| POST `/v1/runner/connect-tickets` | Runner → Platform | 设备凭据认证后签发一次性 WSS Ticket；专用设备认证端点 |

通用请求头：`Authorization: Bearer <service JWT>`（设备 Ticket endpoint 使用设备认证）、`Idempotency-Key`（所有变更请求）、`X-Correlation-Id`、`X-Protocol-Version: 1`。

通用成功 envelope：`{ "request_id": "...", "result": { ... } }`。错误 envelope：`{ "error": { "code": "...", "message": "...", "retryable": false, "correlation_id": "..." } }`。不得返回 SQL、堆栈、凭据或 token verifier。

错误分类建议：
- 400 schema/字段非法；401 身份无效；403 scope/设备授权失败；404 资源不存在；409 generation/owner/idempotency 冲突；410 ticket/lease 已过期；422 状态不允许；429 限流；503 可重试服务不可用；504 结果未知，调用方必须用原幂等键查询/重试。
- Claim 的 504/连接超时永远表示“结果未知”，不得生成新 key 再 Claim。
- 建议默认超时：普通 API 5s、Claim 10s、Inbox accept 3s；重试指数退避并加 jitter，受总预算约束。具体值允许部署配置，但上限由服务端策略限制。

Claim 请求必须包含目标 Runner 身份、稳定 `claim_request_id`、候选 Run 或调度请求上下文；Platform 自行校验设备注册、项目绑定、监督模式、资格、所有 Shield、并发锁及 Generation。SEM 不得提交任意 Runner ID 即获得租约。

## 4. D-04（P0）Runner–SEM WSS wire contract

统一 JSON envelope：
```json
{
  "schema_version": 1,
  "message_id": "uuid",
  "connection_epoch": 12,
  "correlation_id": "uuid",
  "sent_at": "RFC3339 UTC",
  "type": "runner.heartbeat",
  "run_id": null,
  "generation": null,
  "payload": {}
}
```

- 身份来自已验证 Ticket 与当前连接，不信任 payload 的 runner/device ID。
- 执行消息必须携带 `run_id`、`generation`；命令消息另带 `command_id`；进程证据另带完整 `process_identity`。
- V1 消息类型：`session.ready`、`runner.heartbeat`、`lease.renew`、`execution.dispatch`、`execution.accepted`、`execution.rejected`、`command.deliver`、`command.received`、`command.result`、`command.failed`、`process.terminated`、`runner.reconnect_sync`、`runner.resource.report`、`connection.revoked`、`server.drain`、`server.shutdown`。
- 每条需要可靠投递的服务端命令先写 SEM `command_delivery` 再发送；Runner receipt ACK 只证明收到，不证明执行成功或进程退出。
- `process.terminated` 仅在 OS wait/handle 确认目标进程树终止后发送；SEM 转发 Platform 验证，不能凭 WSS ACK 生成 E3。
- 连接 epoch 每次成功重连单调增加；旧 epoch、旧 generation、重复 message_id 被拒绝或按幂等结果响应。
- 推荐心跳 15s，连接失活阈值 45s；值由部署配置但有硬上限。最大消息 1 MiB；每连接有界 in-flight 数与背压，超过阈值拒绝新 dispatch，不丢弃已持久化命令。
- 重连顺序：重新获取 Ticket → 建立新 epoch → 身份/授权重验证 → Runner 上报活动进程清单及每项 process identity → SEM 与 Platform 对账 Run/Generation/command → 决定继续、取消或 E4/E5 隔离 → 才恢复新命令投递。不能把“重连成功”当作进程状态证明。

## 5. D-05（P0）SEM 七表物理模型基线

所有表位于 SEM 自有 PostgreSQL schema `sem`；主键 UUID；时间戳 UTC；外部 Platform ID 仅作为引用值，不建立跨数据库 FK。租户/项目标识仅作隔离和查询，不构成授权依据。

| 表 | 关键字段与唯一性 | 状态/索引建议 |
|---|---|---|
| `inbox_event` | `event_id PK`、type、schema_version、payload_ref/minimal_payload、received_at、status、attempt_count、next_attempt_at、processed_at、last_error_code | `received/processing/processed/retry/dead`；索引(status,next_attempt_at) |
| `runner_connection` | `connection_id PK`、runner_id、credential_ref、epoch、connected_at、last_seen_at、auth_valid_until、status、revoked_at、disconnected_at | 每 Runner 最多一个 active epoch；索引(runner_id,status,epoch DESC) |
| `runner_ticket_use` | `jti PK`、runner_id、consumed_at、expires_at | 按 expires_at 清理，但保留时间不得短于 Ticket 最大寿命+时钟偏差+安全余量 |
| `dispatch_operation` | `operation_id PK`、event_id、run_id、target_runner_id、claim_request_id UNIQUE、stage、platform_result_ref、generation、created_at、updated_at、last_error | `created/claim_pending/claimed/delivery_pending/dispatched/cancel_pending/terminal/blocked`；索引(stage,updated_at) |
| `command_delivery` | `delivery_id PK`、platform_command_id、run_id、generation、runner_id、message_id UNIQUE、status、attempt_count、sent_at、received_at、terminal_ack_at、next_attempt_at | 唯一(platform_command_id,generation,runner_id)；`queued/sent/received/acked/failed/expired`；索引(status,next_attempt_at) |
| `platform_delivery` | `delivery_id PK`、operation_ref、idempotency_key UNIQUE、target_operation、payload_ref、status、attempt_count、next_attempt_at、last_http_status、last_error_code | `pending/sending/delivered/retry/dead`；索引(status,next_attempt_at) |
| `process_observation` | `observation_id PK`、runner_id、run_id、generation、connection_epoch、command_id NULL、process_identity JSONB、evidence_class、observed_state、observed_at、evidence_digest UNIQUE、payload_ref | append-only；索引(run_id,generation,observed_at DESC) |

通用规则：
- 状态更新使用条件 UPDATE（旧状态 + version/updated_at）或行锁；并发 worker 用 `FOR UPDATE SKIP LOCKED` 领取待处理记录。
- `process_observation` 只追加，不覆盖历史；证据原文最小化，优先保存规范化字段和 digest。
- Ticket replay 记录清理不早于 Ticket 有效期+时钟偏差+最大连接握手窗口；其他表按业务审计/重试要求设置保留期，不无限保存 payload。
- SEM migration 由 SEM 部署单元单独执行；启动 readiness 必须验证 schema 版本、数据库可写、Workspace root 可用。SEM 不读取 Platform `DATABASE_URL`。
- 最终 SQL 类型、FK 与索引名称应在迁移文件评审时按当前领域 UUID/租户约束统一；本表是 DDL 生成前的结构契约，不应误称为现有 Schema。

## 6. D-06（P0）应用层 Ports / Adapter 与 SQL 归属

**建议按业务权威与执行事实拆分端口，不以 PgPool 作为跨边界依赖。**

Platform-owned ports（由 Platform SQL adapter 实现）：
- `RunClaimPort`、`LeasePort`、`WorkerCommandPort`、`RunLifecyclePort`、`RunEventAuditPort`、`HIRPort`、`RunnerAuthorizationPort`。
SEM-owned ports（由 SEM 本地 adapter 实现）：
- `ProcessSupervisorPort`、`WorkspacePort`、`ProcessObservationPort`、`CommandDeliveryLedgerPort`、`InboxPort`、`PlatformDeliveryPort`。

SEM application service 调用 Platform-owned ports 的 HTTP client adapter；Platform route handler 调用 Platform SQL adapters。Platform PgPool 只能在 Platform composition root 和 SQL adapter 中创建/注入。SEM composition root 只接 SEM DB pool 与本机 executor；禁止 `DATABASE_URL` 指向 Platform。

当前共享 application service 若混合 SQL 与 process side effect，必须先切开用例边界；不能简单把现有 `run_executor.rs` 复制到 SEM。所有 SQL statement 需归入字段/表级 ownership matrix；CI 增加 SEM 构建/配置检查，确保没有 Platform DB secret/连接。

## 7. D-07（P1）Service / Ticket 密钥生命周期

- Platform 与 SEM 使用不同 service signing key pair；Runner WSS Ticket 使用 Platform 的独立 ticket signing key pair，不复用 service JWT 私钥。
- 私钥由各自部署的 secret manager / OS secret store 提供给服务进程；不写入 Git、镜像、Workspace 卷或普通日志。若部署环境无 KMS，使用受限文件权限的外部挂载 secret，并记录轮换责任人。
- 公钥通过受认证的配置分发/固定信任清单发布，携带 `kid`；验证端缓存当前与下一把公钥。未知 kid 触发一次受控刷新，刷新失败则 fail closed。
- 轮换采用 overlap：先发布新公钥，再切换签名，等待最大 JWT/Ticket TTL + clock skew 后移除旧公钥。紧急泄漏时立即禁用 kid、撤销 service/device，并断开受影响 WSS。
- JWT TTL ≤5 分钟；WSS Ticket TTL ≤60 秒、单次使用；允许时钟偏差建议 30 秒以内。Ticket claims 固定包含 `iss/sub/aud/jti/iat/nbf/exp/kid/scope/runner_id/credential_id`。
- 30 秒授权新鲜度是 SEM 从最近一次成功 Platform revalidation 起算的最大缓存年龄；Outbox 撤权事件可提前失效。到期未能重验证，先禁止派发/命令，再关闭连接；活动进程按 E1–E5 处置，不视为已终止。
- `jti` replay 防护按 token/ticket 类型分别处理；不能用 JWT jti 代替业务幂等键。

## 8. D-08（P1）Claim 幂等响应加密与保留

- Claim 事务内保存业务 Lease/Generation 结果及加密的可重放响应元数据；两者同事务提交。
- 建议 AES-256-GCM 信封加密：Platform 持有 KEK（外部 secret manager/KMS），每条记录生成随机 DEK 加密响应，KEK 包装 DEK；记录保存 ciphertext、nonce、tag、wrapped_dek、key_id、created_at、expires_at。不得把 DEK/KEK 写入同一数据库明文。
- 明文 Grant 只在响应构造时解密进入内存；访问日志、Tracing span、异常、SQL 参数日志全部脱敏。SEM 不持久化 Lease Token。
- 相同 `claim_request_id` + 相同规范化 payload 返回同一结果；相同 key + 不同 payload 返回 409。
- 建议幂等响应保留 24 小时（需与最长网络恢复/调度重试预算核对）；过期后不允许该 key 重新 Claim。SEM 应查询 Claim 状态/当前 Lease，而不是创建新 key 重试。若无法恢复原 token，走 Platform guarded cancel/recovery。
- KEK 轮换支持多 key_id 解密旧记录；过期记录清除 ciphertext/wrapped DEK，保留不含秘密的幂等 tombstone，防止旧 key 被重用。

## 9. D-09（P1）E3 信任与跨 OS Process Identity

V1 信任假设：注册且当前未撤权的 Runner Supervisor 是 OS 进程观察者；E3 是经过身份/Generation/命令/进程绑定的设备证据，不是抵御已攻陷设备的硬件证明。高保证设备证明另立 ADR，不阻塞 V1。

规范化 `process_identity`：
- 通用字段：`pid`、`parent_pid`、`process_started_at`（OS 可提供时）、`executable_fingerprint`、`process_group_or_job_id`、`supervisor_instance_id`。
- Windows：优先以持有的 Process Handle + CreationTime + Job Object 作为观察锚点；不能只用 PID。Runner 重启后句柄丢失时，必须重新验证 PID+CreationTime/Job 关联，无法验证则 E5。
- Linux：pidfd 优先；否则 PID + `/proc/<pid>/stat` starttime + process group/session；无法取得稳定身份则 E5。
- macOS：使用可用的 process start time / audit token 等 OS 标识；无法区分 PID reuse 则 E5。
- 进程树退出判据：Harness 主进程及由 Supervisor 管理的 Job/process group 中所有受管子进程均退出；仅 shell wrapper 退出不构成 E3。
- E3 payload 必须绑定 Runner identity、connection epoch、Run、Generation、command ID、process identity、exit code、observed_at、evidence digest。字段缺失、generation/epoch 不匹配、进程身份不一致或迟到冲突证据均降级 E4/E5，不自动回收。

## 10. D-10（P1）Platform Command 与 SEM Delivery 映射

| Platform worker_command | SEM command_delivery / Runner | 规则 |
|---|---|---|
| issued | queued | Platform API 读出命令后 SEM 建投递记录 |
| delivered | sent 或 received | Platform 只有在 SEM 已持久化投递意图并成功提交相应 API 后更新 delivered；Runner receipt ACK 后单独更新 SEM received |
| acked | acked | 仅代表命令业务确认完成；由 SEM 转发 Runner 结果并由 Platform 校验 |
| failed | failed | Runner 明确报告命令执行失败，Platform 依据 Run/Generation 校验后落业务状态 |
| 终止命令 | receipt ACK + E3 两阶段 | receipt ACK 只证明命令收到；E3 是进程退出证据，不能合并为一个 ACK |

异常处理：
- Runner 收到命令但 receipt ACK 丢失：SEM 重发同 message_id，Runner 幂等响应。
- SEM 已落 receipt、Platform API 不可达：SEM `platform_delivery` 重试同一幂等键；不得重发为新业务命令。
- 迟到 ACK：按 command_id + Run + Generation + message_id 验证；旧 generation 只记审计/拒绝，不改变当前状态。
- E3 独立提交；命令业务 acked 不自动释放 execution barrier。

## 11. D-11（P1）HIR 状态机与屏障解除

建议状态机：
`created → notified → awaiting_runner_selection → accepted → in_progress → resolved → closed`。
无人监督 Runner 默认不要求用户预选；HIR 通知后进入 `accepted` 仅表示处置流程已接收，不表示执行权已转移。

严格推进条件：
- `created`：Platform 在 E4/E5 barrier 同事务创建。
- `notified`：通知服务确认持久化通知投递，不是“尝试发送”。
- `awaiting_runner_selection`：仅 supervised 场景；用户选择写入 intent，不改变 Run lease、Generation 或 barrier。
- `accepted`：有权限的用户/处置流程明确接受 HIR；仍不代表新 Runner 已获执行权。
- `in_progress`：只有 Platform Claim 成功、目标 Runner 身份有效且 Generation 已递增后才能标记 handoff 已执行；UI 应区分“处置处理中”与“新执行已接管”。
- `resolved`：Run 已安全终态化，或新的合法 Attempt 已启动且旧执行端已由 E1/E2/E3 证明终止/隔离策略完成。
- `closed`：复盘与审计完成；关闭 HIR 不自动解除 barrier。
- 原 Run 自愈关闭必须基于同一 Run+Generation 的可信恢复证明；迟到 heartbeat、WSS reconnect、用户选择、单纯超时均不能关闭 barrier。
- 人工风险接受需单独权限、二次确认、风险说明、外部副作用检查项和审计；若旧进程仍不确定，原 barrier 仍保持 active，不能因此允许普通自动重派。

## 12. D-12（P1）Harness 凭据清单与边界

| 凭据类型 | 典型持有者 | 是否注入 Harness | 规则 |
|---|---|---|---|
| Runner/SEM WSS 身份与 Ticket | Runner Supervisor | 否 | 仅 Supervisor 使用；短时 Ticket；不传 Harness |
| Platform service JWT | SEM service | 否 | 仅 SEM server 使用；最小 scope |
| Run Lease Token | Runner Supervisor / Harness MCP bridge（若业务协议仍要求） | 仅在必要业务调用时 | 优先由 Supervisor 代理业务请求；若 Harness 直连 MCP 是既定模式，则只注入单 Run/Generation token，短时、不可写控制面；日志全脱敏 |
| Git read/write credential | 执行端 credential broker | 按任务最小需要 | 优先短时、Repository-scoped；SSH key 临时文件权限最小、退出/回收清理；无法即时撤销时按潜在外部副作用处理 |
| LLM/provider credential | Harness provider adapter | 是，若 Harness 必需 | 使用项目/用户授权的最小 scope；不得把 SEM service key 或设备凭据传给 Harness |
| MCP URL / public endpoint | Harness | 是 | 非秘密配置；不得携带 bearer token 于 URL/query |
| Device credential / connect Ticket | Runner Supervisor | 否 | 不写 Workspace、不传 Harness、不记录日志 |

Phase 0 前需按实际 Codex/其他 Harness 启动器逐项验证：环境变量、命令行参数、配置文件、子进程继承、stdout/stderr、executor-events、crash dump、临时 SSH 文件和日志脱敏。任何无法即时撤销的 Git/API 凭据必须在 HIR 中明确标注潜在外部副作用；DB Lease Token 失效不代表 Git/LLM 凭据已撤销。

## 13. Phase 依赖与验收调整

- Phase 0 前必须 ratify D-01/D-02，并冻结 barrier/HIR 的 Platform Migration 与统一 dispatch predicate；Phase 0 仅做最小 HIR 持久化，不做通知/选择 UI。
- Phase 1 前必须 ratify D-03–D-08，冻结 HTTPS/WSS wire contract、SEM DDL、ports/adapter、key lifecycle、Claim idempotency encryption。
- Phase 2 部署验收同时验证 SEM 无 Platform DB secret、SEM DB 独立迁移、Outbox→Inbox 持久确认、Workspace 运行期卷与断电恢复；不建设 Workspace 备份。
- Phase 3 只做 Session Manager / native session 采集；Resume 仍默认关闭。
- Phase 4 扩展既有 HIR 表与 UI/handoff，不重建 HIR；落实 D-09–D-11。
- Phase 5 进行真实双 Runner、多 OS、分区、密钥撤销、凭据副作用与并发验收。
- D-12 凭据盘点必须在 Phase 0 代码改动前完成，Phase 0/1/2 各自验收真实注入与撤销行为。


## 15. D-13（P1）Runner 资源感知与同机并发准入

**已确认并冻结为 ADR-SEM-26。** Runner 必须报告 CPU、内存和 Workspace 所在磁盘卷资源；SEM 必须基于资源快照、任务资源画像和原子预留，决定同一台 PC 是否可接收并发任务。

### 15.1 资源采集与上报

Runner Supervisor 定期采集并通过现有 WSS 控制连接发送 `runner.resource.report`。资源报告与 WSS Heartbeat 分离：Heartbeat 证明监督连接存活；Resource Report 描述某个采样时刻的资源快照，二者都不续租。

V1 最小指标：

| 类别 | 必报字段 | 用途 |
|---|---|---|
| CPU | logical_cpu_count、cpu_utilization（短窗口与较长窗口）、sample_duration_ms | 判断 CPU 是否有并发余量；使用窗口值，避免瞬时采样抖动 |
| Memory | total_bytes、available_bytes、memory_pressure（平台可提供时） | 硬性内存准入与压力保护 |
| Workspace volume | volume_id、total_bytes、available_bytes、workspace_reserved_bytes | 判断实际 Workspace 所在卷是否有足够空间；不能只看系统盘 |
| 采样元数据 | runner_id（由连接身份确定，不信任 payload）、boot_id、sample_seq、observed_at、schema_version | 防止乱序/重放，识别 Runner 重启与陈旧样本 |

- CPU 使用率按 OS 统一归一化为 0–1；内存/磁盘统一使用 bytes。采样建议 10–15 秒一次，支持配置；断线重连后立即补发最新快照。
- 多磁盘机器必须上报 Workspace 实际落盘的 volume；SEM 不应要求或保存完整本机任意路径。
- 可选指标（GPU、磁盘 IOPS、网络带宽、温度）不作为 V1 必需准入条件；未来按 Harness/任务类别另行扩展。
- 资源样本有最大新鲜度；建议 45 秒。样本过期、boot_id 不匹配、序号倒退或字段无效时，该 Runner 标记为 `resource_unknown`，默认不接收新任务；已有任务不因此被终止。

### 15.2 任务资源需求模型

不能只根据“当前 CPU 低”就无限派发。每个候选任务需要资源需求画像（Resource Profile）：
- `cpu_units`：预期 CPU 份额/核心等效量；
- `memory_bytes`：预估峰值内存预算；
- `workspace_bytes`：预计新增工作区空间预算；
- `profile_class`：例如 `light` / `standard` / `heavy` / `unknown`。

资源画像来源优先级：
1. 项目/任务类型或已批准的 Harness 执行配置；
2. 同类任务的历史运行统计（样本足够后）；
3. 保守默认值。
未知画像不得按零资源处理；使用保守默认预算，或按策略只允许单任务独占 Runner。资源画像是调度提示/准入预算，不改变 Platform 对任务业务状态的权威。

### 15.3 SEM 准入算法与并发预留

SEM 对每个 Runner 维护最新资源快照，并在选择 Runner 时同时检查：
- Runner 在线、授权新鲜、监督模式/用户确认条件满足；
- CPU 使用率未超过准入上限，且剩余 CPU 预算足够；
- available memory 扣除安全保留量后，足以容纳新任务预算；
- Workspace volume 可用空间扣除安全保留量后，足以容纳新增工作区预算；
- 当前 Run 数、Harness/OS 限制和项目级并发上限未超限。

**必须有原子并发预留，不能先并发读同一份 metrics 再各自 Claim。**
1. SEM 在自己的 DB 事务中锁定该 Runner 的资源快照/调度记录，检查已有活动预留，写入该 Run+Generation 对应的 resource reservation（可先挂在 dispatch_operation 上）。
2. 只有预留成功后，SEM 才向 Platform 请求 Claim。
3. Platform Claim 失败/明确未创建 Lease：释放预留。
4. Claim 结果未知：保留预留并使用同一个 claim_request_id 对账，不能释放后另起一次 Claim。
5. Claim 成功并派发后：预留与 Run+Generation 绑定，直到 Platform 终态 + 可靠终止证据/安全处置完成才释放；WSS 断开、Runner 离线、Workspace 丢失或资源报告过期都不能释放。
6. Runner 报告的新快照反映真实当前资源使用；调度预算同时考虑任务资源画像和活动预留，避免并发 Claim 突破容量。实现时须明确“已启动任务的观测占用”与“尚未启动任务的预留”如何折算，禁止把同一任务既按完整实测占用又按完整预测预留重复扣减。

建议初始采用硬门槛 + 保守并发上限，而不是复杂的多维最优化算法。阈值通过真实 Windows Runner 压测校准；不要在没有测量依据时写死 CPU/内存/磁盘百分比。

### 15.4 资源压力与故障语义

- 资源不足只阻止新派发；V1 不自动暂停、杀死或迁移正在运行的任务。
- CPU 持续高占用可暂时降低 Runner 排名或停止新派发；内存/磁盘达到硬阈值时直接拒绝新派发。
- 资源数据是调度信号，不是进程存活证据；不能用 CPU=0、内存下降、磁盘空间变化来推断 Harness 已退出，也不能生成 E1/E2/E3。
- 资源报告中断但 WSS 仍在线：标记资源未知，停止新增派发；已有 Run 按 Lease/进程证据规则继续监督。
- Runner 离线：不再派发；已有 Run 进入既有 E1–E5 故障处置，不自动释放资源预留。
- 任务完成后只有 Platform 终态与进程终止/隔离条件满足，SEM 才释放该 Run+Generation 的资源预留。

### 15.5 持久化与协议影响

为避免无必要扩大 SEM 数据模型，建议 V1：
- 在 `runner_connection` 保存每 Runner 最新资源快照、`boot_id`、`sample_seq`、`observed_at` 和资源健康状态；历史指标可先进入外部监控系统，不要求在 SEM DB 无限存储时序数据。
- 在 `dispatch_operation` 保存资源画像摘要、准入时快照序号、预留预算、reservation 状态及释放原因；其唯一键仍以 Run+Generation/dispatch operation 为边界。
- WSS 新增 `runner.resource.report`；Platform 候选/调度 API 返回候选任务的资源画像或资源类别。Runner 只报告本机事实，不自行决定是否接收任务。
- 资源报告不需要经过 Platform PostgreSQL；资源快照与准入预留归 SEM 私有执行状态。Platform 仍只负责业务 Claim、Lease、Generation 与任务状态。

### 15.6 验收标准

1. 单 Runner 资源充足时可并发运行多个轻量任务，且不超过配置预算。
2. 内存不足或 Workspace volume 空间不足时，SEM 拒绝新增派发，不影响现有任务。
3. 两个调度请求并发到达时，资源预留事务保证不会双双使用同一份剩余预算。
4. Claim 超时/响应丢失时，预留不被提前释放；同一幂等请求恢复后只产生一个 Run+Generation 执行权。
5. Resource Report 陈旧、乱序、Runner 重启、WSS 断线时，停止新派发并正确恢复快照，不把资源状态当进程死亡证据。
6. 任务退出但缺少 E1/E2/E3 时，不释放安全屏障或资源预留。
7. CPU 高占用、内存压力、Workspace 卷空间变化在 Windows Runner 上通过长时间并发压测验证。


## 16. 用户评审清单（整套设计已提交，尚未批准）

以下是本批次提供给用户一次性评审的推荐选择。它们已形成完整设计，但不因文档提交而自动成为已批准 ADR：
1. D-01：是否采用独立 `delivery.run_execution_barrier` 表，而不是在 `task_run` 增加 barrier 列。
2. D-02：是否同意 Phase 0 创建最小正式 HIR 表，Phase 4 扩展同一表。
3. D-03/D-04：是否批准建议的 `/internal/v1` 路由前缀、JSON envelope 和消息命名。
4. D-05：是否批准七表字段/状态/唯一性基线，具体 SQL DDL 在此基线上生成。
5. D-06：是否批准按业务权威/执行事实拆分 Ports/Adapters 的边界。
6. D-07/D-08：是否批准独立 Ticket signing key、AES-256-GCM envelope encryption、24 小时 Claim response TTL（TTL 可根据重试预算修订）。
7. D-09：是否接受 V1 将已注册未撤权 Runner Supervisor 视为 E3 可信观察者，而不提供硬件证明。
8. D-10/D-11：是否批准命令双层状态映射与上述 HIR 状态推进条件。
9. D-12：实际 Harness 凭据清单需要按当前实现逐项复核；本文是目标边界，不冒充已完成代码盘点。
10. D-13 已关闭：用户确认纳入统一架构，正式登记为 ADR-SEM-26；其余 D-01–D-12 仍待确认。

本次已把 D-01–D-12 的推荐设计完整写出并同步到专题文档。用户评审通过并完成必要修订前，整体状态保持 `Design In Progress / Review Pending`，不得启动 Phase 0。


## 17. 批量评审交付说明（2026-11-25）

用户要求将剩余设计一次性整理提交，后续集中评审，不再按单个 D 项逐条等待确认。本次因此将 D-01–D-12 全部作为一个完整候选设计批次提交；不新增或伪造用户已批准的 ADR。统一评审入口为 `sem-02d-review-package.md`。D-12 的目标安全边界已定义，但真实 Harness 凭据注入/继承/日志面仍须在 Phase 0 代码改动前做只读盘点。Phase 0 仍未启动。


### D-04/D-05 与 ADR-SEM-26 的强制对齐补充

WSS V1 消息类型清单必须包含 `runner.resource.report`。七表模型中，`runner_connection` 保存当前 Runner 的资源快照（`resource_boot_id`、`resource_sample_seq`、`resource_observed_at`、`resource_snapshot`、`resource_health`）；`dispatch_operation` 保存任务资源画像、CPU/内存/Workspace 空间预留及预留状态。该设计落实 ADR-SEM-26，不新增第八张必需表。资源报告不续租、不作为 Heartbeat 或 E1/E2/E3 证据；资源未知/过期只阻止新派发。


## 18. 十项评审问题的规范性修正（2026-11-25，Review Pending）

十项问题的逐项核验和完整修正以 [`sem-02d-review-findings-corrective-design.md`](./sem-02d-review-findings-corrective-design.md) 为准。本节明确对本提案既有内容的覆盖关系：

1. **D-01 Execution Barrier**：必须区分自动安全释放与 E6 风险接受。E6 只授权一个 successor，不代表旧进程已死；旧 Barrier 保持 `risk_accepted_unconfirmed`，只有 E1/E2/E3 才释放。
2. **D-02 HIR**：Phase 0 即建立可操作的最小 HIR（创建、查询、责任人/收件人、通知、证据追加、受控处置、审计）。Phase 4 只扩展高级 handoff，不得把最初可见性/通知推迟到 Phase 4。
3. **D-03/D-04**：协议必须覆盖 Interaction terminate/continue、Runner process exit spool、自然退出、lease-loss cleanup、startup cleanup、boot transition、Detached reconnect sync。
4. **D-05/D-06**：SEM 七表模型保留；`runner_connection` 承载 boot/resource/connection 当前快照，`process_observation` 追加进程证据；Platform 增加正式 Execution Barrier/HIR/通知模型。新增统一 Execution Control Port，Runner WSS adapter 与 SEM-local CodexExecutor adapter 均需有命令消费者。
5. **D-09**：进程身份绑定 boot_id + PID + process creation identity。若 OS boot identity 可验证，boot transition 可作为 E3 子类；无法验证降级 E5。
6. **D-10**：command receipt ACK、command result、E3 process-exit evidence、continuation-consumed 四者独立。不能以 cancel ACK 代替进程退出观察。
7. **D-11**：HIR 处置必须映射 Interaction、Continuation、Cleanup Need 和 Execution Barrier；彼此关联但不合并。HIR closed 不自动解除 Barrier。
8. **D-13**：资源报告仍不续租、不证明进程退出、不释放 Barrier/预留。

### 18.1 证据分类修正

- E1/E2/E3：进程终止事实，可自动安全恢复/重派。
- E4/E5：进程可能仍在运行或证据不足，只隔离并创建/关联 HIR。
- E6：有权限操作者明确接受旧进程仍可能运行的风险授权。E6 不是终止证据，只允许一次受限 successor，旧 Barrier 不释放。

### 18.2 Dispatchability 修正

统一 Platform `is_dispatchable` 谓词必须覆盖普通 queued claim、B3-1/B3-2、B06-D3、retry/requeue、orphan reconciliation、handoff 和 E6 successor。检查 Interaction 四值 shield 与独立 Execution Barrier。B06-D3 不得把 shielded Run 回队后被普通 queued claim 重启。Detached 不加入 scheduling_shield CHECK；Phase 0 正式 Migration 必须包含 Barrier/HIR/通知收件人模型。

### 18.3 阶段修正

Phase 0 = Safety + Minimum Human Intervention；Phase 1 = SEM Control Plane + Runner E3 + Detached Recovery；Phase 2 = 独立部署 + Full Interaction Acceptance；Phase 3 = Session Continuity；Phase 4 = Advanced HIR / Cross-Runner Handoff / E6；Phase 5 = Multi-Runner Chaos Acceptance。详细验收见 corrective-design §11。

本节尚未获用户批准，不新增 Ratified ADR；Phase 0 仍未启动。
