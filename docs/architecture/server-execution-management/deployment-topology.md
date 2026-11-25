# 部署拓扑（deployment-topology）

- 性质：架构设计（Phase 2 的设计依据），本阶段不修改任何 Compose/Dockerfile。

## 1. 网络与通信关系

```mermaid
flowchart LR
    subgraph HostP["Platform 主机"]
        API[pm-api HTTPS]
        PW[pm-worker]
        WP[ai-pm-worker role=platform]
        PG[(Platform PostgreSQL<br/>业务权威)]
    end
    subgraph HostE["SEM 主机（独立 Docker）"]
        WE[ai-pm-worker role=execution]
        SDB[(SEM DB<br/>执行侧私有状态)]
        CODEX[Codex CLI / 其他 Harness]
        VOL[(AI_PM_WORKSPACE_ROOT 持久卷)]
    end
    API <--> PG
    PW <--> PG
    WP <--> PG
    WP -->|Transactional Outbox / HTTPS| WE
    WE -->|claim / status / evidence API| API
    WE <--> SDB
    WE --- CODEX
    WE --- VOL
    R[用户设备 Runner] <-->|WSS| WE
```

- **Platform ↔ SEM**：版本化 HTTPS 服务 API；双方数据库独立。SEM 不连接 Platform PostgreSQL。Platform Transactional Outbox 负责可靠触发，SEM 通过 API 请求 claim、上报状态和执行证据。
- **Platform DB**：仅 Platform 服务访问，权威保存业务 Run/Lease/Generation、审批和审计。
- **SEM DB**：只保存 SEM 私有执行侧状态（命令收件/投递账本、连接元数据和恢复协调记录），不得成为 Run/Lease 的第二权威。
- **Runner ↔ SEM**：认证 WSS 双向长连接；Runner 主动连接 SEM，传输命令、ACK、Heartbeat 和执行事件。
- **API / MCP**：业务 API/MCP 留在 Platform；SEM 暴露受服务身份保护的内部 HTTPS API 和 Runner WSS 端点。

## 2. 数据库

- Platform 数据库：`delivery.task_run` 等表是业务 Run/Lease/Generation 的权威仲裁点，只由 Platform 服务访问。
- SEM 数据库：保存 SEM 执行侧私有数据；SEM 对 Run 状态的变更必须调用 Platform API，由 Platform 内部完成事务与审计。
- 不做跨数据库事务；采用 Outbox/Inbox、幂等请求、重试和对账。
- Greenfield：SEM 主机部署使用独立 SEM 数据库；但全新库必须可完整初始化（政策 §3）——现有迁移链即初始化路径，本设计不新增表以外的硬依赖。

## 3. Workspace 卷结构（`AI_PM_WORKSPACE_ROOT`）

```
$AI_PM_WORKSPACE_ROOT/
├── workspaces/<run_id>/          # 每个 Run 一个工作区（worktree）
│   ├── .git 等 worktree 内容
│   ├── run.pid                   # 进程 pid 文件（现有协议）
│   └── logs/…                    # 执行端 stdout/stderr
├── executor-events/<run_id>.jsonl # 执行事件追加账本（现有 append_executor_event）
├── git-mirror/…                  # 裸镜像仓（可重建但建议持久）
└── cleanup-ledger/…              # workspace reclamation 账本
```

- **运行期持久**：整个根目录挂载一个持久卷，供同一 SEM 主机上的进程监督、PID 文件、日志和事件账本在容器重启后继续可见。持久卷不等于备份；本项目明确不备份 Workspace、Worktree 或 Git Mirror。
- **权限**：容器内专用 UID 运行，卷目录 owner 对齐；不使用 root。
- **磁盘清理**：workspace reclamation 现有三重开关（ENABLED + SHARED_ROOT + 绝对路径校验，`main.rs:143-220`）语义保留；Phase 0 新增「清理前 `confirm_termination`」前置（见 `execution-safety.md` §5）。
- **卷丢失策略**：卷丢失意味着本地 PID/children 关联和执行现场不可用，但**不证明进程已终止**。数据库中所有无法取得 E1/E2 的活跃 Run 进入 E4/E5 隔离并创建/关联 HIR；禁止自动重派。Workspace、Worktree、Git Mirror 不做备份或快照；Git Mirror 可从该 Repository 唯一权威 `origin` 重建。
- **git-mirror**：在同一根下（现状 `workspace_root` 布局），作为运行期缓存可持久存在；丢失后从唯一权威 `origin` 重建，不做备份。每个 Repository 仅有一个权威 `origin`，SEM 不负责远端同步。

## 4. PID 与进程证据

- pid 文件、children map、Job Object 是**宿主机事实**，与 workspace 卷同主机——这是「进程监督与工作区必须同主机」的结构性约束（SEM-01 结论 10），本拓扑遵守。
- 终止确认证据（`execution-safety.md` §2 E1/E2）落 DB（`run_events` / 审计），使证据在 worker 重启后仍可读——**证据落库，事实留主机**。

## 5. 日志聚合

- 容器 stdout 走 Docker 日志驱动；执行端文件日志在卷内按 run_id 组织，可被 Loki promtail 之类按 label 采集（SEM-01 已确认 label 就绪）。
- 审计/事件以 DB 为权威，日志聚合只是运维面，不承担一致性职责。

## 6. Secret 注入

| Secret | 注入方式 | 不落盘要求 |
|---|---|---|
| `DATABASE_URL` | compose env / secret | 不写进卷、不进日志（现有脱敏保留） |
| lease token 明文 | claim 响应 → env 注入执行端（现有 L2 协议） | 库内只有 sha256 hash（现状） |
| git SSH key | RAII 临时文件（现有 codex_executor 协议） | 用后即删，不进卷持久目录 |
| LLM API key | Platform 侧 env | SEM 不需要 LLM 凭据（循环 4 不调 LLM） |

- 卷内容（pid/日志/事件）**禁止**包含凭据明文；执行端 env 由 spawn 时注入，进程退出即消失。

## 7. 网络 API、认证与可用性

- Platform 到 SEM：HTTPS，内部服务身份认证；API 版本化、幂等、限流并记录 request_id/event_id。
- Runner 到 SEM：WSS，Runner 主动建立连接；断线重连后必须先同步当前命令/Generation，不得盲目重放旧命令。
- SEM 不可达时，Platform Outbox 保留未成功投递事件并重试；SEM 恢复后通过 API 对账。SEM 不可达不影响 Platform 业务服务。
- SEM 无法访问 Platform API 时，不得自行签发 Lease 或改变权威 Run 状态；在途执行按执行安全模型处理。

## 8. 启动 / 关闭顺序与健康检查

**启动**：PostgreSQL → Platform（api/worker）→ SEM（execution worker）。
- SEM 健康检查 = 进程存活 + DB 连通 + `AI_PM_WORKSPACE_ROOT` 可写 + 执行器（codex CLI）存在。任一失败 → 容器不 ready，不领 Run（领取门控天然停摆，在途 Run 由证据模型保护，不会被误回收——`execution-safety.md` 的 E4/E5 挂起语义保证 SEM 宕机是**安全的**）。
- Platform 不依赖 SEM 在线：SEM 宕机只表现为「无服务端执行」，Platform 其余循环照常。

**关闭**：SEM 先于 Platform 收到 SIGTERM → 停止领取新 Run → 给在途进程 terminate 宽限（现有 run_cleanup_round 语义）→ 证据落库 → 退出。强制超时后 kube/compose 层 kill（Job Object/进程组终止在容器内完成，不跨主机）。

**故障恢复**：
- SEM 容器重启：启动时 `reconcile_orphans`（现状）+ 终止确认证据模型 → 在途 Run 按 E1/E2 回收、E4/E5 挂起。
- DB 不可达：worker 轮询报错退避（现状），无新行为。
- Platform 宕机：SEM 继续按租约语义收尾在途 Run（写 DB 失败则退避重试），不产生孤儿——租约与证据都在 DB，恢复后语义自洽。

## 9. Greenfield 部署基线

- Phase 2 的 compose 变更允许**直接改写**现有 `docker-compose.ai-pm.yml` / 新增独立执行主机 compose 文件，不需要保留旧部署形态的兼容开关——但默认 `AI_PM_WORKER_ROLE=all` 的单机形态必须继续可用（开发态零漂移是工程惯例，不是兼容包袱）。
- 全新环境初始化 = 起库跑迁移 → 起 Platform → 起 SEM，无手工步骤（政策 §3「Complete initialization from an empty database」）。
