# 执行拓扑（execution-topology）：Server Worker 与 Client Runner

全部结论对应 master 真实代码。状态标注：✅ 已实现 / 🟡 部分实现 / ❌ 尚未实现。

## 1. 两种执行模式共享同一 claim 管线

**✅ 已实现。** Model B（Server Worker 无人值守领取）与 Model A（执行端显式领取）共用
`crates/pm-application/src/run_dispatch/claim.rs` 的唯一事务模板 `claim_core`（A-2 裁决：
差异只用 `ClaimOptions` 参数表达，禁止复制事务体）：

- 统一锁序 `project → run → task`（FOR UPDATE；候选 Run 加 `SKIP LOCKED`）；
- I1-C 两阶段协议：无锁候选发现（阶段 A）→ 逐 Project 锁内重查领取（阶段 B）；
- 统一签发一次性 lease token（明文只返回一次，库内 sha256 hex）+ `lease_generation`
  （首次=1，重领 +1，心跳不递增）+ `deadline_at` 首次固化（重领/续租不得重置）。

| 参数 | Model B（worker） | Model A（MCP / Client Runner） |
|---|---|---|
| 入口 | `claim_once`（循环 4） | `claim_task_run_as_client`（cpk 通道 0049）/ `claim_task_run_with_policy`（MCP 四工具） |
| lease_owner | `ai-pm-worker-{uuid}` | `client:{device_id}` / `mcp:{name}:{token8}` |
| execution_mode | `spawn` | Client 通道与 `runner:` 前缀 = `spawn`；其余 = `human` |
| 受 `AI_PM_RUN_DISPATCH` 门控 | 是（A-1：显式领取恒不受限） | 否 |
| 项目过滤 | 无（全量扫描，排除 runner 绑定项目） | 必填 `project_id` + `task_id` |

## 2. 两种模式如何避免领取同一 Run

✅ 已实现，四层：

1. **DB 原子性**：候选条件 `(queued AND 到期) OR (claimed AND 租约过期)` + `SKIP LOCKED`——
   同一时刻至多一个事务能锁住同一 Run 行；
2. **runner 项目排除（D-2=c）**：worker 候选发现 SQL 带 `NOT EXISTS
   (devenv.device_project_binding b JOIN devenv.device d ON d.is_runner ...)`——
   有活跃 runner 绑定的项目对 worker 恒不可见（静态事实判定，与心跳新鲜度无关）；
   env 排除列表（`AI_PM_RUN_DISPATCH_EXCLUDE_PROJECTS`）与之并集生效；
3. **调度屏蔽（N-1 / `scheduling_shield`）**：人工等待 / 回复待投递 / 超时未处置的 Run
   拒绝重领，Interaction 生命周期不受 poll 信号干扰；
4. **fencing**：`accept_executor_result` 要求三元组 `(run_id, executor_session,
   lease_generation)` 全部匹配当前值——旧 generation 永远不能重新获得授权。

## 3. Worker 重启时的进程恢复

✅ 已实现，三条恢复链：

- **启动 reconcile**（循环 4 开头 `reconcile_orphans`，`run_executor.rs:480`）：
  - >1h 租约过期的 running Run（B06-D3）：Run 退回 `queued`（`termination_reason='lease_expired'`，
    **不终态化**）+ 任务 Running→Blocked→Ready + `run.orphan_reclaimed` 审计；
    ⚠️ 此查询**不带 runner 项目排除**——Model A 的孤儿也在此被回收（有意为之：否则无人处理；
    代价见 README 问题 7）；
  - 租约未过期的 claimed/running：逐个 `executor.poll` 一次——Done→收尾 / Uncertain→保留 /
    Running→保留（租约过期后由回收路径接管）。
- **租约过期回收**（`claim_once` 回收分支，持续运行不受 `AI_PM_RUN_DISPATCH` 关闭影响，R4）：
  - B3-1：`executor_session IS NULL` 或 `stage='dispatch'`（启动意图未确认）→ **同 Run 重领**，
    session 由下一轮覆盖（覆盖前留 `executor_session_replaced` 审计 + events 文件）；
  - B3-2：`stage='started'`（进程身份已确认）→ 隔离旧 Run（`timed_out` + failure 行
    `lease_lost`）+ 新建重试 Run（`attempt_no+1`、`supersedes_run_id` 指向旧 Run）。
- **poll_active_runs**（`run_executor.rs:260`）：只扫 `lease_owner = 本 worker_id` 的
  claimed/running Run——四信号分立判定（①固化 deadline ②Agent 心跳停滞 ③进展停滞
  ④存量 fallback）+ 存活探测 + 兜底续租（`renew_lease`：deadline 已过续租天然失败 → B3-2）。
  ⚠️ worker 重启后 worker_id 变化，旧 worker 名下的活跃 Run **不再被 poll**，
  只能等租约过期走回收或 reconcile——这是租约模型的固有行为，不是缺陷。

## 4. 工作区是否必须持久化

**✅ 是，硬依赖。** `AI_PM_WORKSPACE_ROOT`（默认 `./run-workspaces`，
`run_dispatch/port.rs:142`）下按 `{run_id}/` 组织：

| 路径 | 内容 | 持久化必要性 |
|---|---|---|
| `{run_id}/process.json` | pid 文件（原子写）：`{pid, session, identity_hint, recorded_at}` | **必须**——跨重启孤儿判定（T1 三重证据）的第一证据 |
| `{run_id}/logs/stdout.log / stderr.log` | 子进程输出（脱敏、50MiB 上限） | **必须**——`logs/` 目录存在与否是「从未 spawn vs spawn 过」的判据（pid 文件缺失时：目录在 → `Uncertain`，目录不在 → 确证不存在） |
| `{run_id}/logs/executor-events.jsonl` | 结构化执行事件（launch_profile / spawn_ok / terminated / session_replaced） | **必须**——session 替换历史唯一留痕处（库内无历史表） |
| `{run_id}/repos/<name>-<repo_id>/` | git worktree checkout | Run 生命周期内必须；reclamation 可回收 |
| `git-mirror/{repo_id}` + `.lock` | 裸镜像仓 + OS advisory lock | 可重建但强烈建议持久（首 clone 代价 + 锁语义依赖同卷） |

**当前 Docker 部署未持久化该根目录**（见 `docker-deployment-analysis.md` §3）。

## 5. 当前 Worker 对宿主进程状态的依赖

✅ 存在，且是迁移的主要阻力。执行状态一半在 DB（`delivery.task_run` 状态/租约/事件），
一半在宿主：

- **内存**：`CodexExecutor.children`（session → ChildHandle{child, pid, Job handle}）。
  只有 spawn 该子进程的实例能 `try_wait` 收割与 Job Object 整树终止；
- **文件**：pid 文件 / identity_hint（Unix `/proc/<pid>/stat` starttime 精确锚点；
  Windows StartTime.Ticks 近似）；
- **OS**：Windows Job Object（KILL_ON_JOB_CLOSE 级联）/ Unix 进程组 `kill(-pgid)`。

跨重启路径（`codex_executor.rs:998 poll`）完全走 pid 文件 + 身份锚点比对（防 PID 重用误判），
证据不足时返回 `ExecutorProgress::Uncertain`，编排器按「可能存活」保留、不得静默回收。
**含义：进程证据不可跨主机**——若 Run 在主机 X spawn、回收逻辑在主机 Y 跑，
Y 看不到 pid 文件 → 全部降级为 Uncertain/Lost，terminate 只能靠 DB 凭据撤销（token 失效）
而无法杀进程。**因此「领取→spawn→监控→终止」必须与工作区卷同主机。**

## 6. 可复用为 Session Manager 底层接口的执行能力

| 能力 | 位置 | 复用方式 |
|---|---|---|
| 生命周期端口 | `RunExecutor` trait（`port.rs:239`：kind/start/poll/terminate） | Session Manager 的进程操作面直接就是它，无需新抽象 |
| 会话身份 | `ExecutorSession { session, run_id, workspace_root }`（`port.rs:173`） | Session Manager 的最小会话句柄 |
| 启动意图协议 | T1：session 在 spawn **前**持久化（`run_executor.rs:69-125`） | 「意图 ≠ 事实」语义直接沿用 |
| pid 文件协议 | 原子写 + identity_hint 锚点（`codex_executor.rs:1165-1252`） | Session Manager 的进程注册表 |
| 四信号监控 | deadline / heartbeat / progress / lease（`run_executor.rs:260`） | Session Manager 的健康判定 |
| fencing | `renew_lease`（lease_owner 凭证）+ `accept_executor_result`（session+generation 三元组） | Session Manager 的授权面 |
| 清理账本 | `run_cleanup`（迁移 0035：无时间窗、可重试、needs_human 升级） | Session Manager 的清理语义 |
| MCP 心跳/进展刷新 | `run_context.rs`（`last_agent_heartbeat_at` / `last_progress_at`） | Session Manager 的活性输入 |

**结论：Session Manager 不是新机制，是把上述已实现能力收拢到一个有名字的组件里。**
缺口（❌ 尚未实现）只有三件：①session 生命周期状态机（当前只有列值，无创建/接管/关闭的显式状态）；
②session 历史查询面（替换历史只在 jsonl/审计里）；③Harness 原生 session ID 采集（见 session 分册）。

## 7. Client Runner（`apps/ai-pm-runner`）补充事实

- 自领循环五步：`pm_list_tasks` 发现 → `pm_claim_task`（cpk 通道）→ 工作区准备
  （git map + fetch/detach，用户会话凭据，Runner 不碰凭据）→ spawn Agent + 心跳
  `pm_report_progress` + 标记侦测 + 命令轮询 → Agent 自行 `pm_submit_result`（Runner 不代交）。
- 启动恢复 ✅：`recover_inflight_run`（发现未完结 Run → `reacquire_lease`，校验新
  generation > 旧 generation 才接管）+ `scan_orphans` / `terminate_orphan`（身份锚点
  匹配才杀，PID 重用拒杀）。
- 租约丢失处理 ✅：fail-closed 清理态（阻塞心跳/命令/新领取），重试终止或重获租约；
  升级证据落 `{workspace_root}/.aipm/cleanup-escalation-*.json`。
- 心跳节拍守卫 ✅：`heartbeat_secs * 2 < lease_secs` 否则拒绝启动（`Config::validate`）。
- Runner 本地进程会话：`runner:{pid}`（`adapter.rs:172`），仅落本地 `.aipm/process.json`，
  **不上报平台**（平台侧 executor_session 是 `mcp:{client}:{version}`，语义不同——
  见 `session-current-state.md` §5）。
