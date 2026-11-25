# SEM-01 — Server Execution Management 部署边界审计（总览）

- 日期：2026-11-24
- 审计对象：`luqizheng/ai-pm` master（commit `4f047f12`，2026-11-24 pull）
- 性质：**只读审计**，未修改任何业务代码 / 迁移 / Compose / Worker 主循环。
- 架构基线：`docs/architecture/server-execution-management-architecture-v1.md`
  **⚠️ 该文件在当前 master 上不存在**（全仓 grep `server-execution-management` 无命中）。
  本审计以代码事实为锚，基线文档属「**仅有设计（未落盘）**」状态；落盘前本目录是唯一事实源。

## 一句话结论

当前仓库只有**一个**执行型二进制（`ai-pm-worker`），它把 8 条职责迥异的后台循环塞在同一进程里；
其中只有**第四条循环（Run 调度与进程执行）**属于 Server Execution Management 域。
直接把整只 `ai-pm-worker` 迁去独立 Docker 主机是**错误的拆分粒度**：能迁的是「循环 4 的执行半边」，
其余 7 条循环是 Platform 职责（共享 outbox 表的统一 Handler 装配约束使它们不可拆走）。
Session Manager 不需要新表、不需要新消息中间件：现有 `RunExecutor` 端口 + `ExecutorSession` +
pid 文件协议 + 四信号监控已经是它的底层接口，最小改动是**角色化装配**而非新二进制。

## 状态总表（实现程度标注）

| 域 | 结论 | 状态 |
|---|---|---|
| Worker 后台循环 | 8 条循环全部真实存在于 `apps/ai-pm-worker/src/main.rs`，逐条见 `worker-loop-inventory.md` | ✅ 已实现 |
| Run Execution 拓扑 | Model A/B 共享同一 `claim_core` 事务模板 + lease token/generation fencing；详见 `execution-topology.md` | ✅ 已实现 |
| Executor Session | `delivery.task_run.executor_session` 列 + pid 文件 + 内存 children map；无独立表、无历史表 | 🟡 部分实现（单列承载，无生命周期管理） |
| Harness 原生 Session ID | codex CLI 自身 session/rollout ID 全仓未采集 | ❌ 尚未实现 |
| Session Manager | 作为独立组件不存在；其底层接口（RunExecutor trait、四信号、cleanup 账本）已实现 | 🟡 仅接口已实现，组件未实现 |
| Runner 启动恢复 | `recover_inflight_run` + 孤儿扫描 + 身份锚点终止，client 侧 | ✅ 已实现 |
| Docker 部署 | 三 target 单 Dockerfile；`ai-pm-worker` 镜像**无 codex CLI**、**无工作区持久卷**、未设 `AI_PM_WORKSPACE_ROOT` | 🟡 部分实现（能跑 noop/off，不能承载真实执行） |
| 独立执行主机方案 | 仅本报告提出，无任何配置落地 | 🟡 仅有设计（本报告） |

## 八个最终问题的答案（详证在各分册）

1. **能否直接把当前 `ai-pm-worker` 部署到独立 Docker 服务器？**
   不能原样迁移（见 `docker-deployment-analysis.md` §3）：镜像缺 codex CLI、无工作区持久卷、
   且整只迁移会把 7 条 Platform 循环错搬到执行主机（共享 outbox 装配约束会被打破）。
   正确做法是**角色化拆分循环 4**后再迁移（见 `migration-recommendation.md`）。
2. **哪些循环必须留在 Platform？** 循环 1/2/3/5/6/7/8 + `pm-worker` 全部 + pm-api 的
   audit LISTEN listener。判据：只访问 DB / LLM API / knowledge Git 卷，不 spawn 执行进程。
3. **哪些应迁到 SEM？** 循环 4 中 executor-dependent 的五个子步：
   `claim_and_start`（spawn 半边）、`poll_active_runs`、`run_cleanup_round`、
   `cleanup_finished_processes`、workspace reclamation 物理执行。
   DB-only 子步（`interaction_timeout_sweep`、`comm_overview`、`stage_candidates`）留 Platform。
4. **Session Manager 放哪？** `crates/pm-application` 新增 `session_manager` 模块
   （端口 `RunExecutor`/`ExecutorSession`/`run_cleanup` 账本都在这个 crate），
   实现继续落在 `pm-infrastructure::codex_executor`。**不拆新二进制**（最小改动路径）。
5. **是否需要拆新二进制？** SEM-01 最小改动：不需要（`ai-pm-worker` 加角色开关）。
   独立主机常态化后：建议派生 `apps/ai-pm-execution-worker`（复用两个 crate，零新依赖）。
6. **独立服务器需要哪些持久卷？** ① `AI_PM_WORKSPACE_ROOT`（pid 文件 / 日志 /
   executor-events.jsonl / worktree——跨重启孤儿判定**依赖它**）；② git-mirror（在同一根下，
   可重建但强烈建议持久）；③ 日志聚合面（Loki label 已就绪）。镜像内不落任何凭据
   （lease token 走 env 注入，SSH key 走 RAII 临时文件）。
7. **最大的双重执行风险？** **B3-2 回收分支不验进程存活**：`claim_once` 对
   `stage='started'` 且租约过期的 Run 直接隔离 + 新建重试 Run，全程不做 liveness poll
   （`run_dispatch/claim.rs` ④ 段）。原执行端进程若仍存活（Runner 网络分区、Worker 宿主
   GC 暂停），同一任务两个进程并行执行；DB 被 `lease_generation` fencing 保护
   （旧结果被 `accept_executor_result` 拒绝），但算力与远端 git 副作用是双倍的。
   次级风险：`reconcile_orphans` 的 >1h 孤儿确认回收**不带 runner 项目排除**，
   会回收 Model A 客户端仍在执行的 Run（有意为之，但存在「平台已回收、客户端进程仍在跑」窗口）。
8. **SEM-01 最小改动涉及哪些文件？** `apps/ai-pm-worker/src/main.rs`（循环装配加角色过滤）、
   `Dockerfile`（新增含 codex CLI 的 execution target）、`infrastructure/full-dev/` 新 compose 片
   （独立执行主机服务 + 工作区卷）、`crates/pm-application/src/session_manager.rs`（新增，薄层）。
   不动：`run_dispatch/*`、`codex_executor.rs`、数据库迁移、ai-pm-runner。

## 分册目录

- `worker-loop-inventory.md` — 12 条后台循环逐条清单（入口 / DB / 进程 / FS / 常驻 / 重复执行 / 归属）
- `execution-topology.md` — Model A / Model B 执行拓扑、claim/lease 共享、重启恢复
- `session-current-state.md` — 六个 Session 概念辨析与当前实现
- `docker-deployment-analysis.md` — 镜像 / Compose / 卷 / secret / 日志与独立主机方案
- `migration-recommendation.md` — 四类职责归属 + 迁移依赖 + 风险 + 最小改动文件清单

## 审计方法

全部结论对应当前 master 真实代码，关键锚点（均可复核）：

- `apps/ai-pm-worker/src/main.rs`（680 行，8 条循环注释编号第一~第八）
- `apps/pm-worker/src/main.rs`（70 行）
- `crates/pm-application/src/run_dispatch/{mod,claim,lease,port}.rs`
- `crates/pm-application/src/run_executor.rs`（1306 行）
- `crates/pm-application/src/run_context.rs`（executor_session 的 MCP 写入点 873–888）
- `crates/pm-infrastructure/src/codex_executor.rs`（1741 行，进程/工作区唯一落点）
- `apps/ai-pm-runner/src/{runner_loop,adapter,workspace}.rs`
- `Dockerfile`、`infrastructure/full-dev/docker-compose.ai-pm.yml`、`docker-compose-services.prod.yml`
