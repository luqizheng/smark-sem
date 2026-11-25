# Session 当前实现审计（session-current-state）

状态标注贯穿全文：✅ 已实现 / 🟡 部分实现 / 📄 仅有设计 / ❌ 尚未实现。
全部路径对应当前 master。

## 1. 六个概念严格区分

当前代码与文档中至少存在六个「session」近义概念，**不得混用**：

| # | 概念 | 载体 | 生命周期 | 状态 |
|---|---|---|---|---|
| 1 | **Run** | `delivery.task_run` 行（`run_kind='delivery'/'review'`，`uq_task_run_active` 保证每任务至多一条活跃 delivery） | queued → claimed → running → 终态（succeeded/failed/timed_out/cancelled）；B3-2 失联可派生新 Run（`supersedes_run_id` 链） | ✅ |
| 2 | **Execution / Attempt** | 同一 Run 的 `attempt_no` 递增 + 重领 `lease_generation` 递增；attempt 间无独立表，靠 `attempt_no`/`supersedes_run_id`/`lease_generation` 三列表达 | 随 Run / 随租约 | ✅ |
| 3 | **Executor Session（平台）** | `delivery.task_run.executor_session` 列（`TEXT`，无独立表） | 从「启动意图落库」到进程收尾；替换时旧值只留 events 文件 + 审计 | 🟡 |
| 4 | **Harness 原生 Session** | codex CLI 自身的 session/rollout ID | **未采集**——`CodexLaunchProfile` 只传 env（`AI_PM_EXECUTOR_SESSION` 是平台 session，不是 harness session），日志不解析 | ❌ |
| 5 | **Runner Process Session** | runner 本地：`session_id = "runner:{pid}"`（`adapter.rs:172`），落 `{workspace_root}/{run_id}/.aipm/process.json` | runner 进程本地，**不上报平台** | ✅（仅本地） |
| 6 | **审计 / Agent 身份**（防混淆提示） | `lease_owner` / `client_name` / `claimed_device_id` | 归因用，非凭证、非会话 | ✅ |

易混点澄清：

- 客户端 claim 后、首报 started 前，`executor_session` 为 NULL——此时 Run 已被领取但
  **平台侧没有 session**；B3-1 判定正是利用这一点做「同 Run 重领」。
- worker 路径与 MCP 路径写 `executor_session` 的**格式和时机都不同**（见 §3），
  同一列承载两种语义。
- `executor_session` 不是凭证；凭证是 lease token（sha256 入库，明文一次性下发）。

## 2. Executor Session 的写入点（全仓仅两处写）

✅ 已实现：

1. **Model B（worker spawn 路径）**：`run_executor.rs:69-125` `claim_and_start`。
   编排器预生成 `format!("{executor_kind}:{uuid}")`（如 `codex:…`），在 spawn **之前**
   条件 UPDATE（`WHERE status='claimed' AND stage='dispatch'`）持久化——T1 裁决：
   session 是**启动意图**，不等于进程已启动。spawn 成功后同事务把
   `status→running, stage→started`（带 session 匹配防竞态 + 先锁 Project 行防归档窗口）。
2. **Model A（MCP 首报路径）**：`run_context.rs:873-888` `report_progress` 首报
   `stage='started'` 时写 `executor_kind='mcp'` + `executor_session="mcp:{client}:{version}"`
   ——即 **MCP 路径的 session 是客户端自报标识**（client_name+version），
   不是进程身份，也无法用于定位进程。

读取/fencing 点：`accept_executor_result`（三元组比对）、`poll_active_runs`（只扫
session 非空且 `lease_owner=本worker`）、`claim_once` B3-1/B3-2 分叉、四条 cleanup/
reconcile 查询。

## 3. Session 持久化与恢复

| 层 | 机制 | 状态 |
|---|---|---|
| DB | `delivery.task_run.executor_session`（当前值快照，无历史） | ✅ |
| 进程内存 | `CodexExecutor.children: Mutex<HashMap<session, ChildHandle>>`（child + pid + Windows Job 句柄）——**仅本进程 spawn 的 session 可直接收割** | ✅ |
| 文件 | `{AI_PM_WORKSPACE_ROOT}/{run_id}/process.json`：`{pid, session, identity_hint, recorded_at}`，原子写（tmp + rename，Windows 先删后 rename 的窗口由「tmp 已就绪」缩小）；token 明文绝不入盘 | ✅ |
| 跨重启恢复 | `poll` 走三重证据：pid 文件身份锚点比对（Unix `/proc/<pid>/stat` starttime 精确 / Windows StartTime 近似）→ 活 → `Running`；死/PID 重用 → `Done{Lost}`；pid 文件缺失但 `logs/` 在 → **`Uncertain`（不得静默回收）**；目录都没有 → 确证从未 spawn | ✅ |
| Session 替换留痕 | 旧 session 被覆盖前：`executor-events.jsonl` 记 `session_replaced` + 审计 `executor_session_replaced`（**库内无历史表**，文件是唯一历史） | 🟡（留痕在 FS，容器重建即丢） |
| Runner 侧恢复 | `recover_inflight_run`（重获租约需 generation fencing）+ `scan_orphans`/`terminate_orphan`（身份锚点匹配才杀） | ✅ |

## 4. Session 与 PID 的关联

✅ 已实现，两条独立链（worker 与 runner 各一套，结构同构但互不相通）：

- worker：`process.json` 在 `{AI_PM_WORKSPACE_ROOT}/{run_id}/process.json`
  （`codex_executor.rs:128`），由 `claim_and_start` spawn 成功后写入；
  孤儿 terminate 按 pid + identity_hint 匹配后 `kill_by_pid`（含进程组/Job 整树）。
- runner：`.aipm/process.json`（`adapter.rs:228` `write_process_record`）；
  `terminate_orphan` 按平台前缀校验锚点格式（`win-ft-` / `proc-start-` / `ps-start-`），
  不匹配拒绝终止。

🟡 缺口：pid 关联只活在工作区文件里，平台 DB 不知道任何 pid；跨主机场景（本审计的
迁移目标）pid 证据失效是**结构性限制**（见 execution-topology.md §5）。

## 5. Harness 原生 Session ID 的使用

❌ 尚未实现。证据：

- `CodexLaunchProfile`（`codex_executor.rs:715-824`）注入的 env 只有平台侧
  `AI_PM_EXECUTOR_SESSION` / `AI_PM_LEASE_TOKEN` / `AI_PM_LEASE_GENERATION` 等；
- 全仓 grep `rollout` / `harness`（排除无关命中）无 session 采集代码；
- 子进程 stdout/stderr 只脱敏落盘不解析，codex CLI 的会话文件（若产生）落在
  codex 自己的 home 目录，平台不感知。

含义：**进程死后无法恢复/续聊 codex 会话**，重试 Run 每次都是全新 harness 会话
（prompt 由 instruction.md + MCP 拉契约重建）。SEM 若要求「跨 Attempt 续会话」，
harness session 采集是前置缺口。

## 6. 结论与 SEM 的关系

- 已实现的部分（session 列、pid 协议、fencing、Uncertain 语义）质量高、语义自洽，
  Session Manager 应当**原样继承**这些协议，而不是重新发明；
- 真正的缺口按优先级：
  1. 🟡 session 历史不可查询（FS 留痕）→ 若 SEM 需要「谁的进程在哪个主机」的面，
     需要把 pid/host/session 关系升入 DB（**本阶段不做迁移**，仅记录）；
  2. ❌ harness session 未采集 → 阻塞「续会话」类需求，不阻塞部署边界迁移；
  3. 🟡 MCP 路径 session（`mcp:{client}:{version}`）与进程无关联 → 该路径本就是
     「Agent 自执行」，无进程可管，语义成立；但与 runner spawn 路径（也写
     `execution_mode='spawn'`）共用一列时，靠 `executor_kind` 区分（`codex:*` vs
     `mcp:*`）——SEM 落地时若引入第三种执行器，需要先扩展 executor_kind 枚举。
