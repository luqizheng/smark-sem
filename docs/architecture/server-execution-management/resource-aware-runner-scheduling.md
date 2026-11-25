# Runner 资源感知与同机并发调度（ADR-SEM-26）

- 状态：**Approved Architecture Decision**
- 决策日期：2026-11-25
- 适用范围：SEM V1 Runner 选择、同机并发准入、资源预留和资源压力处理
- 关联决策：ADR-SEM-19（Platform/SEM 服务边界）、ADR-SEM-20（SEM 唯一 Runner 控制面）、ADR-SEM-21（Lease Renewal 唯一路径）、ADR-SEM-24（SEM 私有 DB）、ADR-SEM-25（跨服务幂等）

## 1. 决策

Runner Supervisor 必须通过已认证的 Runner–SEM WSS 控制连接，定期报告 Runner 所在 PC 的 CPU、内存和 Workspace 实际所在磁盘卷资源。SEM 必须将这些数据纳入 Runner 选择与同机并发任务准入决策，不能仅依据在线/忙碌状态决定派发。

SEM 是资源准入与 Runner 选择的决策者；Platform 仍是业务执行权授予者。SEM 的资源判断和资源预留不等于 Claim 成功，只有 Platform 原子 Claim 成功并签发 Lease/Generation 后才能向 Runner 派发执行授权。

## 2. 职责边界

### Runner Supervisor
- 采集本机 CPU、内存和 Workspace 所在卷的资源快照。
- 使用 WSS 发送资源报告；Runner 身份从已认证连接确定，不信任 payload 自报身份。
- 资源报告不承担 Heartbeat、Lease Renewal 或进程退出证明职责。

### SEM
- 保存每个 Runner 最新有效资源快照。
- 为候选任务计算资源需求画像，执行资源准入和 Runner 排序。
- 在 SEM DB 中原子预留资源预算，避免并发调度请求超额承诺。
- 处理样本过期、资源压力、Claim 结果不确定和预留释放。
- 不因资源压力自动终止、暂停或迁移正在运行的任务（V1）。

### Platform
- 继续权威维护 Run、Lease、Generation、Task 状态、业务审计与 Claim 事务。
- 在 Claim 时重新验证设备授权、项目绑定、业务并发限制和所有调度安全屏障。
- 不把 SEM 的资源快照作为执行权或业务状态权威。

## 3. Runner 资源报告协议

WSS 消息类型：`runner.resource.report`。

必需字段：
- `boot_id`：Runner Supervisor 每次 OS/Runner 启动周期的稳定标识。
- `sample_seq`：同一 boot_id 内严格递增的采样序号。
- `observed_at`：UTC RFC 3339 采样时间。
- `cpu.logical_cpu_count`：逻辑 CPU 数。
- `cpu.utilization_short`、`cpu.utilization_long`：0–1 归一化窗口利用率。
- `memory.total_bytes`、`memory.available_bytes`；可提供时报告 `memory.pressure`。
- `workspace_volume.volume_id`、`total_bytes`、`available_bytes`、`workspace_reserved_bytes`。

规则：
- 建议采样/发送间隔 10–15 秒；资源样本新鲜度建议 45 秒。实际阈值可配置，但必须有服务端上限并经过负载测试。
- 磁盘指标必须对应 Workspace 实际所在卷；多卷机器不能只上报系统盘。
- 只报告 volume_id 和容量，不要求上报任意本机路径。
- 乱序、重复、无效样本不得覆盖新样本；boot_id 改变表示 Runner 重启，必须重新完成活动进程清单与 SEM/Platform 对账。
- 资源样本过期或不可用时 Runner 资源状态为 `unknown`，停止新派发；已运行任务继续按原 Lease/进程证据规则监督。
- Heartbeat 只证明 Supervisor 连接/循环存活；Lease Renewal 只按 ADR-SEM-21；资源报告只表示资源快照。三者严格分离。

V1 不强制 GPU、IOPS、网络带宽、温度指标；按未来任务类型需求另立扩展。

## 4. 任务资源需求画像

每个候选任务具有 Resource Profile：
- `cpu_units`：CPU 预算，使用归一化核心等效量。
- `memory_bytes`：预估峰值内存预算。
- `workspace_bytes`：预计新增 Workspace 空间。
- `profile_class`：`light` / `standard` / `heavy` / `unknown`。

画像来源顺序：
1. 项目/任务类型或已批准 Harness 执行配置；
2. 同类任务历史观测（达到足够样本量后）；
3. 保守默认画像。

未知画像不得按零资源处理。可采用保守预算，或按策略只允许该 Runner 同时运行一个任务。历史实测值可用于修正预测，但不能取代硬性内存/磁盘安全余量。

## 5. SEM 准入算法

Runner 可接收新任务必须同时满足：
1. WSS 在线、身份有效、授权新鲜；监督模式要求已满足（默认 unattended，supervised 必须先取得用户选择）。
2. 最新资源样本未过期且 boot_id/sample_seq 有效。
3. CPU 使用率/剩余预算符合配置准入策略。
4. available memory 扣除安全保留量后足以容纳候选任务峰值预算。
5. Workspace volume available bytes 扣除安全保留量后足以容纳候选任务空间预算。
6. 当前活动任务数、OS/Harness 限制和项目级并发上限均未超限。
7. 通过下述原子资源预留。

V1 采用硬门槛 + 保守并发上限；不在没有真实压测数据时写死 CPU、内存或磁盘百分比。CPU 持续高占用可以降低 Runner 排名或暂缓新派发；内存与 Workspace 磁盘硬阈值不足时直接拒绝新派发。

## 6. 原子资源预留与 Claim 顺序

1. SEM 在本地事务中锁定 Runner 调度/资源记录，重新读取最新快照和活动预留。
2. SEM 计算可用预算，并原子创建绑定 `dispatch_operation`、Run 和 Generation 的资源预留。
3. 只有资源预留成功后，SEM 才向 Platform 发起 Claim，使用稳定 `claim_request_id`。
4. Platform 明确拒绝且确认未创建 Lease：SEM 释放该次预留。
5. Claim 超时、HTTP 504 或结果未知：SEM 保留预留，以相同 `claim_request_id` 查询/重试；禁止释放后另起 Claim。
6. Claim 成功：预留绑定到返回的 Run+Generation，随后 SEM 才能通过 WSS 派发。
7. Runner 接受/进程启动后，SEM 继续跟踪活动预留。最新实测资源快照与预测预留必须采用统一核算规则，避免同一任务被重复扣除完整预测预算和完整实测占用。
8. 只有 Platform 业务终态与可靠终止/安全处置条件满足后，SEM 才释放预留。WSS 断开、Heartbeat 丢失、资源样本过期、Workspace 丢失或 CPU=0 均不能单独释放预留。

SEM DB 最小数据承载：
- `runner_connection` 保存最新资源快照、boot_id、sample_seq、observed_at 和资源健康状态。
- `dispatch_operation` 保存 Resource Profile 摘要、准入时 sample_seq、预留预算、预留状态与释放原因。
- 不新增必需的第八张 SEM 表；如后续需要历史时序分析，使用监控系统或另立设计，不把无限增长的指标历史塞进业务协调表。

## 7. 资源压力与故障语义

- 资源不足只阻止新派发；V1 不自动杀死、暂停或迁移已有任务。
- Resource Report 丢失但 WSS 仍在线：资源状态变 unknown，停止新派发；已有任务照常监督。
- Runner 离线或授权失效：停止新派发；已有任务走 E1–E5/HIR 故障处置，预留不因离线自动释放。
- CPU、内存、磁盘数据是调度信号，不是进程 liveness 或 termination 证据，永不生成 E1/E2/E3。
- 资源预留与 D-01 execution barrier 是不同概念：前者防止同机超额承诺，后者防止进程状态不确定时自动重派。两者都不能替代 Platform Lease/Generation 权威。

## 8. 验收门槛

1. 资源充足时同一 Runner 能按预算并发承载多个任务。
2. 内存或 Workspace 卷空间不足时拒绝新任务，现有任务不被自动终止。
3. 两个并发调度请求不能重复消费同一份资源预算。
4. Claim 响应丢失时预留保持，原幂等键恢复同一结果。
5. stale/out-of-order/invalid sample、Runner 重启、WSS 断线均正确停止新派发并恢复对账。
6. 资源数据绝不被误用为 E1/E2/E3；缺少终止证据时不释放 execution barrier 或活动任务预留。
7. Windows Runner 完成长时间多任务压力测试并校准阈值；其他 OS 在各自采集语义通过验收后才启用。
8. 验证资源观测与预测预算的核算不会双重扣减或漏算。

## 9. 非目标

- 不由 Runner 自行决定是否领取任务；Runner 报告事实，SEM 调度。
- 不由资源报告续租、授予 Lease 或改变 Generation。
- V1 不自动终止、暂停或迁移运行中的任务。
- 不要求完整硬件遥测（GPU、温度、风扇等）。
- 不为资源时序指标增加新的必需 SEM 数据库表。
