# SEM V1 Testing and Acceptance

A mock passing does not prove OS process semantics. Process and Runner ACK tests require real process/Runner integration.

## 1. Unit tests

- E1/E2/E3/E4/E5 classification and allowed-action matrix.
- Run lineage and monotonic Attempt numbering.
- HIR transition guards and authorization.
- Unified dispatchability predicate checks both Interaction scheduling_shield and independent Run Execution Barrier on every claim/recovery/requeue path.
- Generation/token/client identity validation.
- Runner supervision default and mode changes.
- Harness capability default supports_resume=false.
- Secret redaction and workspace path containment.

## 2. Database and concurrency

- Two claimers cannot own the same Run.
- Shielded Run is excluded from every claim candidate query.
- Expired shielded Run is not requeued by B3-2, B06-D3, orphan reconciliation or retry paths.
- Late heartbeat from old generation cannot clear shield or renew lease.
- New claim increments generation and rotates token verifier.
- lease_client_id mismatch is rejected.
- HIR constraints hold under concurrent creation.
- Empty database migration chain initializes all SEM schema.

## 3. OS process tests

- Live child + expired lease: no E1/E2; no reclaim.
- Child exits: E1 observed; guarded recovery allowed.
- Original process absent with validated process identity: E2; guarded recovery allowed.
- PID reused by unrelated process: never mistake unrelated process for original.
- Worker restart with runtime volume intact: reconcile without duplicate spawn.
- Volume loss while process remains alive: E4/E5 shield, no requeue.
- Cleanup refuses active/uncertain process workspace.

## 4. Runner protocol

- Command receipt ACK differs from termination confirmation.
- Runner sends E3 only after supervisor wait/handle observes process exit.
- ACK with stale generation, wrong command ID or process identity is rejected.
- Duplicate ACK is idempotent.
- Lost/delayed ACK remains E4/E5.
- Runner reconnects with stale token and is rejected.
- Default registration is unattended; supervised requires explicit configuration and pre-claim confirmation.

## 5. Harness Resume

For each exact Harness/version: collect native session ID; controlled supervisor restart; resume same native session; verify context continuity; verify workspace/process prerequisites; inject resume failure and confirm Fresh Attempt only after old process termination proof. Until all tests pass, supports_resume=false.

## 6. Fault injection and E2E

- SEM crash/restart at lifecycle boundaries.
- PostgreSQL outage during claim, heartbeat, termination and result acceptance.
- Runner network partition and loss during active process.
- E4 shield survives service restart and lease expiry.
- Authorized manual HIR resolution cannot bypass process safety.
- Two-Runner handoff with delayed/reconnected old Runner; no overlapping execution.
- Ten concurrent Runs with process and DB evidence assertions.
- Git origin unavailable during workspace reconstruction.
- Credential revocation and log-secret scanning.

## 7. Release gates

- Phase 0: no started Run can be reclaimed without E1/E2/E3; credentials meet minimum-scope/revocation/redaction requirements.
- Phase 1: SEM role registers no outbox handlers; Platform role spawns no execution processes.
- Phase 2: real independent-host execution and restart/volume-loss drill pass.
- Phase 3: Resume remains disabled unless exact-version evidence passes.
- Phase 4: HIR authorization/state tests and Runner ACK semantics pass.
- Phase 5: multi-Runner fault matrix green and audit chronology replayable.


## 8. Service boundary and authentication acceptance (ADR-SEM-22/25)

- Platform↔SEM service JWT rejects wrong issuer, audience, scope, expired/not-yet-valid token, revoked key and replayed token ID where one-time semantics apply.
- Service identity cannot authenticate as a human principal or invoke ordinary user-only routes.
- Platform Claim API rejects arbitrary/self-reported target Runner IDs and validates registered device, project binding and policy.
- Claim request timeout/retry with the same idempotency key produces exactly one Run lease and the same recoverable result.
- SEM logs/traces/DB never contain plaintext Lease Token or WSS ticket.

## 9. Runner WSS authorization acceptance (ADR-SEM-23)

- Expired, wrong-audience, wrong-scope, invalid-signature and replayed connect tickets are rejected.
- Device revocation/project unbinding closes active WSS connection and prevents further command delivery.
- Missed revocation event is caught by periodic revalidation; inability to revalidate before freshness deadline fails closed.
- Old connection epoch and stale generation messages are rejected after reconnect/handoff.
- WSS close/revocation does not mark process terminated; E1/E2/E3 evidence remains mandatory.

## 10. Inbox, delivery and dispatch acceptance (ADR-SEM-24/25)

- Platform Outbox is acknowledged only after SEM Inbox transaction commit.
- Duplicate event_id creates one Inbox record and one logical dispatch operation.
- SEM crash after Inbox commit resumes processing after restart.
- Lost Claim response does not create a second lease; same claim_request_id returns the same result.
- SEM crash after Claim but before WSS send resumes to the same target Runner or performs guarded cancellation; never blind redirection.
- Command receipt ACK and E3 termination ACK remain distinct and idempotent.
- SEM outbound reports survive restart through platform_delivery retry ledger.


> ADR-SEM-21–25 are approved architecture decisions. The tests in §§8–10 are implementation/acceptance gates and remain unpassed until the actual services and integrations exist and pass them.


## 11. Resource-aware Runner admission (ADR-SEM-26 — approved)

- Runner Supervisor reports CPU logical capacity and normalized utilization windows, memory total/available/pressure, and total/free bytes for the actual Workspace volume.
- Resource reports use authenticated WSS identity, boot_id, monotonic sample_seq and observed_at; stale, duplicate, out-of-order or invalid samples cannot overwrite a newer snapshot.
- Resource reporting is independent from Heartbeat and Lease Renewal; neither resource values nor resource-report loss can be interpreted as process termination evidence.
- Task resource profiles include CPU budget, peak memory budget and expected Workspace growth; unknown profiles use conservative defaults or single-task admission, never zero-cost assumptions.
- Concurrent dispatch attempts against one Runner cannot oversubscribe capacity: resource reservation is atomic and bound to dispatch operation / Run+Generation before Platform Claim.
- Claim rejection releases reservation only when the Platform result is definitive; timeout/unknown outcome retains reservation and retries/query with the same claim_request_id.
- Stale/unknown resource state blocks new dispatch but does not stop active Runs or release their reservations.
- Memory pressure and Workspace-volume low-space thresholds reject new dispatch; CPU saturation may lower scheduling priority or pause new admission according to configured policy.
- Reservations release only after safe terminal/termination handling; WSS disconnect, heartbeat loss, Workspace loss or resource sample expiry alone is insufficient.
- Windows Runner long-duration concurrent load tests calibrate thresholds and verify no runaway memory/disk consumption; Linux/macOS implementations must satisfy the same normalized contract before being enabled.


## 8. Corrective review acceptance matrix（Review Pending）

### 8.1 Interaction execution loop

- Agent 在 Runner 执行时创建 Interaction：terminate 命令必须通过 SEM WSS 到达正确 Runner，进程终止后报告 E3；用户回复后 continue 必须注入 checkpoint + response、启动新 Session 并完成消费回执。
- Agent 在 SEM-local CodexExecutor 执行时创建 Interaction：必须由 SEM-local Execution Control Adapter 消费 terminate/continue；不得因为命令消费者只有 Runner 而挂起。
- Command receipt、command result、E3、continuation-consumed 分别断言；任何一项不能冒充另一项。
- continue 重复投递必须幂等，不得启动第二个 Agent；continue 未成功注入时 Interaction 不得 consumed，shield 不得清除。

### 8.2 Runner process evidence and restart

- 自然退出、terminate、lease-loss cleanup、startup orphan cleanup、shutdown 均写入本地 evidence spool 并经 WSS 上报。
- WSS 断线时 spool 保留；重连后重复发送幂等；SEM ACK 前不得删除。
- Lease 已过期时仍允许报告旧 Run/Generation 的进程观察，但不得修改新 Generation 业务状态。
- Runner 重启后测试 same boot process reattach、boot transition proof、无法验证时 E5；覆盖 Detached → Reconciling → Active/Terminated/Quarantined。

### 8.3 Workspace loss / Lost semantics

- 对 stage=started Run 删除 PID、logs 和 Workspace volume：必须 E5/Uncertain，不得 Done{Lost}、释放 Barrier 或重派。
- stage=dispatch 且权威证明未 spawn：才可按 B3-1 处理。

### 8.4 HIR / notification

- Phase 0 即验证 HIR 创建、责任人解析、收件人通知、Inbox 可见、证据追加、hold/受控处置和审计。
- interaction.created 与 HIR created 在事务内产生 Outbox notification；收件人缺失进入项目级未分派队列并告警。
- 通知投递失败不改变 Interaction/HIR/Barrier 状态；120s deadline 不延迟通知。

### 8.5 E6

- E4/E5 默认拒绝自动重派；无 E6 时必须保持 Barrier。
- E6 必须二次确认、记录风险/缓解措施、绑定唯一 successor、保留旧 Barrier；重复点击或并发请求不能产生第二个 successor。
- E6 不能生成 E3，也不能把旧 Barrier 标成 released。

### 8.6 Unified dispatchability

- 对 shield=human_wait/start_wait/timed_out 的 queued Run，普通 claim 必须拒绝。
- B06-D3 不能把带 Interaction shield 或 active Execution Barrier 的 Run 回队并被普通 queued claim 领取。
- B3-1/B3-2、retry/requeue、orphan reconciliation、handoff 和 SEM Claim 全部验证同一谓词；锁内重验防竞态。

### 8.7 Session continuity

- Runner 本机采集 native session id 并上报；SEM 不读取 Runner CODEX_HOME。
- Interaction Continuation（checkpoint/reply 注入 + Fresh Session）、Process Reattachment、Harness Native Resume 分别测试。
- Native Resume 默认 false；跨设备仅复制 session id 必须失败/降级 Fresh Session。
