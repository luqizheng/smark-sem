# Execution Identity, Lifecycle, Fencing and Delivery Contract

- Status: **Detailed design draft / review pending**.
- Scope: bilateral AI-PM ↔ SEM contract and SEM ↔ Runner infrastructure contract.
- Authority: AI-PM owns business authorization and business state; SEM owns execution transport, Runner binding and infrastructure resource state; Runner Supervisor owns local Harness process supervision.
- This document refines the opaque-message architecture. It does not authorize implementation, migrations, Phase 0, or PR merge.
- Related: [Platform–SEM–Runner Execution Message Protocol](./PLATFORM-SEM-EXECUTION-MESSAGE-PROTOCOL-DRAFT.md).

## 1. Non-negotiable boundary

SEM may understand only:
- its own execution_id, request/delivery/release identities and message envelopes;
- Runner identity, registered capabilities, supervision mode, connection/health and resource telemetry;
- its binding/execution epoch, delivery state, process observations and resource reservations;
- opaque payload bytes and opaque AI-PM-issued authorization material that SEM is instructed only to transport.

SEM must not understand or derive:
- Task, Requirement, Project, AI-PM Run business state, approval, HIR, Barrier, acceptance, retry eligibility or business completion;
- Task identity from prompt text, payload JSON, filenames, Git branch names or correlation metadata;
- business authorization from Runner eligibility, a successful delivery ACK, process exit code or resource release.

The prompt/body is opaque. SEM may enforce envelope size, content type, encryption, retention and routing policy. It must not parse or transform its meaning. Runner infrastructure metadata is not business authorization.

## 2. Canonical identity model

Three identities must remain distinct:

| Identity | Issuer/owner | Meaning |
|---|---|---|
| Delegating actor | AI-PM | Human or explicitly authorized Platform actor that authorized the business attempt; attribution only |
| Delegated execution grant | AI-PM | Short-lived authority for one Harness execution attempt to call a narrow set of AI-PM MCP operations |
| Runner identity | SEM registration + Runner key | Infrastructure endpoint/process host receiving the opaque execution |

The Harness is not a human and must not be represented by fabricating a HumanActor. A delegated grant does not impersonate the delegating human. SEM service credentials and Runner WSS credentials are never valid AI-PM MCP credentials.

### 2.1 AI-PM grant claims and enforcement

The grant is AI-PM-issued and must bind at minimum:
- issuer and audience (the AI-PM MCP/API audience);
- tenant_id, project_id, task_id and AI-PM run_id/attempt_id;
- immutable execution_id;
- AI-PM authorization_generation;
- an explicit operation/capability allow-list;
- delegating actor identity and distinct Harness executor identity;
- runner_id and Runner public-key thumbprint (or an equivalent cryptographic channel binding);
- issued_at, not_before, expires_at, unique jti and revocation/consumption state.

Every MCP call must be authorized at the AI-PM application-service boundary against the current grant and exact resource tuple. A caller-supplied task_id, run_id, execution_id or correlation_id is a selector, never proof of authority. Reads are scoped too: changing task_ref must not expose another Task.

The allow-list should be typed, not a broad task:update wildcard. It may include only the business operations required by the current Harness workflow, for example:
- read the authorized Task and its execution context;
- report progress for that exact attempt;
- submit a delivery/result for that exact attempt.

It must exclude formal review/approval, acceptance, project administration, membership changes, arbitrary Task status setting, cross-Task reads/writes and unrestricted Git credential access. Human-only review/approval guards remain human-only.

AI-PM must persist an auditable grant record or equivalent revocation authority. Audit records preserve delegating actor, Harness executor, Runner identity, execution_id, authorization_generation, operation, decision and timestamp. Do not log bearer tokens or bootstrap secrets.

### 2.2 Recommended credential bootstrap: two-stage, Runner-bound

The preferred design is a two-stage exchange. The exact token encoding and cryptographic library remain implementation decisions; the security properties below are required.

1. **Request and reserve.** AI-PM creates a new execution_id and persists its business attempt plus an Outbox execution.requested message. It sends the opaque prompt and infrastructure-only Runner requirements to SEM. No human API key, reusable MCP bearer token or business authorization secret is included.
2. **Bind.** SEM selects an eligible Runner, reserves capacity, increments the SEM binding epoch and emits execution.binding_established containing execution_id, binding_epoch, runner_id and the registered Runner public-key thumbprint / authenticated identity evidence.
3. **Authorize.** AI-PM verifies the binding event using its authenticated trust in SEM and independently validates the Runner key against an enrollment record or certificate authority that AI-PM trusts. A Runner public-key thumbprint supplied only by SEM is not sufficient if the security requirement is that SEM itself must not be able to redeem the ticket: otherwise a compromised SEM could substitute its own key. AI-PM creates the narrowly scoped delegated grant for the exact attempt and generation, then sends an opaque one-time bootstrap ticket to SEM for transport to that exact Runner binding.
4. **Redeem.** Runner Supervisor's local credential broker redeems the ticket directly with AI-PM over an authenticated channel. The ticket is one-time, short-lived, execution-bound, binding-epoch-bound and cryptographically bound to the Runner key. SEM can relay it but cannot redeem it or read the resulting MCP credential.
5. **Inject.** The local broker injects the short-lived MCP credential into the Harness MCP connection without placing it in the prompt, command-line arguments, workspace files or ordinary logs. Prefer a local broker/proxy so the token is not exposed to unrelated Harness processes.
6. **Use and revoke.** AI-PM checks the grant on every MCP call. Revocation/expiry/attempt replacement denies subsequent calls. Runner Supervisor separately stops or isolates the process when required.

The bootstrap ticket must not be a bearer secret usable by any Runner. It must be redeemable only by the registered Runner key for the matching execution_id + binding_epoch, once, before expiry. A replay, wrong Runner, wrong epoch, expired ticket or already-consumed ticket is rejected. SEM must not store plaintext reusable MCP tokens.

If this flow cannot be implemented with the existing Runner registration trust model, stop and design the trust bootstrap explicitly; do not fall back to a human API key in the prompt.

### 2.3 Authorization revocation and generation

authorization_generation belongs to AI-PM. It is monotonically advanced or replaced whenever the old attempt grant must become invalid, including business retry, cancellation/revocation, or a rebind that authorizes a different Harness process.

AI-PM must atomically make the old generation inactive before authorizing a successor grant. Every MCP request validates current generation, not merely token signature and expiry. Short token TTL limits exposure but is not a substitute for generation checks/revocation.

Revoking MCP authority does not prove the process stopped. A stale Harness may still perform local filesystem, Git remote or external-network side effects. Process isolation and external side-effect fencing are separate Runner/AI-PM concerns.

## 3. Three lifecycles and their correlation

There are three independent lifecycles:

| Lifecycle | Authority | Key | What it decides |
|---|---|---|---|
| Business Task | AI-PM | task_id | Whether business work is ready, running, submitted, reviewing, completed, blocked or cancelled |
| Business Run/attempt | AI-PM | run_id + attempt identity + authorization_generation | Which business attempt is authorized, what evidence is accepted, and its business outcome |
| Infrastructure Execution | SEM | execution_id + binding_epoch | Whether a request is queued, bound, delivered, process-running, releasing, released, failed or uncertain |

AI-PM owns the mapping from Run/attempt to opaque execution_id. SEM stores execution_id and transport metadata only; it must not store Task IDs or mirror Run/Task states. correlation_id is for tracing only.

One AI-PM Run attempt maps to at most one active SEM execution_id. A new business retry creates a new attempt and a new execution_id. Transport retries reuse the same request_id/execution_id and do not create a new business attempt. Rebinding infrastructure for the same attempt may advance binding_epoch, but it must not silently authorize a second Harness while the old process may still run.

Task, Run and SEM Execution terminal states are not equivalent:
- Harness process exit does not complete the Task.
- Task submission does not necessarily complete the Task.
- Task completion may precede SEM process cleanup.
- SEM release may occur while Task is submitted/reviewing or waiting for a human decision.
- SEM release failure does not roll back an AI-PM business decision.

## 4. Message, inbox/outbox and idempotency contract

### 4.1 Platform outbox

AI-PM persists the business decision and corresponding SEM intent in the same AI-PM database transaction:
- creating/authorizing an attempt and execution.requested;
- deciding the attempt no longer needs a runtime and execution.release_requested;
- revoking an authorization generation and the corresponding stop/release intent when policy requires both.

The outbox is delivered at least once. A sender retries the same immutable message_id/request_id and canonical payload. A timeout is an unknown outcome, not proof of rejection. AI-PM must query/reconcile by request_id/execution_id before creating a replacement attempt.

### 4.2 SEM inbox and durable execution ledger

SEM durably records an accepted Platform message and its idempotency key before returning accepted. Duplicate delivery with the same idempotency key and same canonical payload returns the original outcome. Reuse of an idempotency key with different payload is a conflict and is rejected/audited.

SEM's durable ledger tracks only infrastructure facts: request acceptance, selected Runner, binding_epoch, delivery_id, reservation, delivery receipt, process observations, release request and release outcome. It does not store Task state or interpret the payload.

### 4.3 Runner message deduplication and ordering

Every Runner-directed operation has a stable operation ID (delivery_id or release_id) and is bound to execution_id + binding_epoch. Runner Supervisor persists deduplication and process ownership records locally before launching/stopping a process.

Runner→SEM observations carry:
- event_id (globally unique);
- execution_id and binding_epoch;
- runner_id;
- monotonically increasing per-execution event_sequence;
- event_type and occurred_at;
- process_identity where relevant;
- evidence metadata and signature/authenticated-channel provenance.

SEM deduplicates event_id and rejects events from stale bindings. It detects sequence gaps and reconciles rather than assuming missing events did not occur. SEM→AI-PM infrastructure events are also at-least-once and deduplicated by event_id; AI-PM applies them idempotently and never maps them directly to Task status.

There is no cross-database transaction. Correctness comes from local transactions, durable inbox/outbox, stable IDs, idempotent handlers and reconciliation.

## 5. SEM Execution lifecycle and dispatch

Suggested infrastructure states (names are illustrative, not business semantics):

accepted → queued → reserved → bound → delivering → delivered → starting → running → releasing → released

Failure/uncertainty branches include rejected, delivery_failed, start_failed, infrastructure_uncertain and cleanup_failed.

Rules:
- Runner selection uses registered capability, configured Harness profile, unattended/supervised mode, connectivity and fresh resource telemetry (CPU, memory, disk/workspace volume).
- Default supervision mode is **unattended** unless AI-PM explicitly requests a supported alternative.
- Resource reservation is atomic within SEM and must account for reported capacity plus active reservations; telemetry is an input, not an exact guarantee.
- A Runner is not eligible if telemetry is stale, capacity is insufficient, required Harness capability is absent, or its connection/registration is unhealthy.
- SEM may queue when no Runner is eligible. It must not mutate AI-PM Task/Run state because dispatch is delayed or rejected.
- The prompt remains opaque through persistence, selection, delivery, retries and release.
- One execution_id may not have two concurrently active process bindings unless a future explicitly approved multi-process contract says otherwise.

## 6. Process ownership, observation and fencing

### 6.1 Runner Supervisor owns the process

Runner Supervisor is the only component that launches, attaches to, terminates and observes the local Harness process. It must persist a local process registry before/at launch containing:
- execution_id, binding_epoch and delivery_id;
- runner_id and supervisor_instance_id;
- OS boot identity and process identity (PID plus process start identity; PID alone is insufficient);
- Harness profile and launch timestamp;
- current local lifecycle and last reported event sequence.

The process registry is operational state, not a workspace backup. No workspace/worktree backup is introduced.

harness.process_exited requires positive OS-level observation by the Supervisor (for example, successful wait/reap of the exact child process and matching process start identity), with exit code/signal and observation metadata. Heartbeat loss, WSS disconnect, timeout, process-list absence from an untrusted source, workspace deletion, command ACK or exit claim from the Harness itself is not sufficient.

### 6.2 Two independent fencing domains

| Fence | Authority | Rejects |
|---|---|---|
| authorization_generation | AI-PM | Stale Harness MCP business reads/writes for a replaced/revoked attempt |
| binding_epoch | SEM | Stale Runner delivery, process observations, release and cleanup messages for an old Runner binding |

A business retry changes AI-PM attempt identity and authorization_generation and uses a new execution_id. A Runner rebind advances binding_epoch. Neither fence substitutes for the other.

A rebind to another Runner is permitted only after the old process is positively exited or an explicitly approved isolation/fencing action makes its further side effects impossible. Revoking the old MCP grant is necessary where authority changes, but is not sufficient proof of process termination.

### 6.3 Disconnect and uncertain state

On Runner disconnect without positive process-exit evidence:
1. Mark the SEM execution infrastructure_uncertain.
2. Retain/quarantine the old Runner binding and its resource reservation; do not treat the reservation as free capacity.
3. Do not dispatch a competing Harness for the same execution/attempt.
4. Reconcile on reconnect using the Runner's persisted process registry and signed/authenticated event sequence.
5. If the Runner cannot return, require an independently verified host/process isolation or termination procedure before releasing the reservation or rebinding.

No timeout alone may convert infrastructure_uncertain to released or process_exited. If the deployment cannot prove the old host is fenced, the safe outcome is continued quarantine and explicit operator escalation.

### 6.4 Release and process exit races

Release is an AI-PM business instruction but process termination is an infrastructure action:
- SEM validates execution_id + expected binding_epoch and deduplicates release_id.
- Runner Supervisor applies graceful stop, then forced termination only under the configured policy/deadline.
- Natural exit may arrive before release; preserve both facts and make release idempotently converge to cleanup complete.
- Release may arrive before process start completes; Supervisor must prevent a late launch after a release fence has been applied.
- A stale release for epoch N must never stop a process bound to epoch N+1.
- SEM releases resource reservation only when process-exit/absence is positively established and cleanup policy permits. If cleanup is uncertain, retain quarantine.

## 7. Delivery and business-result contract

### 7.1 Harness business interaction

Harness obtains Task context and performs all business operations directly through AI-PM MCP. It never asks SEM for Task context or reports business state to SEM as an authority channel.

AI-PM must provide a delegated MCP surface that:
- returns only the exact authorized Task and execution context;
- checks authorization_generation and operation allow-list on every call;
- provides typed progress and result-submission operations;
- validates Task state transitions and delivery evidence;
- rejects arbitrary status setting and all human-only approval/review operations.

The current Task lifecycle is not replaced by this document. In the audited source baseline, a delivery submission advances Running→Submitted when its manifest is valid; Submitted→Reviewing and Reviewing→Completed remain guarded business transitions, with acceptance evidence required for completion. The manual Ready→Completed path remains human-only. These semantics must be revalidated against the implementation baseline before code work.

Process heartbeat, CPU/memory/disk telemetry and process exit are infrastructure observations through SEM, not pm_report_progress or other business progress operations.

### 7.2 Remote Git evidence

AI-PM must not assume it can read a Runner-local worktree. For remote execution evidence:
1. AI-PM issues or authorizes a unique execution-scoped branch/ref and records the locked baseline commit.
2. Harness pushes the intended commit to that ref.
3. Harness submits the ref and exact commit SHA through AI-PM MCP.
4. AI-PM fetches the remote ref and verifies it resolves to the submitted SHA.
5. AI-PM verifies the locked baseline is an ancestor of the submitted commit.
6. AI-PM computes changed-file facts from the fetched Git object graph (for example, diffing baseline to submitted SHA). A Harness-declared file count is not independent evidence.
7. If the ref/SHA cannot be fetched or verification fails, submission is rejected or remains explicitly unverified; it is never silently treated as verified delivery.

A remote ref proves the pushed Git object state, not the Runner-local worktree HEAD. If exact local workspace state is required, define a separate signed Runner attestation and trust model. SEM may transport an opaque evidence reference but does not inspect Git, refs, commits or Task semantics.

### 7.3 Submission, completion and release

Harness submits delivery; AI-PM validates and records it. Submission is not acceptance and is not Task completion. AI-PM alone decides review/acceptance and Task completion.

When AI-PM decides a Run attempt no longer needs a runtime, it commits the business decision and release Outbox intent atomically. SEM receives only execution_id, expected binding_epoch (or a safe reconcile-before-release command), release_id and infrastructure stop policy. It receives no Task status or business reason beyond an optional opaque audit code.

## 8. Required acceptance tests before implementation approval

### Identity and MCP
1. Human API key, SEM service JWT and Runner WSS credential cannot be used as delegated Harness MCP credentials.
2. Grant is bound to exact tenant/project/task/run/attempt/execution/generation and Runner key.
3. Cross-tenant, cross-project, cross-Task, wrong-Runner, wrong-epoch, expired, revoked, replayed and wrong-operation calls are rejected.
4. A delegated grant cannot approve, formally review, accept, administer a project or set arbitrary Task status.
5. Delegating actor and Harness executor remain distinct in audit; secrets never appear in prompt, SEM logs or ordinary process arguments.

### Lifecycle and messaging
6. Duplicate Platform request, duplicate Runner delivery, duplicate release and duplicate infrastructure event are idempotent.
7. Same idempotency key with different payload is rejected.
8. Outbox commit is atomic with the corresponding AI-PM business decision; crash/retry does not lose the intent.
9. SEM restart recovers inbox, execution ledger, reservations and pending delivery/release without reconstructing business state.
10. Event sequence gaps and stale binding events are detected and reconciled.

### Fencing and process safety
11. Runner disconnect while Harness is alive does not free capacity or dispatch a competing Harness.
12. Old Harness MCP calls fail after generation revocation, while test proves this does not count as process-exit evidence.
13. PID reuse, Runner reboot, supervisor restart, delayed exit event and stale release cannot confuse process identity.
14. Release arriving during startup prevents a late process from escaping the release fence.
15. Rebind is denied until positive exit or independently verified isolation.

### Delivery
16. Harness cannot self-complete Task; existing Task transition guards remain effective.
17. Remote Git submission is verified from a host without access to Runner workspace.
18. Changed-file facts are computed from Git objects, not copied from Harness claims.
19. Process exit code 0 does not mark business Run/Task successful.
20. Task completion may coexist with SEM releasing/uncertain; release failure does not roll back business completion.

## 9. Decisions still open

These are intentionally not guessed:
- Exact Runner registration trust chain and independent AI-PM validation of the Runner key/certificate; SEM must not be the sole source of the key binding.
- Exact bootstrap ticket/token format, signing/encryption algorithms, key rotation and credential-broker IPC.
- Whether binding_epoch alone is sufficient or a separate delivery/process generation is needed for restart semantics.
- Exact resource reservation model and stale telemetry thresholds.
- Exact process-isolation/fencing procedure for a permanently unreachable Runner host.
- Exact remote Git provider credentials, branch naming/cleanup policy and protected-ref behavior.
- Final bilateral event endpoint, retry/backoff, retention and payload size limits.

Do not resolve these by weakening the security invariants. No code, migration, runtime config, Phase 0 or merge is authorized by this draft.


## 10. Current AI-PM source compatibility gate

The AI-PM read-only source review (see [Harness identity and business fencing review §10](https://github.com/luqizheng/ai-pm/blob/docs/sem-02e-architecture-convergence/docs/architecture/server-execution-management/harness-identity-and-business-fencing-review.md)) found that the current `cpk_` device credential is a reusable device-wide secret. AI-PM stores only its hash, but successful authentication maps it to the device owner's HumanActor and existing project-membership authorization. Device enrollment currently records device metadata and `is_runner`, not a cryptographically enrolled Runner public key/certificate.

Therefore:
- Existing `cpk_` is not an acceptable delegated Harness grant and must not be passed to Harness as a shortcut.
- Existing `devenv.device` enrollment cannot, by itself, prove Runner key possession or provide the independent key trust required by §2.2.
- The delegated execution grant requires a distinct AI-PM identity/authorization design and exact application-service enforcement. Reuse of any existing device tables is a future schema/domain decision, not assumed here.
- The Runner enrollment/attestation design must specify proof of private-key possession, owner/admin approval, Runner key rotation, revocation, recovery after host reinstall, duplicate device IDs, and how AI-PM independently validates the Runner key rather than trusting SEM-supplied key material.

This source finding is a hard design gate. It is not permission to alter current device authentication or introduce migrations.
