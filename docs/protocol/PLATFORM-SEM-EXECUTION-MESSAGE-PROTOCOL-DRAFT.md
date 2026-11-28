# Platform–SEM–Runner Execution Message Protocol Draft

- Version: Draft 0.2
- Status: Architecture review only; not normative and not implementation-authorizing.
- Replaces: the superseded Platform–SEM–Runner Protocol V1.
- Authority baseline: [SEM Authority Boundary and Execution Message Model](../architecture/SEM-AUTHORITY-BOUNDARY-AND-EXECUTION-MESSAGE-MODEL.md).
- Detailed companion contract: [Execution Identity, Lifecycle, Fencing and Delivery Contract](./EXECUTION-IDENTITY-LIFECYCLE-FENCING-DELIVERY-CONTRACT-DRAFT.md).
- Machine-readable HTTP contract: [OpenAPI 3.1 draft](./openapi/platform-sem-v1-draft.yaml).
- Reusable HTTP message schemas: [Platform–SEM v1 JSON Schema](./json-schema/platform-sem-v1.schema.yaml).

## Transport deployment profile (V1)

Platform↔SEM and Runner↔SEM transport security is configurable for company-internal deployment; the application message contract does not change with the transport choice.

- Platform↔SEM supports both HTTP and HTTPS. Both endpoints must be reachable only through the company private network/VPN or an explicitly approved internal network segment. V1 has no public internet ingress requirement.
- HTTPS is supported with publicly trusted certificates, enterprise-private CA certificates, or self-signed certificates. A self-signed certificate is a supported production deployment option when its trust is explicitly provisioned.
- Clients must validate the configured trust chain or an explicitly pinned certificate/public-key fingerprint. Certificate validation must never be silently disabled; no production `--insecure` / verify=false mode.
- Runner registration CLI and WSS clients use the same configurable trust-material model (CA bundle or explicit pin), while Runner key proof-of-possession remains separate from TLS server authentication.
- HTTP is permitted only on the restricted internal network. It provides no transport confidentiality; request authentication, integrity protection, timestamp/nonce replay defense, idempotency and audit remain mandatory. Sensitive fields that require confidentiality must be protected at the application layer or sent over HTTPS.
- Certificate expiry, renewal, rotation, overlap, revocation and trust-material distribution are D-09 operational requirements. A trust change must not silently downgrade validation.

This is a deployment/transport choice, not two business protocols. Endpoint configuration selects `http://` or `https://`; message schemas, Outbox/Inbox, idempotency and reconciliation are identical.

## 1. Contract invariants

1. AI-PM owns all business semantics and business state. SEM is an execution-message transport and infrastructure coordination service.
2. SEM treats the prompt body as opaque. It never parses prompt instructions to infer Task identity, business intent, status, approval, retry eligibility or completion.
3. Harness obtains Task context and performs business operations directly through independently authenticated AI-PM MCP.
4. Runner Supervisor owns local Harness process launch/attach/stop, OS process identity and exact process-exit observation. SEM transports commands and stores/reports Runner observations; it does not own the remote OS process.
5. AI-PM decides business completion/cancellation and sends SEM an explicit release/stop instruction.
6. Task lifecycle and SEM Execution lifecycle are independent.
7. No shared database, distributed transaction, SEM access to Platform PostgreSQL, or business-state mirror.
8. Every message is authenticated, versioned, idempotent and correlated. Stale release messages must not stop a newer execution. HTTP message IDs and idempotency keys are carried in both the envelope and headers where defined; the receiver rejects disagreement.


## 1.1 HTTP service authentication and integrity (approved cryptographic baseline)

Because V1 permits private-network HTTP as well as HTTPS, TLS cannot be the sole request-authentication or integrity mechanism. The approved V1 cryptographic baseline is **asymmetric Ed25519 HTTP Message Signatures**, using the standardized HTTP Message Signatures and Content-Digest fields:

- HTTP Message Signatures: RFC 9421 — https://www.rfc-editor.org/rfc/rfc9421
- Content-Digest: RFC 9530 — https://www.rfc-editor.org/rfc/rfc9530

Each service direction has its own signing keypair: AI-PM signs Platform→SEM requests; SEM signs SEM→AI-PM callbacks and HTTP responses. The private key remains in the owning service. The peer pins/loads the public key under a configured key_id. These service keys are separate from Runner Ed25519 identity keys, TLS certificates and Harness delegated credentials.

Required signature coverage for every request:

- `@method`, `@authority`, `@path`, `@query`;
- `content-digest;sf` and `content-type` (RFC 9530 Content-Digest is canonicalized using RFC 9421 Structured Field serialization, including the digest of an empty body for bodyless requests);
- `x-sem-message-id` when the operation has a message ID;
- `idempotency-key` for mutating/idempotent operations;
- signature parameters `created`, `expires`, `nonce`, `keyid` and `alg=ed25519`.

Wire headers follow RFC 9421 (`Signature-Input` and `Signature`) and RFC 9530 (`Content-Digest`). The receiver verifies the HTTP signature and body digest before parsing or persisting the request. It then atomically checks the nonce replay registry and message/idempotency record. Same key + same idempotency key + same canonical body returns the original disposition; same key with a different body is a conflict.

Provisional freshness values (not yet normative): `created` may be at most 30 seconds in the future and no more than 60 seconds old; `expires` must not exceed `created + 60 seconds`; nonce is a cryptographically random value with at least 128 bits of entropy and is single-use per key_id. The receiver retains consumed nonces for at least 10 minutes and rejects duplicates. These are proposed initial bounds, not frozen operational values.

Responses are also signed by the responding service. The earlier shorthand response component list is superseded by the dedicated [D-04 HTTP Signed Response and Conditional GET Contract Addendum](./D04-HTTP-SIGNED-RESPONSE-AND-CONDITIONAL-GET-ADDENDUM.md), especially its §8 candidate serialization profile. In particular, response signatures bind `@status`, `content-digest;sf`, the direction-specific response correlation field (`X-SEM-Request-Id` equals the authenticated `Idempotency-Key` for Platform→SEM; `X-SEM-Event-Id` equals the authenticated `Idempotency-Key` for SEM→AI-PM callback), and the originating request components using RFC 9421 `;req` parameters; they do not use a bare response-derived `@authority`. For valid envelopes the authenticated header equals body `request_id`/`event_id`; on signed validation errors the response MUST correlate only to the authenticated header, never an unverified body field. The authenticated-versus-pre-authentication error response boundary is defined in the D-04 bilateral addendum §18. The addendum defines a distinct 304 component set and request-context association contract. Clients verify the response signature before trusting any 2xx, 4xx or 5xx outcome. This protects response integrity/authenticity on HTTP; it does not provide confidentiality. The addendum remains Draft / not ratified, so these exact details are not yet an implementation authorization.

Key lifecycle requirements: distinct key IDs per environment and direction; public-key distribution through trusted deployment configuration; overlapping old/new public keys during rotation; explicit revocation; no automatic fallback to unsigned requests; unknown, expired or revoked key IDs fail closed. The exact key storage mechanism belongs to D-09.

**Cryptographic decision approved:** Ed25519 + RFC 9421 + RFC 9530 is the V1 HTTP request/response authentication and integrity baseline. Exact covered-component sets, header names, timestamp/nonce bounds, OpenAPI representation, key lifecycle operations and interoperable test vectors remain D-04/D-09 closure items. The algorithm-family decision is closed; P0-01 remains open for wire-level specification and validation.

## 2. Identifiers

| Identifier | Owner | Purpose |
|---|---|---|
| message_id | Sender | Unique message identity / deduplication |
| request_id | AI-PM | Idempotency identity for one execution request |
| execution_id | AI-PM | Opaque identity for one requested execution attempt; not a Task ID |
| binding_epoch | SEM | Fencing token for the current Runner binding |
| delivery_id | SEM | One durable SEM→Runner delivery operation |
| runner_id | SEM / registered identity | Infrastructure endpoint identity |
| correlation_id | AI-PM | Trace correlation only; never authorization |
| process_identity | Runner | Exact local OS process identity, including boot/start identity |

A new business execution attempt should receive a new execution_id from AI-PM. SEM may retry delivery of the same execution_id idempotently. SEM increments binding_epoch when it establishes or replaces a valid Runner binding. SEM reports the current binding through an execution.binding_established infrastructure event. AI-PM stores that opaque epoch with its execution mapping and includes it in a release request. An old epoch cannot stop a newer binding. If AI-PM has not received the latest binding event, it must query/reconcile the execution by execution_id before issuing a fenced release.

binding_epoch allocation rules (P0-06 contract baseline): the first binding of an execution MUST use `binding_epoch = 1`; every later accepted rebind allocates a strictly greater epoch in the same per-execution sequence. SEM is the only authority that allocates epochs; an epoch that AI-PM has never received through an authenticated event does not exist for dispatch or release purposes. AI-PM's consumer-side projection rules for these events are defined in [§7.2](#72-binding-projection-event-contract-p0-06).

## 3. Platform → SEM: execution request

Suggested endpoint: POST /internal/sem/v1/executions

~~~json
{
  "message_id": "uuid",
  "message_type": "execution.requested",
  "schema_version": 1,
  "occurred_at": "RFC3339 UTC",
  "request_id": "uuid",
  "correlation_id": "uuid",
  "payload": {
    "execution_id": "uuid",
    "prompt": {
      "content_type": "text/plain; charset=utf-8",
      "body": "请获取任务 A，并且执行。"
    },
    "harness_profile": "codex",
    "runner_requirements": {
      "capabilities": ["codex"],
      "supervision_mode": "unattended"
    }
  }
}
~~~

Rules:
- No Task ID, Task status, acceptance criteria, requirements body, business Run state or business authorization decision is required by SEM.
- Business context is obtained by Harness through AI-PM MCP according to the instructions in the prompt.
- runner_requirements contains infrastructure capability constraints only. It does not express business priority or Task eligibility.
- The prompt body is opaque to SEM. SEM may validate content type/size and encrypt/persist it, but must not interpret it.
- The request must not contain a reusable Platform service credential or a human credential in plaintext.
- If the body is too large, a short-lived authenticated content reference may replace the inline body. Its retrieval and expiry policy remain open contract items.

## 4. SEM → Platform: acceptance response

~~~json
{
  "message_id": "uuid",
  "request_id": "uuid",
  "execution_id": "uuid",
  "acceptance": "accepted",
  "accepted_at": "RFC3339 UTC"
}
~~~

Possible acceptance values: accepted and duplicate. Rejections use the structured HTTP error envelope and an appropriate status code.

Acceptance means only that SEM durably accepted the infrastructure execution request. It does not mean a Runner was selected, the prompt was delivered, Harness started, or business work began. The binding_epoch is assigned only when a Runner binding is established and is reported in execution.binding_established; it is not part of the initial durable-acceptance response.

Duplicate request_id with the same canonical payload returns the original acceptance result. The same request ID with a different payload is a conflict.

## 5. SEM → Runner: opaque prompt delivery

~~~json
{
  "message_id": "uuid",
  "message_type": "execution.deliver",
  "schema_version": 1,
  "execution_id": "uuid",
  "binding_epoch": 1,
  "delivery_id": "uuid",
  "harness_profile": "codex",
  "prompt": {
    "content_type": "text/plain; charset=utf-8",
    "body": "请获取任务 A，并且执行。"
  }
}
~~~

Runner behavior:
1. Validate the SEM connection and message identity.
2. Deduplicate delivery_id/execution_id/epoch so duplicate WSS delivery cannot launch a second Harness for the same attempt.
3. Check whether the configured Harness is installed and available; start/attach according to Runner policy.
4. Inject the prompt into the Harness.
5. Report transport receipt and Harness launch outcome separately.
6. Harness uses AI-PM MCP directly for Task context and business operations.

Runner must not fetch Task context from SEM or ask SEM to mutate Task state.

## 6. Infrastructure observation directions

SEM→AI-PM events:
- execution.binding_established: SEM selected and bound the execution to a Runner and assigned binding_epoch.
- execution.delivery_status: SEM's durable delivery state and any Runner receipt.
- harness.process_observed: SEM-relayed Runner process start/exit observation.
- execution.release_status: SEM's release/cleanup state.
- execution.infrastructure_uncertain: SEM cannot currently prove the process/binding state.
- execution.unbound_release_applied: an unbound release won the dispatch fence; no Runner/binding/process facts exist (§7.1).

Runner→SEM observations:
- execution.delivery_received: Runner Supervisor durably accepted the delivery operation.
- harness.starting: local launch is in progress.
- harness.started: exact Harness process identity has been established.
- harness.start_failed: launch failed before a process was established.
- harness.process_exited: exact local process identity exited, with exit code and OS evidence metadata.
- runner.resources.report: CPU, memory and workspace-volume telemetry.
- execution.release_applied: Runner processed the release instruction and reports cleanup/process facts.

Heartbeat loss, resource telemetry, agent activity, timeout, workspace deletion and a command receipt are not process-exit evidence.

## 7. AI-PM → SEM: release/stop instruction

Suggested endpoint: POST /internal/sem/v1/executions/{execution_id}/release

The request carries a tagged expected-binding condition (P0-07). The bound form:

~~~json
{
  "message_id": "uuid",
  "message_type": "execution.release_requested",
  "schema_version": 1,
  "request_id": "uuid",
  "correlation_id": "uuid",
  "payload": {
    "execution_id": "uuid",
    "release_id": "uuid",
    "expected_binding": { "state": "bound", "binding_epoch": 1 },
    "stop_policy": {
      "mode": "graceful_then_force",
      "grace_period_seconds": 30
    }
  }
}
~~~

The unbound form cancels an accepted execution that AI-PM believes has no Runner binding:

~~~json
{
  "payload": {
    "execution_id": "uuid",
    "release_id": "uuid",
    "expected_binding": { "state": "unbound" },
    "stop_policy": { "mode": "force", "grace_period_seconds": 0 }
  }
}
~~~

Rules:
- AI-PM sends this only after its own business decision (Task completed, cancelled, or otherwise no longer requiring this execution).
- The schema uses a strict oneOf: `unbound` forbids `binding_epoch`; `bound` requires an integer `binding_epoch >= 1`. The legacy untagged `expected_binding_epoch` field is rejected by the envelope schema.
- SEM linearizes every release against its single per-execution dispatch/release sequencer (§7.1); it never judges dispatch permission in two services or two transactions.
- For bound releases SEM validates the exact execution_id and binding_epoch, deduplicates release_id, and forwards the stop request to the bound Runner.
- Runner Supervisor owns the actual local graceful/forced process termination.
- Repeated release requests with identical canonical bodies are idempotent; the same release_id with a changed expected_binding or stop policy is `409 IDEMPOTENCY_CONFLICT`.
- A stale epoch is rejected and must never terminate a newer execution.
- Release is not a Task transition and must not update business state.
- Do not fabricate an epoch, a Runner identity, a stop fence or process-exit evidence for an unbound execution; the unbound outcome is expressed only through §7.1 and the execution.unbound_release_applied event.

## 8. SEM → AI-PM: infrastructure result

Distinct infrastructure event types (the normative set is the six-way discriminated union in `json-schema/platform-sem-v1.schema.yaml`):
- execution.binding_established
- execution.delivery_status
- harness.process_observed
- execution.release_status
- execution.infrastructure_uncertain
- execution.unbound_release_applied (P0-07 dispatch-fence tombstone; §7.1)

~~~json
{
  "message_id": "uuid",
  "message_type": "execution.release_status",
  "schema_version": 1,
  "occurred_at": "RFC3339 UTC",
  "correlation_id": "uuid",
  "payload": {
    "execution_id": "uuid",
    "binding_epoch": 1,
    "release_status": "released",
    "process_exit_observation_id": "uuid",
    "runner_id": "uuid"
  }
}
~~~

Infrastructure status values should describe facts such as accepted, delivering, running, releasing, released, failed and uncertain. Do not reuse AI-PM Task statuses such as completed, blocked or in_progress.

AI-PM may use infrastructure facts as inputs to its own business policy, but SEM cannot choose the business consequence.

## 9. Harness MCP authentication

Installing AI-PM MCP is necessary but not sufficient. Before implementation, define:
- How the Runner/Harness receives a project-scoped MCP identity.
- Whether the identity represents a human principal, service principal or delegated execution principal.
- How AI-PM binds the identity to the intended project and permissions.
- Token lifetime, renewal, revocation and audit behavior.
- How MCP credentials are injected without exposing them to SEM logs or unrelated Harness processes.
- Negative tests proving cross-project and unauthorized Task mutations are denied.

SEM service JWTs and Runner WSS credentials must never be reused as Harness MCP business identities.



## 9.1 AI-PM MCP business transition requirements

Harness business status changes must use AI-PM-owned, guarded MCP operations. Do not add an unrestricted arbitrary Task status setter. AI-PM validates every requested transition against its Task state machine and records the business audit.

The existing ai-pm source baseline has specialized transitions coupled to the old Runner Claim/Lease path: pm_report_progress currently combines business progress/stage with Lease renewal and advances Task to running on the first started stage; pm_submit_result advances Task to submitted; pm_get_run_context returns the fuller execution contract but requires the old claim token; pm_get_task_context is currently a narrower snapshot. The replacement Harness MCP contract must expose complete authorized Task/execution context without requiring Runner Claim, preserve typed business progress/result transitions, and separate all process heartbeat/resource liveness from MCP business operations.

## 9.2 Delegated Harness identity and two fencing domains

The current AI-PM MCP transport permission gate is not sufficient for this model: PM_MCP_TASK_UPDATE is currently unassigned in the permission map, while pm_report_progress and pm_submit_result mutate business execution/Task state but are not mapped to a dedicated task-update permission. pm_get_task_context currently authorizes project membership and accepts a Task reference; it is not bound to one execution attempt. The new delegated grant must be enforced at the AI-PM application-service boundary for each exact Task/Run/execution attempt and each operation. Formal review/approval endpoints retain their human-principal gate and must reject delegated Harness identities.


The current ai-pm MCP identity implementation is human-key based: a user API Key resolves to a human principal; the current cpk_ device credential resolves to the device owner's human principal; the MCP caller context requires HumanActor; service JWTs are rejected from business endpoints. The existing identity governance decision explicitly says V1 does not issue independent Agent credentials. This cannot, without redesign, prove that one Harness process is authorized for exactly one Task/Run attempt.

The replacement must define a Delegated Execution Identity / grant. This is a proposed concept, not a frozen schema. It must be issued/authorized by AI-PM, scoped to one tenant/project/task/attempt and an allow-list of MCP business operations, short-lived and revocable. It must not impersonate the initiating human and must not authorize approval, formal acceptance, project administration, unrelated Task access or arbitrary Task status mutation. Audit must preserve the delegating human/Platform actor separately from the Harness executor and Runner/device identity.

Do not put a reusable human API Key in the prompt or reuse SEM service JWT / Runner WSS credentials as MCP credentials. Prefer a one-time Runner-bound bootstrap exchange with AI-PM; if a bootstrap ticket traverses SEM, cryptographically bind it to the intended Runner so SEM and other Runners cannot redeem it. A local Runner credential broker may inject the short-lived MCP token into Harness requests. The exact exchange, token format, key binding and revocation design remain open.

Two independent fencing domains are mandatory:
- AI-PM authorization_generation fences every delegated Harness MCP operation for the business attempt.
- SEM binding_epoch/binding_epoch fences delivery/release operations for the current Runner binding.

Neither value substitutes for the other. A new business retry invalidates the prior AI-PM grant. A Runner rebind must fence the old Harness business grant before another Harness can mutate the Task. Revoking MCP access alone does not prove an old process cannot mutate Git remotes or external systems.

If a Runner disconnects and process exit cannot be positively established, keep the execution infrastructure_uncertain, quarantine the old binding and do not launch a competing Harness for the same attempt. Reassignment requires positive process-exit evidence or a separately designed isolation/fencing procedure.

## 9.3 Business submission is not Task completion

The current AI-PM Task lifecycle distinguishes Running→Submitted (delivery manifest required), Submitted→Reviewing, and Reviewing→Completed (acceptance evidence required). The special Ready→Completed path is for manual tasks and requires a human principal and reason. Harness may submit delivery and report progress through typed MCP operations; it must not self-accept or use a generic arbitrary status setter. AI-PM decides final completion under its existing guarded review/acceptance rules.

When an AI-PM business decision makes the execution no longer necessary, the business transition and Platform Outbox release intent should be committed atomically. SEM release remains an infrastructure lifecycle, independent of Task completion.



## 9.4 Remote Runner Git evidence boundary

The AI-PM Platform cannot assume it can inspect a worktree located on an independent Runner host. The current AI-PM D4 remote verifier supports a remote-carrier mode, but that mode currently verifies a declared commit as a remote branch head and checks baseline ancestry; it does not prove the Runner-local worktree HEAD and currently echoes the declared changed-file count rather than independently recalculating it.

Before implementation, define the remote execution evidence contract. At minimum, require the Runner/Harness to push to a unique execution branch/ref before submitting; AI-PM must bind the submitted SHA to that ref and verify the remote ref and ancestry. Changed-file facts must be calculated from the remote Git object graph, or explicitly labeled as an unverified declaration. A commit not pushed or not fetchable must not be treated as verified delivery. If exact local worktree HEAD proof is required, define a separate Runner-signed attestation and trust model; a Harness JSON claim is not independent evidence.

The remote evidence mode must be explicit execution metadata, not inferred from a legacy lease_owner string or credential prefix. SEM transports any opaque evidence reference without interpreting Git or Task semantics.



## 9.5 Task, AI-PM Run and SEM Execution are three lifecycles

Do not collapse these into one status:

| Lifecycle | Owner | Example facts/states |
|---|---|---|
| Task | AI-PM | running → submitted → reviewing → completed; may also be blocked/cancelled/failed under guarded business rules |
| Run / business attempt | AI-PM | one authorized attempt, its lease/authorization generation, delivery association and Platform-decided outcome |
| SEM Execution | SEM infrastructure | queued → assigned → delivering/starting → running → releasing → released, or failed/uncertain |

Harness MCP may cause guarded Task transitions such as first start (running) and validated delivery submission (submitted). It does not set completed. Review/acceptance decides Task completion under AI-PM rules. Runner process start/exit is reported as infrastructure evidence through SEM; AI-PM correlates that evidence to its Run and decides the Run outcome. A process exit code alone is not a business success or Task completion.

SEM release is triggered when AI-PM decides that the corresponding Run/attempt no longer needs a runtime. This can happen after delivery submission while the Task is still submitted/reviewing, after cancellation, or while waiting for a human decision. Therefore release must not be coupled only to Task=completed. The Platform Outbox event should identify the exact AI-PM attempt and opaque SEM execution, while SEM sees no Task status semantics.

## 10. Failure and recovery semantics

- SEM accepts request but cannot find a Runner: remain queued/rejected according to infrastructure policy; no business state is changed.
- Runner accepts delivery but Harness fails to start: report infrastructure failure; AI-PM decides the business consequence.
- Harness exits before Task completion: report exact process exit; AI-PM decides whether the Task is retryable or requires intervention.
- Task completes before Harness exits: AI-PM sends release; Task remains completed even if cleanup is still pending.
- Runner disconnects: mark infrastructure uncertain; do not infer process death from heartbeat loss.
- SEM restarts: recover durable inbox/delivery/release records and reconcile Runner binding. Never reconstruct Task state from SEM persistence.
- Unknown message outcome: retry with the same message/request/delivery identity; do not generate a new execution attempt blindly.

## 11. Open review questions

1. Inline prompt body vs short-lived content reference: size limits, confidentiality, retention and replay.
2. Runner authorization: which AI-PM-issued scope/allow-list proves a Runner may receive a given execution request without exposing Task semantics to SEM?
3. Harness MCP principal and credential provisioning model.
4. Runner selection policy when multiple Runners satisfy infrastructure constraints.
5. Execution epoch allocation and persistence across SEM restart/reconnect.
6. Graceful stop deadline, forced termination policy and handling of a Runner that never reconnects.
7. Whether infrastructure reporting is pushed to an AI-PM endpoint, returned synchronously, or both.
8. Retention policy for prompt bodies, process observations and infrastructure logs.

The OpenAPI and JSON Schema files are Draft validation artifacts. They do not resolve the open questions above or authorize implementation.

No implementation or migration is authorized until these questions are reviewed and the bilateral contract is approved.


## 12. Contract clarifications and companion design

The detailed companion contract defines the proposed two-stage Runner-bound credential bootstrap, AI-PM grant claims and per-call authorization, the AI-PM Run ↔ SEM Execution correlation, durable inbox/outbox and event ordering, Runner process identity evidence, disconnect quarantine, release/start races, resource reservation and remote Git delivery evidence.

The canonical SEM fencing identifier in this draft is binding_epoch. It is allocated when a Runner binding is established, not when SEM first accepts the request. Therefore the synchronous acceptance response contains no epoch. AI-PM learns the epoch from the authenticated execution.binding_established event (or an explicit reconciliation response). Release must use the expected binding_epoch; if AI-PM does not know the current epoch, it must reconcile by execution_id before issuing a fenced release.

The credential bootstrap described in the companion contract is a design proposal, not an approved implementation choice. It requires review of the Runner registration trust chain and the cryptographic binding of the one-time ticket to the selected Runner key. No reusable human credential or MCP bearer token may be carried in the prompt body.


## 13. Concrete infrastructure event and bootstrap envelopes (draft)

The following examples make the direction and minimum fields explicit. They are draft wire shapes; final OpenAPI/JSON Schema, signing details and retention limits remain review gates.

### 13.1 SEM → AI-PM: binding established

This event is emitted only after SEM has selected a Runner and durably reserved capacity. The binding_epoch is assigned here, not at request acceptance.

~~~json
{
  "event_id": "uuid",
  "event_type": "execution.binding_established",
  "schema_version": 1,
  "occurred_at": "RFC3339 UTC",
  "execution_id": "uuid",
  "execution_event_sequence": 1,
  "payload": {
    "execution_id": "uuid",
    "binding_epoch": 1,
    "runner_id": "uuid",
    "runner_key_thumbprint": "sha256:...",
    "reservation_id": "uuid",
    "supervision_mode": "unattended"
  }
}
~~~

AI-PM authenticates SEM, validates the event and its Runner binding evidence, and stores the opaque binding_epoch with its Run↔execution mapping. runner_key_thumbprint is infrastructure identity metadata, not business authorization.

### 13.2 AI-PM → SEM → Runner: opaque credential bootstrap ticket

After validating the binding, AI-PM may send a separate message:

~~~json
{
  "message_id": "uuid",
  "message_type": "execution.credential_bootstrap",
  "schema_version": 1,
  "request_id": "uuid",
  "payload": {
    "execution_id": "uuid",
    "expected_binding_epoch": 1,
    "runner_id": "uuid",
    "runner_key_thumbprint": "sha256:...",
    "ticket_content_type": "application/octet-stream",
    "ticket": "<opaque one-time ticket bytes>"
  }
}
~~~

SEM routes this opaque ticket only to the exact current Runner binding and does not inspect, redeem, log or transform it. Runner Supervisor's local credential broker redeems it directly with AI-PM using the bound Runner key. The resulting MCP credential is never returned to SEM. A stale binding, wrong Runner or mismatched key must be rejected by both SEM routing and AI-PM redemption validation.

### 13.3 Runner → SEM: durable delivery receipt

~~~json
{
  "message_id": "uuid",
  "message_type": "execution.delivery_received",
  "schema_version": 1,
  "journal_id": "uuid",
  "event_sequence": 1,
  "occurred_at": "RFC3339 UTC",
  "payload": {
    "execution_id": "uuid",
    "binding_epoch": 1,
    "runner_id": "uuid",
    "delivery_id": "uuid",
    "receipt": "durably_recorded"
  }
}
~~~

This receipt proves only that Runner Supervisor durably recorded the delivery operation. It does not prove that Harness started or that business work began.

### 13.4 Runner → SEM: Harness process started

~~~json
{
  "message_id": "uuid",
  "message_type": "harness.started",
  "schema_version": 1,
  "journal_id": "uuid",
  "event_sequence": 2,
  "occurred_at": "RFC3339 UTC",
  "payload": {
    "execution_id": "uuid",
    "binding_epoch": 1,
    "launch_id": "uuid",
    "containment_id": "opaque-containment-id",
    "runner_id": "uuid",
    "supervisor_instance_id": "uuid",
    "process_identity": {
      "os_boot_id": "opaque-boot-id",
      "pid": 1234,
      "process_start_identity": "opaque-os-start-token",
      "cgroup_path": "/sys/fs/cgroup/sem/...",
      "systemd_invocation_id": "opaque-systemd-invocation-id"
    },
    "harness_profile": "codex"
  }
}
~~~

PID alone is not a stable process identity. The process start identity and OS boot identity are required to detect PID reuse and Runner reboot.

### 13.5 Runner → SEM: exact process exit observation

~~~json
{
  "message_id": "uuid",
  "message_type": "harness.process_exited",
  "schema_version": 1,
  "journal_id": "uuid",
  "event_sequence": 3,
  "occurred_at": "RFC3339 UTC",
  "payload": {
    "execution_id": "uuid",
    "binding_epoch": 1,
    "runner_id": "uuid",
    "process_identity": {
      "os_boot_id": "opaque-boot-id",
      "pid": 1234,
      "process_start_identity": "opaque-os-start-token",
      "launch_id": "uuid",
    "containment_id": "opaque-containment-id",
    "boot_id": "opaque-boot-id",
    "systemd_invocation_id": "opaque-systemd-invocation-id",
    "cgroup_path": "/sys/fs/cgroup/sem/...",
    "cgroup_populated": 0,
    "evidence_id": "uuid",
    "exit_status": { "kind": "code", "code": 0 },
    "supervisor_instance_id": "uuid"
  }
}
~~~

The systemd invocation and cgroup v2 evidence must be produced by the trusted host-side Runner Supervisor. A Harness self-report is not process-exit evidence. The exit status is infrastructure evidence and never means Task completion.

### 13.6 Runner → SEM: resource telemetry

~~~json
{
  "message_id": "uuid",
  "message_type": "runner.resources.report",
  "schema_version": 1,
  "occurred_at": "RFC3339 UTC",
  "payload": {
    "runner_id": "uuid",
    "runner_boot_id": "opaque-boot-id",
    "cpu": {"capacity_cores": 8, "available_cores": 5.5},
    "memory": {"capacity_bytes": 34359738368, "available_bytes": 25769803776},
    "workspace_volume": {"capacity_bytes": 536870912000, "available_bytes": 402653184000},
    "active_process_count": 2
  }
}
~~~

Telemetry includes observation time and Runner boot identity. SEM applies a configured freshness window and accounts for its own active reservations before dispatch. Stale or missing telemetry is not treated as unlimited capacity.

### 13.7 AI-PM → SEM: fenced release request

~~~json
{
  "message_id": "uuid",
  "message_type": "execution.release_requested",
  "schema_version": 1,
  "request_id": "uuid",
  "payload": {
    "execution_id": "uuid",
    "release_id": "uuid",
    "expected_binding": { "state": "bound", "binding_epoch": 1 },
    "stop_policy": {
      "mode": "graceful_then_force",
      "grace_period_seconds": 30
    }
  }
}
~~~

If AI-PM does not know the current binding_epoch, it must first query/reconcile the execution by execution_id, or send the explicit unbound form (`"expected_binding": { "state": "unbound" }`) and follow §7.1's sequencer outcomes. SEM rejects a stale expected_binding_epoch and never applies it to a newer binding. Release arriving while launch is in progress must be persisted as a stop fence so the Supervisor cannot launch a late process after the release.

### 13.8 SEM event delivery acknowledgement and per-execution cursor

The SEM callback is at-least-once and carries one event per request in the current Draft. AI-PM must commit its durable Inbox row and permitted infrastructure observation in one transaction before returning a success acknowledgement.

A successful acknowledgement contains:
- `event_id`: exact event acknowledged;
- `execution_id`: event stream identity;
- `execution_event_sequence`: sequence of this SEM→AI-PM event within the exact execution;
- `contiguous_through_sequence`: highest contiguous sequence durably committed by AI-PM for this execution;
- `disposition`: `accepted` or `duplicate`;
- `acknowledged_at`: receiver timestamp.

If a later sequence arrives before the missing predecessor, AI-PM returns a structured `409 EVENT_SEQUENCE_GAP` with `execution_id` and `expected_sequence`; it does not advance the contiguous cursor. SEM retains and retries/replays the missing event. A duplicate event_id with the same canonical body returns `duplicate`; the same event_id with a different body returns `409 IDEMPOTENCY_CONFLICT`. A duplicate older event may return the current contiguous cursor, but must not change it.

The success ACK is never returned before Inbox + permitted Run-observation commit. The generic AI-PM `POST /api/v1/events` endpoint is not this callback receiver; a dedicated AI-PM route and Inbox contract remain to be designed and approved bilaterally.

### 13.9 Ordering and duplicate handling

- Every sender supplies a unique message_id; every logical operation also has its stable request_id, delivery_id or release_id.
- Runner observations carry a monotonically increasing `event_sequence` within the durable Runner event stream identified by `runner_id + journal_id`; SEM validates `execution_id + binding_epoch` independently and persists the last contiguous stream sequence.
- A duplicate message with the same identity and canonical payload returns the original acknowledgement. Reuse with a different payload is a conflict.
- A gap in `execution_event_sequence` within one execution, stale epoch, unknown process identity or out-of-order state-changing observation triggers reconciliation; it is not silently accepted as current state.
- SEM→AI-PM events are at-least-once. Each durable SEM→AI-PM event carries `execution_id` and `execution_event_sequence`, monotonic within that execution's SEM event stream. AI-PM deduplicates by `event_id` and stores the per-execution cursor. This is distinct from Runner→SEM `journal_id + event_sequence`, which is scoped by `runner_id + journal_id` and survives WSS reconnect. AI-PM applies infrastructure facts through its own Run policy and must not let SEM directly change Task status.

### 13.10 SEM → AI-PM: unbound release applied (sixth event)

Emitted exactly once per execution when an unbound release wins the dispatch/release sequencer (§7.1 outcome A). It is replayed at-least-once like every other durable SEM event and deduplicated by AI-PM through the standard Inbox identity.

~~~json
{
  "event_id": "uuid",
  "event_type": "execution.unbound_release_applied",
  "schema_version": 1,
  "occurred_at": "RFC3339 UTC",
  "execution_id": "uuid",
  "execution_event_sequence": 13,
  "payload": {
    "release_id": "uuid",
    "dispatch_fence_id": "uuid",
    "disposition": "released_unbound",
    "applied_at": "RFC3339 UTC"
  }
}
~~~

The payload intentionally contains no Runner identity, binding_epoch, stop_fence_id or process-exit fields; the strict schema branch rejects any such field. It participates in the same `execution_event_sequence` contiguous-cursor and ACK contract as the other five events (§13.8). Relation to the existing five events: it replaces no event, it never accompanies a Runner stop, and once AI-PM records its tombstone, later `execution.binding_established` events for the same execution_id are integrity contradictions and must be rejected.


## 6.1 SEM event callback acknowledgement

The callback success acknowledgement echoes the exact event sequence field name from the event envelope. The field is `execution_event_sequence`; the ambiguous alias `event_sequence` is not accepted. This value is scoped to one SEM execution event stream and is distinct from Runner journal `event_sequence` and WSS `message_sequence`.

```json
{
  "event_id": "uuid",
  "execution_id": "uuid",
  "execution_event_sequence": 12,
  "contiguous_through_sequence": 12,
  "disposition": "accepted",
  "acknowledged_at": "RFC3339 UTC"
}
```

A duplicate delivery with the same event_id and identical canonical body returns `disposition: duplicate` and echoes the same `execution_event_sequence`. The ACK is returned only after the AI-PM Inbox record, append-only Run observation and per-attempt cursor have committed atomically. A sequence gap or identity conflict is an error response, never a success ACK.

## 6.2 Identity and evidence validation requirements

The event schema requires `runner_key_version`, `boot_id` and `supervisor_instance_id` on delivery, process, release and uncertainty observations. The receiver must compare these fields to the currently known binding for the execution; schema validity alone is not authorization to apply an observation.

For `harness.process_observed` with `observation=exited`, the payload must contain exact process identity and exit evidence with exactly one of `exit_code` or `exit_signal`. For `exit_status_unknown`, evidence may prove the containment is empty while the numeric status remains unknown. A `execution.release_status` event may report `requested`, `release_uncertain` or `stale_rejected` before a Runner stop fence is durably known; those states do not require `stop_fence_id`. Once the fence is committed, `stop_fenced`, `termination_requested`, `process_exited`, `released` and `cleanup_failed` MUST carry the exact `stop_fence_id` referencing the immutable Runner journal record. `process_exited` MUST additionally include `process_exit_evidence_id` referring to the exact accepted process-exit evidence. These references must resolve to the same execution, runner key version, boot, supervisor instance, binding epoch, launch and containment identity in the SEM durable ledger.


## 7.1 Unbound release and dispatch-fence contract (P0-07)

The bound-only release request is insufficient for an accepted execution that has not yet received a Runner binding. Do not invent binding_epoch=0, a Runner identity, a stop_fence_id or process-exit evidence.

### Request shape proposal

~~~json
{
  "execution_id": "uuid",
  "release_id": "uuid",
  "expected_binding": { "state": "unbound" },
  "stop_policy": {
    "mode": "graceful_then_force",
    "grace_period_seconds": 30
  }
}
~~~

The bound form is:

~~~json
{
  "execution_id": "uuid",
  "release_id": "uuid",
  "expected_binding": { "state": "bound", "binding_epoch": 7 },
  "stop_policy": {
    "mode": "graceful_then_force",
    "grace_period_seconds": 30
  }
}
~~~

The schema must use a strict oneOf: unbound forbids binding_epoch; bound requires integer binding_epoch >= 1. No optional/ambiguous combination is accepted.

### Linearization and outcomes

Dispatch and release MUST use one SEM-owned per-execution command sequencer/transactional state row and the same serialization boundary:

1. SEM accepts the execution and creates its dispatch-eligible state.
2. A Runner binding transaction and an unbound-release transaction contend on the same execution state lock / sequencer.
3. If unbound release wins, SEM atomically changes dispatch state to released_unbound and persists an immutable dispatch-fence record before returning success. Every later dispatch/bind attempt must fail closed against that fence. SEM emits a new Platform event execution.unbound_release_applied with execution_id, event_id/sequence, release_id, dispatch_fence_id and applied_at. It contains no Runner, binding_epoch, stop_fence_id or process-exit evidence.
4. If dispatch wins, SEM returns authenticated 409 BINDING_ALREADY_ESTABLISHED with the actual binding_epoch and exact binding identity. It emits no unbound-release event. AI-PM reconciles and submits the normal bound release using that epoch.
5. If the result is ambiguous, SEM returns/retains an uncertain result and does not claim either outcome. AI-PM retries the exact release_id/request body; SEM reconciles the sequencer's durable row and returns the same terminal disposition.
6. Duplicate release_id + identical canonical body returns the original outcome. Same release_id with changed expected_binding/stop policy is IDEMPOTENCY_CONFLICT.
7. A release-wins tombstone is permanent for that execution_id. No later Runner assignment, requeue, or higher binding_epoch may resurrect it. A genuinely new AI-PM attempt uses a new execution_id.

The dispatch-fence record is SEM durable state, not Runner stop-fence evidence. Its existence proves only that SEM will not dispatch this execution; it does not prove any Harness process exited.

### Event shape proposal

~~~json
{
  "event_id": "uuid",
  "event_type": "execution.unbound_release_applied",
  "schema_version": 1,
  "occurred_at": "RFC3339 UTC",
  "execution_id": "uuid",
  "execution_event_sequence": 13,
  "payload": {
    "release_id": "uuid",
    "dispatch_fence_id": "uuid",
    "disposition": "released_unbound",
    "applied_at": "RFC3339 UTC"
  }
}
~~~

This is a sixth SEM→AI-PM event type, intentionally distinct from execution.release_status. It cannot accidentally imply Runner stop or process exit. The dedicated strict JSON Schema branch (`$defs/UnboundReleaseAppliedEvent` / `$defs/UnboundReleaseAppliedPayload`), the OpenAPI release/acknowledgement definitions, positive and negative callback fixtures, and the D04 acceptance cases D04-H89–H100 plus D04-H48–H51 are now machine-readable artifacts in this repository and are enforced by CI. The schema, not this prose, is the normative shape; the prose does not silently extend it further.

Machine-readable P0-07 baseline (this branch):
- `json-schema/platform-sem-v1.schema.yaml`: tagged `expected_binding` oneOf on `ExecutionReleaseRequest`; sixth event branch; `release_disposition` on `ReleaseAcceptanceEnvelope`; optional `binding_epoch` on `ProtocolErrorEnvelope.error` for `BINDING_ALREADY_ESTABLISHED`.
- `openapi/platform-sem-v1-draft.yaml`: identical tagged request/acceptance/error shapes; `released_unbound` snapshot state.
- `tests/protocol/fixtures/payload-fixtures-v1.json`: valid bound and unbound release requests and one valid sixth event; validator asserts the tombstone never carries Runner/binding/stop-fence/process-exit fields and rejects direction confusion between WSS frames and SEM callback events.

P0-07 runtime remains open: the SEM dispatch/release sequencer service, its persistence and failure-injection tests do not exist yet. Contract artifacts are not runtime evidence.

### Required D04 cases

- D04-H94: unbound release wins; persist dispatch fence and emit released_unbound event with no Runner/process fields.
- D04-H95: dispatch wins; return BINDING_ALREADY_ESTABLISHED with actual epoch/identity; no unbound event.
- D04-H96: release wins, then delayed dispatch/retry/requeue arrives; reject permanently.
- D04-H97: ambiguous response after durable release fence; exact retry returns same event/disposition.
- D04-H98: same release_id with changed expected_binding or stop policy; IDEMPOTENCY_CONFLICT.
- D04-H99: duplicate unbound-release event callback; AI-PM ACKs exact duplicate without changing projection.
- D04-H100: a new AI-PM attempt with a new execution_id is independent; old tombstone cannot block it.

P0-07 contract artifacts are complete at Draft level; P0-07 runtime closure remains OPEN until the SEM dispatch/release sequencer implementation and its failure-injection tests exist. Contract completion is not runtime completion.

## 7.2 Binding projection event contract (P0-06)

AI-PM persists one consumer-side projection row per execution attempt (single table `delivery.task_run_sem_execution`; no duplicate binding table and no dual-write projection — see the AI-PM PR #9 documents [SEM Callback Inbox — Exact DDL and Concurrency Design](https://github.com/luqizheng/ai-pm/blob/docs/sem-02e-architecture-convergence/docs/architecture/server-execution-management/sem-callback-inbox-ddl-and-concurrency-design.md) §13 and the bilateral review addendum). The projection records dispatch_state, the current binding tuple, binding_epoch, runner identity, host boot identity, launch/containment identity, release state and uncertainty/quarantine state. SEM remains the sole authority for epoch allocation, Runner selection and infrastructure facts; the AI-PM projection is never dispatch authorization and never mutates Task/Run business state.

The ten binding/event handling cases below are the normative consumer contract for this protocol's events. SEM guarantees the evidence column; AI-PM must implement exactly the handling column.

| # | Case | SEM-side guarantee (authoritative evidence) | Required AI-PM handling |
|---|---|---|---|
| 1 | First binding | `execution.binding_established` with `binding_epoch = 1`, full Runner tuple (runner_id, runner_key_version, boot_id, supervisor_instance_id, delivery_id), no prior binding exists | First-bind algorithm: insert the projection atomically with the Inbox row, Run observation and cursor CAS; require epoch=1 and a complete Runner tuple; no historical binding is compared |
| 2 | Exact duplicate binding | Same event_id + identical canonical envelope replayed at-least-once | Resolve via Inbox event identity/envelope hash/sequence BEFORE projection mutation; return duplicate ACK without rewriting projection or `updated_at` |
| 3 | Same epoch, different tuple | SEM never reuses an epoch with a different Runner tuple; such a tuple indicates forgery/integrity failure | Reject as conflict; quarantine; never overwrite the projection; cursor does not advance |
| 4 | Lower-epoch late event | Old-epoch events may replay after a rebind; SEM marks them stale | Reject as stale; never regress the projection; append-only audit history only |
| 5 | Higher-epoch rebind | SEM only allocates epoch N+1 after positively completed prior release (exact stop-fence/no-start proof or exact process-exit evidence) OR an explicit authenticated host-isolation disposition; it never rebinds while the old process may live | Accept only when the prior projection state is `released` with exact release evidence or `host_isolated` with the exact SEM disposition reference; old history stays append-only; strictly greater epoch required |
| 6 | Rebind after normal release | Released state carries `stop_fence_id` (positive no-start proof) or `process_exit_evidence_id` (exact exit evidence) referencing immutable journal records | Same as case 5 bound-release branch; the tombstone/fence references must resolve to the same execution, epoch, runner key version, boot and supervisor instance |
| 7 | Uncertain old binding | `execution.infrastructure_uncertain` always carries `reservation_retained=true`; heartbeat loss/WSS disconnect/host unreachable are NOT termination evidence | Reject any epoch change while prior state is `uncertain`; retain quarantine and reservation; never treat SEM self-asserted host state as AI-PM rebind authorization |
| 8 | Runner host permanent loss | D-03 disposition is a separately authorized operator action (`runner.quarantine.resolve` audit record), never an automatic event; permanent loss is NOT process-exit evidence | Set `host_isolated` (or retain quarantine) only from the explicit SEM-authenticated disposition reference; the old binding stays fenced; old host capacity is never re-eligible |
| 9 | Host physically isolated | Same D-03 path: exact affected identities + operator attestation + timestamp + reason are required | Same as case 8; physical isolation permits rebind ONLY via case 5's explicit disposition branch, and never fabricates process-exit evidence |
| 10 | Inspection inconclusive | SEM keeps `infrastructure_uncertain` with quarantine and retained reservation | Reject rebind; keep `uncertain`; resolution only through §3.4 reconciliation edges backed by named-authority evidence |

Additional normative points:

- SEM's own claim about host state (heartbeat, WSS session, resource telemetry) is never AI-PM dispatch or rebind authorization. Only the exact evidence classes above cross the authority boundary.
- The first `execution.binding_established` has no historical binding; case 1's first-bind algorithm replaces the generic compare-against-current-binding rule.
- Release and unbound-release handling (tombstone protection: a recorded `released_unbound` projection rejects every later binding event for the same execution_id regardless of epoch) is specified in §7.1 and the AI-PM DDL design §12.
- The required lock order for every AI-PM callback transaction is: Run row → execution projection → Inbox event → Run observation → cursor CAS, committed atomically or not at all.
- Concurrent race coverage required on the AI-PM side: concurrent first-bind, two epochs in flight, concurrent duplicate commits, old event after new, release-vs-binding, host-isolation-vs-rebind, and mid-transaction failure replay (INBOX-50+ and BIND/UNBOUND cases in the AI-PM PR #9 DDL design).
