# 后台循环清单（worker-loop-inventory）

逐条记录当前 master 上全部后台循环。判定列：DB=访问数据库；Proc=启动外部进程；
FS=依赖本地文件系统；常驻=需要常驻运行；重复=多实例是否会重复执行；归属=建议部署位置。
状态：全部为 ✅ 已实现（代码在 master，非设计稿）。

## A. `ai-pm-worker`（`apps/ai-pm-worker/src/main.rs`）

同一进程内 8 条循环（源码注释以「第 N 条循环」编号，本表沿用）。
worker_id 每次启动随机生成：`ai-pm-worker-{uuid}`。

| # | 名称 | 入口函数 | 处理对象 | DB | Proc | FS | 常驻 | 重复执行风险 | 归属 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | ai_analysis 作业 | `main` 主线程 `job_queue::claim("ai_analysis")` → `Orchestrator::handle_ai_job` | `integration.job`（lease 3600s，60ms 轮询） | 是 | 否 | 读 policy YAML（`AI_PM_POLICY_FILE`，镜像内 `/app/policies`） | 是 | 无：job 队列原子 claim + lease | **Platform** |
| 2 | repo_import 作业 | spawn 线程 `job_queue::claim("repo_import")` → `handle_repo_job` → `run_import_job` | 仓库导入分析（LLM） | 是 | 否（LLM API） | 否 | 是 | 无：同一 job 队列 | **Platform** |
| 3 | outbox 分发 | spawn 线程 `register_all_handlers` → `OutboxWorker::run` | `outbox` 表事件（TaskReady→建 queued Run；DeliverySubmitted→D5 拍①；RunCompleted→审计+通知） | 是 | handler 内可 shell `git`（KB/PC 快照分析） | 否 | 是 | 无：outbox claim 原子；**与 pm-worker 共表，注册集合必须一致（`assert_catalog_consistent` fail-fast）** | **Platform** |
| 4 | **Run 调度与执行** | spawn 线程：`reconcile_orphans`（启动一次）→ 循环 `claim_and_start` + `poll_active_runs` + `interaction_timeout_sweep` + `run_cleanup_round` + `cleanup_finished_processes` + `comm_overview` + workspace reclamation | `delivery.task_run`（queued/claimed/running）→ Codex CLI 子进程 | 是 | **是**（codex spawn、git mirror/worktree、Job Object/进程组） | **是**（`AI_PM_WORKSPACE_ROOT` 默认 `./run-workspaces`：pid 文件、logs、executor-events.jsonl、git-mirror、worktree） | 是 | claim 由 DB `FOR UPDATE SKIP LOCKED` 原子化；**但进程证据（pid 文件/children map）是宿主本地的——跨主机后孤儿判定降级** | **Server Execution Worker**（拆分见迁移册） |
| 5 | D5 review 领取拍 | spawn 线程 `run_review_loop` | review run（`executor_kind='platform'`，确定性校验管线） | 是 | 否 | 否 | 是 | review run 无独立租约，由循环内谓词防重入（§6.2） | **Platform** |
| 6 | D5 失败判定 | spawn 线程 `judge_failures_once`（60ms 轮询） | 扫描谓词强制 `run_kind='delivery'` | 是 | 否 | 否 | 是 | 谓词 + 条件 UPDATE 幂等 | **Platform** |
| 7 | assistant 会话回复 | spawn 线程 `ConversationReplyWorker::reply_round`（1s 轮询） | 对话消息 → LLM 回复；`AI_PM_CONVERSATION_REPLY` 默认 **off** | 是 | 否（LLM API） | 否 | 是（开关 on 时） | 扫描/防重入在 `pm_ai::conversation_reply` | **Platform** |
| 8 | 访谈编排（DK-B） | `spawn_discovery_orchestrator` → `orchestrate_round` + `sweep_write_back`（1s 轮询） | 访谈会话轮次 + 知识 Git 写回（草案止步 pending_confirmation）；`AI_PM_DISCOVERY_ORCHESTRATOR` 默认 **off** | 是 | `git`（KnowledgeRoot Markdown 提交） | **是**（`AI_PM_KNOWLEDGE_ROOT`，compose 已挂卷 `/data/knowledge`） | 是（开关 on 时） | 会话级状态机防重入 | **Platform** |

另有非循环常驻面：metrics HTTP（`AI_PM_WORKER_METRICS_ADDR` 默认 `127.0.0.1:9465`）。

## B. `pm-worker`（`apps/pm-worker/src/main.rs`）

| # | 名称 | 入口函数 | 处理对象 | DB | Proc | FS | 常驻 | 重复执行风险 | 归属 |
|---|---|---|---|---|---|---|---|---|---|
| 9 | outbox 分发 | `register_all_handlers` → `OutboxWorker::run`（100ms idle 轮询） | 与循环 3 **同一张 outbox 表**、同一 Handler 全集 | 是 | handler 内 `git`（KB 快照分析） | 否 | 是 | 无（原子 claim）；两 worker 装配不一致会制造假死信——目录校验启动即 panic | **Platform** |
| 10 | 文档处理作业 | `DocprocWorker::run`（表即队列，独立于 outbox） | `docproc` job：拉原始字节 → 解析；未配置 file-service 时诚实降级跳过 | 是 | 否（HTTP 拉 file-service） | 否 | 是 | job claim + lease | **Platform** |

## C. `pm-api`（`apps/pm-api/src/main.rs`）

| # | 名称 | 入口 | 处理对象 | 归属 |
|---|---|---|---|---|
| 11 | audit SSE LISTEN listener | `tokio::spawn(audit_stream::run_listener)` | PG `LISTEN` 专用连接 → 进程内 broadcast → SSE | **Platform**（必须贴着 API 进程，不可拆） |
| 12 | JWKS 刷新 / consul 注销 / setup 探测 | `init_with_refresh_loop(30s)`、consul guard、`run_startup_check` | 进程内维护 | **Platform** |

## 归属判定总则

- **Platform**：只碰 DB / LLM API / file-service / knowledge Git 卷。共 9 条（1/2/3/5/6/7/8/9/10）+ pm-api 全部。
  其中循环 3 与 9 **绑定约束**：共享 outbox 表，`register_all_handlers` 注册集合必须一致，
  任何一方的 handler 缺失都会把对方可处理事件误判为死信（T-061 §6.2.1）——
  这 8 条循环因此**不能与 outbox 消费拆到不同代码路径**，也就不能拆给执行主机。
- **Server Execution Worker**：只有循环 4，且其中仅 executor-dependent 子步需要迁移
  （详见 `migration-recommendation.md` §2 的子步拆分表）。
- **Client Runner**（`apps/ai-pm-runner`）：不在本清单展开，见 `execution-topology.md`。

## 与其他 Worker 重复执行的具体机制

- 循环 1/2：`integration.job` 的 claim 是原子 UPDATE + lease（3600s）；多实例安全。
- 循环 3/9：outbox claim 同范式；目录一致性校验保证语义一致。
- 循环 4：DB 层安全（SKIP LOCKED + lease + generation fencing）；**进程层不安全**：
  两个 `CodexExecutor` 实例各有独立 `children: Mutex<HashMap<session, ChildHandle>>`，
  跨实例 terminate 只能走 pid 文件（有 identity_hint 锚点防 PID 重用误杀，安全但间接）。
- 循环 5/6/7/8：谓词 + 条件 UPDATE + 会话状态机，多实例幂等（各实例独立扫描可接受）。
