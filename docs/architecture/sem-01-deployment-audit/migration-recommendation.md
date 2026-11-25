# 职责迁移建议（migration-recommendation）

前置：`docs/architecture/server-execution-management-architecture-v1.md` 在 master 上不存在；
本册以代码事实推导，正式实施前需按仓库惯例先 brainstorming（`todo.md` §0.1）并落盘设计文档。
本阶段只读审计，以下均为建议，未实施。

## 1. 四类职责归属

| 类别 | 内容 | 现载体 | 归属裁定 |
|---|---|---|---|
| **Platform Background Worker** | 循环 1 ai_analysis、2 repo_import、3 outbox、5 review、6 失败判定、7 会话回复、8 访谈编排；pm-worker 循环 9 outbox、10 docproc；pm-api audit listener | `ai-pm-worker`（除循环 4）、`pm-worker`、`pm-api` | 留 Platform 主机，**不迁** |
| **Server Execution Worker** | 循环 4 中 executor-dependent 子步（见 §2） | `ai-pm-worker` 循环 4 | 迁独立 Docker 主机（SEM） |
| **Session Manager** | 进程会话生命周期：spawn 登记（pid/host/session）、存活监控（四信号）、终止与清理账本、session 查询面 | 现分散于 `run_executor.rs` 编排 + `codex_executor.rs` 进程证据 | 嵌 `pm-application::session_manager`（新模块）+ 实现留 `pm-infrastructure`，**先不拆新二进制** |
| **Client Runner** | 用户 PC 上的 Agent 载体（发现/领取/监督/交付） | `apps/ai-pm-runner` | 不变（用户侧，天然分布式） |

## 2. 循环 4 的子步拆分（迁移的最小正确切面）

| 子步 | 函数 | 性质 | 归属 |
|---|---|---|---|
| 孤儿启动 reconcile | `run_executor::reconcile_orphans` | **执行**（需 executor.poll 进程证据） | SEM |
| 领取并启动 | `claim_and_start`（claim 半边是 DB，start 半边是 spawn） | **执行** | SEM |
| 活跃 Run 监控 | `poll_active_runs`（terminate/续租/收尾） | **执行** | SEM |
| 人工等待超时判定 | `interaction_timeout_sweep` | DB 条件 UPDATE，幂等 | Platform（重复执行无害；也可随迁，但留 Platform 让通信面判定贴近平台） |
| 清理账本轮 | `run_cleanup::run_cleanup_round` | **执行**（需 executor.terminate） | SEM |
| 终态僵尸兜底 | `cleanup_finished_processes` | **执行** | SEM |
| 通信面观测 | `comm_overview` 聚合日志 | 只读 DB | Platform |
| 回收候选 staging | `workspace_reclamation::stage_candidates` | 只读 DB + 写账本 | Platform |
| 回收物理执行 | `run_worktree_reclamation_round` / `run_repository_mirror_reclamation_round` | **执行**（删目录，需与工作区同卷） | SEM |

## 3. 迁移依赖与重复运行风险

### 依赖（按序）

1. **角色化装配**（硬前置）：`ai-pm-worker` 的 8 条循环 spawn 处加角色过滤
   （`AI_PM_WORKER_ROLE=platform|execution|all`，默认 all 保持现行为）。
   不做这一步就整只迁走 = Platform 侧失去 outbox 消费者（与 pm-worker 共表的
   `register_all_handlers` 集合仍会一致，但循环 1/2/5/6/7/8 全部停摆）。
2. **执行镜像**：Dockerfile 增 `runtime-ai-pm-execution` target（+ codex CLI）。
3. **工作区卷**：`AI_PM_WORKSPACE_ROOT` 显式绝对路径 + 持久卷（跨重启孤儿判定依赖，
   见 execution-topology.md §4）。
4. **网络**：DATABASE_URL 直连平台 PG；`AI_PM_MCP_URL` 指向平台 /mcp 可路由地址
   （执行端 Agent 需要调 `pm_get_run_context` 等工具）。
5. （可选，SEM 第二步）`session_manager` 模块：把 pid/host/session 关系升入 DB 面的
   查询接口——**本阶段无迁移、无表**，等真实需求。

### 重复运行风险矩阵

| 场景 | 防线 | 残余风险 |
|---|---|---|
| Platform worker 与 SEM worker 并存 | `AI_PM_RUN_DISPATCH` off/on；DB claim 原子 | 无（回收/清理两边都会跑，幂等） |
| SEM 双实例（扩容） | SKIP LOCKED + lease + generation fencing | terminate 跨实例走 pid 文件（间接但安全） |
| SEM 与 Client Runner | runner 绑定项目候选排除（D-2=c）+ scheduling_shield | `reconcile_orphans` >1h 回收**不含 runner 排除**——「平台已回收、客户端进程仍在跑」窗口存在（fencing 保证 DB 安全，算力双耗） |
| **最大风险（Q7）** | — | **B3-2 回收分支不验进程存活**（`claim.rs` ④ 段：stage='started' + 租约过期 → 直接隔离+新建，不 poll）。心跳断供（网络分区/宿主暂停）即触发；旧进程存活期间同任务双进程并行。缓解建议（SEM 内做，不改协议）：回收前先 `executor.poll` 一次，`Running`/`Uncertain` 时只续租或告警、不新建——与 `reconcile_orphans` 的保守语义对齐 |

## 4. Session Manager 的嵌入位置（Q4/Q5）

**推荐：`crates/pm-application/src/session_manager/`（新模块）+ 现有二进制承载。**

理由：

- 端口已在 `pm-application`：`RunExecutor` trait、`ExecutorSession`、`run_cleanup` 账本、
  `workspace_reclamation`——Session Manager 只是把这些收拢成「一个 Run 的进程会话生命周期」
  显式状态机（registered → spawn_pending → running → reaping → cleaned）；
- 实现已在 `pm-infrastructure::codex_executor`（pid 协议、三重证据、Job/进程组）——零新依赖；
- 承载宿主：短期就挂在 SEM worker 的循环 4 位置（同一处调用点替换），
  长期若需要独立查询面（REST「当前有哪些活进程」），从 pm-api 挂只读路由即可，
  仍不需要新二进制。
- **不推荐**把 Session Manager 塞进 `pm-mcp`（它是模型交互面）或 `pm-domain`（无 IO 层职责）。

**是否拆新二进制（Q5）**：SEM-01 最小改动 = 不拆（角色化装配即可上线独立主机）。
常态化后可选拆 `apps/ai-pm-execution-worker`（复用 `pm-application`/`pm-infrastructure`，
main.rs 只装配执行角色循环）——收益是镜像与配置面干净，成本是 Cargo workspace 一行 +
CI 一条流水线，届时再议。

## 5. SEM-01 最小改动文件清单（Q8）

| 文件 | 改动 | 性质 |
|---|---|---|
| `apps/ai-pm-worker/src/main.rs` | 8 条循环 spawn 处加 `AI_PM_WORKER_ROLE` 过滤（默认 all，行为零漂移） | 唯一业务代码改动 |
| `Dockerfile` | 增 `runtime-ai-pm-execution` target（codex CLI 层） | 构建 |
| `infrastructure/full-dev/docker-compose.execution.yml`（新增） | 执行主机服务定义 + workspace 卷 + §4 env 表 | 部署（新增文件，不动现有片） |
| `docs/architecture/server-execution-management-architecture-v1.md`（新增） | 基线设计落盘（含本审计引用与裁定） | 文档 |
| （可选）`crates/pm-application/src/session_manager.rs` | 薄封装：会话状态机 + 查询面，复用现有端口 | 代码（可延后） |

**不动**：`run_dispatch/*`、`run_executor.rs`、`codex_executor.rs`、ai-pm-runner、
数据库迁移、pm-api、pm-worker。

## 6. 明确不做（沿用审计约束）

- 不拆微服务、不引入 Redis/RabbitMQ/Kafka（队列 = PG 表，现有 outbox/job 范式已够）；
- 不新增数据库迁移（session 升 DB 面留待真实需求）；
- 不改 Worker 主循环语义（角色过滤是装配层开关，循环体不动）；
- 不讨论 Artifact Service / SeeCode。
