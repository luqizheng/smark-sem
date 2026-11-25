# Docker 部署分析（docker-deployment-analysis）

只读分析，本阶段未修改任何配置。状态：现状 = 🟡 部分实现；独立主机方案 = 📄 仅有设计（本文提出）。

## 1. 现状：镜像（根 `Dockerfile`）

单构建阶段，按 `--target` 出四个镜像：

| target | 内容 | 与执行相关的事实 |
|---|---|---|
| `runtime-pm-api` | pm-api + git + openssh-client | 知识 Git 写入、deploy key |
| `runtime-pm-worker` | pm-worker + git + openssh-client | KB 快照分析 shell 出 git |
| `runtime-ai-pm-worker` | ai-pm-worker + git + openssh-client + `policies/` | ⚠️ **不含 codex CLI、不含 docker CLI**；`AI_PM_RUN_EXECUTOR=codex` 时 spawn 会直接失败（`spawn codex failed`）→ 走基础设施退避 |
| `runtime-web` | nginx + vite dist | — |

构建上下文 = 仓库根（sqlx migrate! 编译期嵌入）；私有依赖走 kellnr（192.168.2.12:16444）。
运行时基镜像 Debian trixie（GLIBC 2.41，必须与构建镜像同大版本）。

## 2. 现状：Compose（`infrastructure/full-dev/`）

- `docker-compose.ai-pm.yml`（ai-pm 自有服务片，include 进主 compose；YAML anchor 不能跨
  include 文件）：
  - **pm-api**：8090 宿主端口、consul 环境面、JWKS（token-service:8082）、file-service、
    `AI_PM_SECRET_KEY`、首管理员对、`AI_PM_MCP_ALLOWED_HOSTS`（T-081 /mcp 跨机白名单）、
    setup marker 落 `/app/data/setup-admin.marker`（⚠️ `/app/data` **无卷**——重启重新探测）。
  - **pm-worker**：仅 DATABASE_URL + 两个开关 + SECRET_KEY。
  - **ai-pm-worker**：DATABASE_URL、`AI_PM_SECRET_KEY`（缺它所有 git 克隆失败）、
    `AI_PM_POLICY_FILE=/app/policies/ai-pm-ai-lead-v2.yaml`、
    `AI_PM_RUN_DISPATCH`（默认 **off**）、EXCLUDE_PROJECTS、DISCOVERY_ORCHESTRATOR（off）、
    CONVERSATION_REPLY（off）、`AI_PM_KNOWLEDGE_ROOT=/data/knowledge`（卷
    `aipm_knowledge` ✅ 已持久化）。
    ⚠️ **未设置 `AI_PM_WORKSPACE_ROOT`** → 默认 `./run-workspaces` = 容器内 `/app/run-workspaces`
    （WORKDIR /app）→ **容器文件系统，重建即丢，无命名卷**。
    ⚠️ metrics `127.0.0.1:9465` 未暴露端口且绑回环。
  - **ai-frontend-web**：8092 → nginx。
- 生产差异片 `docker-compose-services.prod.yml`：仅清空宿主端口（唯一入口 api-gateway:3000，
  rustfs 9000 例外）+ restart 策略。**无独立执行主机拓扑**。
- 网络：`superpowers` 外部网络（与 lmms 栈同网络）——**单机 compose 网络，跨主机不可复用**，
  独立执行主机必须改用 DATABASE_URL 直连 IP（本机 Docker 场景按 AGENTS.md #3 用 127.0.0.1）。
- PG：ai-pm 与 lmms 共享 infra 片 postgres（2026-11-10 裁决），三服务共用 `${DATABASE_URL}`。

## 3. 缺口清单（能否承载真实执行）

| # | 缺口 | 后果 | 严重度 |
|---|---|---|---|
| 1 | 镜像无 codex CLI | `AI_PM_RUN_EXECUTOR=codex` 时所有 spawn 失败 → 基础设施退避 → Run 最终 failed | 🔴 |
| 2 | `AI_PM_WORKSPACE_ROOT` 无卷 | pid 文件 / 日志 / executor-events.jsonl / worktree / git-mirror 全部随容器生命周期——worker 重启后孤儿判定降级 Uncertain/Lost，session 替换历史丢失 | 🔴 |
| 3 | `AI_PM_RUN_DISPATCH` 默认 off | 当前容器内 worker 实际不领取 Run（循环 4 只做回收/清理），生产执行默认发生在哪里？——**没有第二台执行 worker**，即现状 = 无无人值守执行 | 🟡（设计如此，待 SEM 补位） |
| 4 | git-mirror 随容器 FS | 每次重建重新首 clone；`reclaim_repository_mirror` 的体积收益归零 | 🟡 |
| 5 | Loki label 已挂（`logging: loki`）但子进程日志在工作区 FS | 容器丢失 = 执行证据丢失，审计链断裂（审计 DB 有操作记录，无 stdout） | 🟡 |
| 6 | 无执行主机专属 secret 通道 | deploy key 解密密钥 `AI_PM_SECRET_KEY` 与平台三服务同值——独立主机需要最小权限分发 | 🟡 |

## 4. 环境变量 / Secret / 数据库连接盘点（执行主机视角）

`ai-pm-worker` 循环 4 的执行半边实际消费的 env（全部读 env，无硬编码，符合工程偏好）：

| env | 默认 | 作用 | 独立主机建议 |
|---|---|---|---|
| `DATABASE_URL` | 必填 | 唯一状态源（claim/lease/事件/审计全在 PG） | 直连平台 PG（内网可达即可，无需同 compose 网络） |
| `AI_PM_RUN_EXECUTOR` | 缺省 noop | `codex`/`mock` → CodexExecutor | `codex` |
| `AI_PM_WORKSPACE_ROOT` | `./run-workspaces` | 工作区根 | **显式绝对路径 + 命名卷/主机卷** |
| `AI_PM_RUN_DISPATCH` | off | 领取开关（只管新领取，回收不受控） | execution 主机 `on`；Platform 主机保持 `off` |
| `AI_PM_RUN_LEASE_SECS` / `AI_PM_RUN_HEARTBEAT_SECS` 等 | 300/60 | 租约与心跳 | 与 Client Runner 侧镜像值保持一致（runner `Config` 校验 heartbeat*2 < lease） |
| `AI_PM_SECRET_KEY` | 空 | deploy key 信封解密（缺 → 克隆失败） | 必须下发（与平台同值） |
| `AI_PM_MCP_URL` | 空 | 注入执行端 mcp.json（pm_get_run_context 等工具面） | 指向平台 /mcp 的可路由地址 |
| `AI_PM_CODEX_BIN` / `AI_PM_CODEX_ARGS` / `APPROVAL_POLICY` / `SANDBOX_POLICY` | codex/never/workspace-write | spawn 参数 | 镜像层装 codex CLI |
| `AI_PM_RUN_LOG_MAX_BYTES` / `AI_PM_RUN_KILL_GRACE_SECS` | 50MiB/30s | 日志上限 / 优雅终止 | 可默认 |
| `AI_PM_WORKSPACE_RECLAMATION_*` | off/off | 物理删除三重确认（requested + shared_root + 绝对路径） | 卷明确后可开 |

Secret 注入链路：`AI_PM_SECRET_KEY`（env）→ 解密 deploy key → RAII 临时 key 文件
（0700/0600，drop 即删）→ `GIT_SSH_COMMAND`；lease token 仅经子进程 env 注入，
pid 文件/日志/事件三处均不落明文，日志管道实时脱敏（token → `[REDACTED]`）。✅ 已实现。

## 5. 日志与进程证据持久化现状

| 证据 | 位置 | 现状 |
|---|---|---|
| 结构化业务事件 | DB：`delivery.run_event`（S05 0013）、`governance.audit_log` | ✅ 持久 |
| 执行事件流 | `{workspace}/{run_id}/logs/executor-events.jsonl` | 🟡 无卷 |
| 子进程 stdout/stderr | 同目录 `*.log`（脱敏 + 50MiB cap） | 🟡 无卷 |
| pid / 身份锚点 | `{workspace}/{run_id}/process.json` | 🟡 无卷 |
| 服务日志 | Loki label（`logging: loki, env: staging, service: ai-pm-worker`） | ✅（tracing → stdout → loki） |

## 6. 独立 Docker 执行主机方案（仅设计，不实施）

**目标拓扑**：Platform 主机（pm-api + pm-worker + ai-pm-worker（裁剪后）+ ai-frontend + lmms 全栈 + PG）
+ Execution 主机（纯执行 worker + 工作区卷）。

1. **镜像**：新增 target `runtime-ai-pm-execution`——基于 `runtime-ai-pm-worker`，
   增装 codex CLI（安装层独立，平台镜像不加）。
2. **服务定义**：新增独立 compose 片（如 `docker-compose.execution.yml`，不 include 进
   现有单机栈）：单服务 `ai-pm-execution-worker`，`network` 不 join `superpowers`，
   `DATABASE_URL` 直连平台 PG 内网地址；环境同 §4 表。
3. **卷**：`execution_workspace`（挂 `AI_PM_WORKSPACE_ROOT`，绝对路径）——
   pid/日志/worktree/git-mirror 全在此根下，一个卷覆盖 §3 缺口 2/4/5。
   （代码把 git-mirror 放在 workspace root 下的 `git-mirror/`，无需第二个卷。）
4. **重复执行防线**：Platform 侧 `AI_PM_RUN_DISPATCH=off` + Execution 侧 `on`
   ——DB claim 原子性保证单实例语义；若跑双实例（同主机扩容），SKIP LOCKED 仍安全，
   但进程证据共享同一卷时 `children` map 仍各自独立（terminate 走 pid 文件，安全但间接）。
5. **Runner 项目隔离已内建**：绑定 runner 的项目对 worker 候选恒排除（D-2=c），
   独立执行主机不抢 Client Runner 的活。
6. **迁移顺序约束**：必须先给 `ai-pm-worker` 加角色装配（见 migration-recommendation.md），
   否则整只迁走会把 outbox 统一装配约束打破（假死信风险）。
