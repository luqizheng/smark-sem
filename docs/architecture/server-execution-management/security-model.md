# SEM V1 Security Model

Status: security design baseline.

## 1. Principals

- Human user: may view/resolve HIR and select Runner within authorized tenant/project scope.
- Platform services: act under service identity and explicit permissions to Platform PostgreSQL.
- SEM service: authenticates to Platform only through its scoped service API identity; it has no Platform PostgreSQL credentials.
- Client Runner: device identity plus current lease proof; scoped to claimed Run/generation.
- Harness process: receives only execution-scoped credentials.
- Git remote: one authoritative origin per Repository.

## 2. Authorization

- Preserve exact lease_client_id/device identity binding.
- Every mutation checks tenant/project scope, Run identity, generation and current lease proof.
- HIR operations require user authorization and audit.
- Runner supervision changes require authorized user/admin action.
- SEM DB credentials are least-privilege and scoped only to SEM-owned tables; no runtime superuser.
- Platform DB credentials are never mounted into SEM containers; Platform APIs are the only route for Run/Lease/Generation mutations.

## 3. Lease and fencing

- Store token verifier/hash, not plaintext.
- Issue fresh token on claim and rotate on new generation.
- Reject stale generation and mismatched client identity.
- Generation fencing protects DB state, not Git/network/other external side effects.

## 4. Harness and Git credentials

- Use per-Run or per-Repository minimum-scope credentials where supported.
- Prefer short-lived, revocable credentials; do not inject long-lived personal tokens into generic Harness processes.
- SSH keys use restrictive permissions and temporary-file lifecycle.
- Environment, process arguments, stdout/stderr, executor events, exceptions and HIR details must not expose secrets.
- Revocation status/time is auditable. DB token rotation does not revoke a credential already held by an OS process.
- If an old process may still hold a credential, assume it can still perform external actions until process termination or credential-side revocation is confirmed.

## 5. E3 trust

E3 is accepted only when Runner supervisor authentication is valid; Run/generation/command/process identity match; supervisor observed OS process termination; and exit observation/time are included. Duplicate delivery is idempotent.

A process's own self-report that it is stopping is insufficient. A generic HTTP response is insufficient.

## 6. Workspace isolation

- One active writer per workspace.
- Every replacement Attempt gets a new workspace.
- Resolve workspace paths under configured root; reject traversal and symlink escape.
- Do not delete/reuse a workspace while process termination is uncertain.
- Runtime-persistent Workspace volume is not backed up.

## 7. Audit

Audit claim, generation rotation, shield creation/release, termination evidence, credential issuance/revocation, HIR transitions, Runner supervision changes and handoff. Redact secrets before persistence.


## 8. Platform–SEM service identity (ADR-SEM-22)

- Use separate service identities for Platform→SEM and SEM→Platform. Service identity is not a human principal and must not pass through ordinary human-principal resolution.
- Proposed V1: TLS plus short-lived asymmetric-signed JWT; issuer, subject, audience, scope, issued/not-before/expiry, key ID and token ID are validated. Maximum token lifetime 5 minutes; public keys rotate with overlap. mTLS is optional defense-in-depth, not the application authorization contract.
- SEM receives only Claim-for-Runner, Lease Renewal, command read/ACK, execution report, E3 submit and Runner authorization-read scopes. Platform→SEM delivery is limited to Inbox write.
- Every mutation has a stable idempotency key and correlation/causation identifiers. Same key/same semantic body returns prior result; conflicting reuse is rejected.

## 9. Runner WSS connect ticket and revocation (ADR-SEM-23)

- Runner authenticates to Platform with its registered device credential and obtains a short-lived, single-use ticket scoped to SEM audience and exact device identity. SEM validates Platform signature and atomically consumes ticket `jti`; never trust a payload-supplied Runner ID.
- Platform authorization changes (credential revoke, device disable, project unbind, tenant suspension) are emitted through Outbox to SEM; SEM closes affected connections. Periodic Platform API revalidation detects missed events. Proposed default authorization freshness window is 30 seconds; if it expires without successful revalidation, stop dispatch and close WSS.
- Revoking a connection does not prove the process is dead. Pending commands stop; active execution follows E1–E5 and HIR rules.

## 10. SEM persistence boundary (ADR-SEM-24)

The proposed minimum SEM-owned tables are `sem.inbox_event`, `sem.runner_connection`, `sem.runner_ticket_use`, `sem.dispatch_operation`, `sem.command_delivery`, `sem.platform_delivery` and `sem.process_observation`. Exact fields and exclusions are specified in `service-protocol-security-and-persistence.md`. SEM stores no Platform Run/Lease/Generation/HIR/command business authority and no plaintext Lease Token.

## 11. Lease Renewal and cross-service idempotency (ADR-SEM-21 / ADR-SEM-25)

- Lease Renewal is initiated only by Runner Supervisor over WSS and forwarded by SEM to Platform HTTPS. Platform alone validates and commits the renewal.
- WSS Heartbeat and Harness Agent Activity never renew a Lease.
- Claim and cross-service mutations use stable idempotency keys; Platform stores Claim result in the same transaction as Lease/Generation mutation.
- SEM does not persist plaintext Lease Token; token may exist only in bounded process memory for dispatch/relay and is always redacted.


## 12. Runner process evidence trust boundary（Review Pending）

Runner 进程退出报告通过已认证设备 WSS 连接上报，必须绑定 Runner/device、boot_id、Run、Generation、process creation identity、exit observation、source 和 digest。Lease token 失效不应阻止提交历史进程观察，但该接口只允许追加证据，不授予 Run 状态写权限。SEM 持久化后再转 Platform；Platform 校验精确 Generation 和身份。无法验证 boot/process identity 时降级 E5。

## 13. E6 Human Risk Acceptance authorization

E6 需要独立高风险权限、二次确认、操作者/时间/原因、残余风险展示、缓解措施、唯一 successor 绑定和不可变审计。E6 不代表进程终止，不替代 E1/E2/E3，不释放旧 Execution Barrier，不绕过租户/项目/设备授权、lease_client_id 或 Generation fencing。旧进程仍可能持有 Git/SSH/API 凭据；风险确认界面必须明确该事实。
