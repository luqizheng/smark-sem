# SEM V1 Operational Runbook

Status: target runbook. Deployment-specific commands and thresholds are validated in Phase 2.

Workspace, Worktree and Git Mirror are not backup targets. No Workspace RPO/RTO or snapshot restore procedure is defined.

## 1. Startup

1. Verify Platform API health and Platform database/schema health through Platform health endpoints/operations.
2. Verify SEM-owned database availability and schema version.
3. Verify SEM service identity, TLS trust and least-privilege credentials; confirm no Platform DB credentials are mounted.
3. Verify AI_PM_WORKSPACE_ROOT is mounted, writable by non-root service UID and has sufficient free space.
4. Verify selected Harness CLI exists and its version is approved.
5. Start SEM with execution role only; confirm Platform remains the sole outbox consumer.
6. Confirm readiness before allowing claims.

## 2. Shutdown

1. Stop accepting new claims.
2. Observe/terminate owned processes within bounded grace.
3. Persist termination evidence and audit outcomes.
4. Any process not confirmed terminated remains E4/E5 shielded.
5. Stop SEM only after safe containment decisions are persisted.

## 3. Monitoring

Monitor active Run count by stage/generation; expired leases awaiting evidence; E4/E5 shield count and age; HIR count/age; E1/E2/E3 outcomes; Runner heartbeat age and stale-generation rejection; process poll uncertainty; workspace disk usage; credential issuance/revocation failures; and outbox role configuration.

Alert on requeue attempts for shielded Runs, SEM attempting Platform DB access or registering Platform outbox handlers, Platform process spawning, Platform API/SEM DB connectivity failure, workspace permission failure, disk exhaustion or secret leakage.

## 4. Suspected duplicate execution

1. Freeze new claims for affected scope.
2. Identify Run rows, generations, lease owners and process identities.
3. Do not delete workspaces or rotate state blindly.
4. Collect OS process evidence on SEM host and authenticated Runner evidence.
5. Classify E1–E5; if uncertain, retain shield and HIR.
6. Inspect Git origin branches and external systems for side effects.
7. Resume only after old execution is proven terminated/contained and new generation is safely claimed.
8. Record incident timeline and corrective action.

## 5. Workspace volume lost

1. Treat as execution-safety incident.
2. Do not infer process termination from missing PID/event files.
3. Stop new claims for affected execution scope.
4. Shield active Runs lacking E1/E2/E3 and create/associate HIR.
5. Rebuild Git Mirror from each Repository's sole authoritative origin only for safe future work.
6. Do not restore a stale workspace snapshot; none is maintained.

## 6. Runner offline

1. After heartbeat grace, classify as E4.
2. Set durable Scheduling Shield and create/associate HIR.
3. Send cancellation command when channel permits.
4. Command receipt is not E3.
5. Wait for OS exit observation; otherwise keep shield and escalate.

## 7. Boundaries

SEM does not host Platform API/MCP, manage Git multi-origin synchronization, back up Workspace/Worktree/Git Mirror, or introduce Redis/Kafka/RabbitMQ for V1.


## 8. Human Intervention and Detached recovery（Review Pending）

1. 检查 HIR 是否已创建、责任人/收件人是否解析、通知是否投递；通知失败时从 Inbox 查询，不能关闭 HIR 或释放 Barrier。
2. 对 Detached Run，先检查 Runner reconnect sync、boot_id、process identity、Lease/Generation；不要只凭 PID 或心跳推断进程状态。
3. 有 E1/E2/E3 时，按 Platform 受控事务终止旧 Attempt 并处理后继；只有命令 ACK 没有 E3 时继续隔离。
4. Workspace/PID/logs 丢失且 Run 曾启动时按 E5 处理；不删除/重建旧执行证据来“修复”状态。
5. E4/E5 下如确需重派，必须走 E6 高风险审批：展示可能重复的 Git/外部 API/LLM 副作用，记录缓解措施，绑定唯一 successor；旧 Barrier 保持未证实终止。
6. Interaction continue 失败、response 未注入或消费证据不足时，不得手工把 Interaction 标成 consumed，也不得清除其 scheduling_shield。
7. Cleanup Need 与 HIR 分开处理；清理完成不等于进程终止，HIR 关闭也不等于 Barrier 释放。
