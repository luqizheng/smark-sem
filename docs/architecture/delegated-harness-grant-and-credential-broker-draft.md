# Delegated Harness Grant and Credential Broker — Design Draft

- Status: **Proposed security contract / review required**.
- Decision ID: SEM-D-02.
- Authority: AI-PM issues and enforces business grants; SEM transports opaque bootstrap material; Runner Supervisor's local broker holds Runner private key and MCP access token.
- This is a design proposal, not an approved API, schema or migration.

## 1. Security objective

A Harness execution must access AI-PM MCP as a distinct delegated execution identity, not as the human who authorized the work and not as a reusable device identity.

The grant must:
- authorize exactly one tenant/project/Task/AI-PM Run attempt/SEM execution tuple;
- be bound to one enrolled Runner key version;
- be limited to an explicit operation allow-list;
- expire and be revocable immediately at AI-PM;
- be invalidated by authorization_generation changes;
- preserve delegating human, Harness executor and Runner as distinct audit identities;
- never be visible to SEM, prompt history, ordinary Harness arguments or workspace files.

## 2. Proposed identity types

| Identity | Meaning | Can perform business MCP calls? |
|---|---|---|
| Human principal | Human who authorized/created the attempt | Only under normal human permissions |
| Delegating actor | Audit attribution for the authorization decision | No independent bearer credential implied |
| Harness executor | Named executor profile/process (e.g. codex/claude) | Only through its delegated grant |
| Runner identity | Cryptographically enrolled host installation | No business authority by itself |
| SEM service identity | Infrastructure transport service | No business MCP authority |
| Delegated execution grant | AI-PM authorization for one exact attempt | Yes, only within exact scope and allow-list |

Do not map a delegated grant to `HumanActor`. Introduce a distinct typed caller context, e.g. `DelegatedExecutionActor`, with no human-only methods. Do not let a grant construct an AuditActor that falsely attributes every Harness action to the delegating human.

## 3. Grant record

The AI-PM persistence model should represent at least:

| Field | Requirement |
|---|---|
| grant_id | Immutable unique ID |
| tenant_id / project_id / task_id | Exact business resource scope |
| run_id / attempt_id | Exact AI-PM attempt scope |
| execution_id | Exact SEM execution correlation |
| authorization_generation | Current AI-PM fencing generation |
| runner_id / runner_key_version / key_thumbprint | Exact enrolled Runner identity |
| delegating_actor_id | Human/authorized Platform actor that approved delegation |
| harness_executor_id / profile | Distinct Harness executor attribution |
| operations | Typed allow-list; no wildcard |
| issued_at / not_before / expires_at | Bounded validity |
| revoked_at / revoke_reason | Immediate revocation |
| status | pending / active / revoked / expired / consumed where appropriate |
| created_by_request_id | Idempotent authorization request trace |

The grant must be persisted in the same AI-PM transaction that authorizes the attempt and writes the Outbox execution.requested intent. A grant must never be created solely because SEM reports that a Runner is available.

### 3.1 Operation allow-list

Initial candidate operations (final operation names must match actual MCP tool names and schemas):
- `task.context.read`: read only the exact authorized Task and its permitted execution context;
- `task.progress.report`: append progress for the exact authorized attempt;
- `task.delivery.submit`: submit delivery evidence for the exact authorized attempt.

Explicitly excluded:
- arbitrary Task status update or Task completion;
- formal review, approval, acceptance or rejection;
- manual-task completion;
- project/member/repository administration;
- cross-Task/project/tenant reads or writes;
- broad search/discovery APIs that can enumerate unrelated resources;
- unrestricted Git credential issuance or external side-effect administration.

The operation list is checked for every call at the AI-PM application-service boundary. Transport middleware may authenticate the token but cannot be the only authorization layer.

## 4. Bootstrap ticket

### 4.1 Issuance

After AI-PM accepts a verified SEM `execution.binding_established` event, AI-PM creates:
- a grant bound to the exact business attempt and Runner key version;
- a cryptographically random, one-time bootstrap ticket (recommended 256-bit entropy);
- a stored hash of the ticket, never the plaintext;
- an expiry (recommended 60 seconds from issuance);
- binding to runner_id, key_version/thumbprint, execution_id and binding_epoch.

The plaintext ticket is sent to SEM in an opaque, encrypted transport envelope. SEM may persist ciphertext for reliable delivery but must not be able to decrypt, redeem or log the ticket. If transport-level encryption is used, the envelope must be encrypted to the Runner key or another independently trusted recipient key; TLS between AI-PM and SEM alone does not prevent a compromised SEM from reading the body.

### 4.2 Redemption proof

Runner Credential Broker redeems directly with AI-PM over TLS:
- sends the ticket and the exact tuple (runner_id, key_version, execution_id, binding_epoch);
- includes a fresh server challenge/nonce or obtains one from AI-PM;
- signs a canonical, domain-separated redemption message using the enrolled Runner private key;
- includes issued_at and a unique request nonce.

AI-PM atomically verifies:
1. ticket hash exists, is unexpired and unused;
2. ticket's execution_id and binding_epoch match the current binding;
3. ticket's runner_id and key version match AI-PM's own enrolled trust record;
4. Runner signature proves possession of that exact private key;
5. grant remains active and authorization_generation is current;
6. grant scope and operation allow-list remain valid.

AI-PM atomically marks the ticket consumed and issues the first short-lived MCP access token. Replayed, expired, wrong-runner, wrong-key, wrong-epoch, revoked or stale-generation redemption fails.

A ticket is not a bearer credential by itself. SEM cannot redeem it without the Runner private key.

## 5. MCP access token and local credential broker

### 5.1 Token profile

Recommended first profile: opaque 256-bit random token with a distinct prefix such as `hgr_`; store only its hash in AI-PM. Suggested access-token lifetime: 5 minutes. The exact prefix and lifetime are implementation parameters to freeze in the API contract.

Why opaque + per-request lookup:
- revocation and authorization_generation changes take effect on the next MCP request;
- no JWT cache window or stale signature-only acceptance;
- the token contains no readable Task/project claims if leaked.

Every MCP request validates token hash, active grant, expiry, current authorization_generation, exact Runner key status and operation scope. No authorization cache may outlive the defined revocation SLA; recommended initial policy is no positive cache.

### 5.2 Local broker

Runner Supervisor starts a per-execution Credential Broker:
- owns the Runner private-key handle and delegated token;
- redeems bootstrap ticket directly with AI-PM;
- renews short-lived access tokens while the grant remains active, using a fresh Runner-key proof and grant_id (no long-lived refresh bearer token);
- exposes a local authenticated MCP proxy/stdio bridge to the Harness;
- injects the bearer token only on broker→AI-PM requests;
- does not expose the token through prompt, environment variables, argv, workspace files or ordinary logs.

The Harness connects to the broker endpoint as its MCP server. The broker binds access to the exact local process/containment unit where the OS supports it. If the Harness can read the token from its own process memory, the design has failed the isolation objective; prefer a proxy that keeps the bearer token in the broker process.

The final transport mode (stdio bridge vs loopback HTTP) must be selected against the supported Codex/Claude Harness MCP client capabilities before implementation.

### 5.3 Token renewal

- Broker renewal is authenticated by Runner key proof and grant_id, not by a long-lived refresh token.
- AI-PM checks the grant and authorization_generation on each renewal.
- Renewal returns a new short-lived token and revokes/replaces the prior token atomically or allows a very short overlap for in-flight requests.
- Renewal stops immediately on grant revocation, generation change, Runner key revocation, attempt termination or expiry.
- Broker loss must not cause Harness to fall back to a human credential.

## 6. AI-PM MCP enforcement architecture

Separate authentication from business authorization:

1. API auth recognizes the delegated token prefix and resolves the token hash to a typed delegated identity.
2. The MCP caller context contains grant_id, execution_id, Runner identity and Harness executor; it does not contain HumanActor.
3. Each tool maps to a typed operation identifier.
4. The application service loads/validates current grant state and generation, then validates the exact tenant/project/task/run/attempt tuple.
5. The tool's target resource is derived from or checked against the grant; caller-supplied IDs are selectors, not authority.
6. Reads are scoped as strictly as writes.
7. The business operation, result and audit are committed according to the relevant AI-PM transaction contract.

Do not rely solely on a route-level permission such as PM_MCP_READ. A tool that changes progress or submits delivery is a write operation and must require its own grant capability.

Human-only handlers (formal review, approval, acceptance and manual completion) must reject delegated execution identities explicitly, even if a future generic permission is accidentally broadened.

## 7. Revocation and fencing

AI-PM revokes the grant or advances authorization_generation atomically when:
- business attempt is cancelled/replaced/retried;
- user or policy revokes the execution;
- Runner key is revoked or compromised;
- execution binding changes to another Runner/key;
- security monitoring invalidates the Harness process.

On the next MCP call, AI-PM rejects the old token. SEM receives an opaque stop/release intent as required. Runner Supervisor stops the process and reports positive process-exit evidence.

Revocation does not prove process termination. A revoked Harness may still access local files, Git remotes or external services until its process/host is stopped or isolated.

## 8. Audit model

Audit must preserve separate fields:
- delegating_actor_id and actor_type;
- harness_executor_id and harness_profile;
- runner_id, key_version and attestation serial;
- grant_id, execution_id, authorization_generation;
- operation, target resource tuple, decision and reason;
- request_id, token/grant status and timestamp.

Never store plaintext bootstrap ticket or MCP token. Store only cryptographic hashes and non-secret identifiers. Ensure error traces, HTTP logs, WSS frames, telemetry and crash dumps redact credential material.

## 9. Required API surfaces (logical contract)

Exact paths and OpenAPI schemas remain to be frozen, but the design needs:
- create/revoke enrollment intent (human/admin);
- Runner enrollment proof submission;
- Runner key rotation/revocation;
- Platform→SEM identity attestation distribution/revocation;
- SEM→AI-PM binding-established event;
- AI-PM→SEM opaque bootstrap-ticket delivery;
- Runner→AI-PM bootstrap redemption;
- Runner Broker→AI-PM delegated-token renewal;
- MCP delegated authentication and per-operation authorization.

The bootstrap redemption endpoint must be reachable by Runner directly and must not require SEM to proxy the response. Network policy should permit Runner egress to AI-PM MCP/API only for these credential operations and the MCP channel.

## 10. Acceptance tests

1. Human JWT, API key, existing `cpk_`, SEM JWT and WSS credential cannot authenticate as delegated Harness identity.
2. Grant cannot be minted without a persisted AI-PM-authorized attempt and verified Runner binding.
3. Bootstrap ticket cannot be redeemed by SEM, another Runner or a substituted key.
4. Duplicate redemption is rejected after the first successful atomic consume.
5. Wrong Task/project/tenant/Run/attempt/execution/generation is rejected on both read and write operations.
6. A broad MCP read permission cannot authorize progress/result writes without the corresponding operation capability.
7. Arbitrary Task status setting, completion, formal review, approval and manual completion are rejected for delegated identity.
8. Revocation and generation change deny the next MCP request.
9. Token expiry denies access; broker renewal works only while grant and Runner key remain active.
10. Broker crash does not cause fallback to human credentials.
11. Token/ticket do not appear in prompt, argv, environment, workspace or ordinary logs.
12. Audit retains delegating actor, Harness executor and Runner as distinct identities.
13. SEM cannot inspect or redeem bootstrap ticket; AI-PM independently validates Runner key.
14. Runner key revocation blocks renewal and redemption even if SEM has not yet processed the revocation event.
15. MCP operation result submission does not mark Task completed; existing AI-PM business state machine remains authoritative.

## 11. Open choices before freeze

- exact token and ticket prefixes;
- exact ticket encryption envelope (Runner public-key encryption vs opaque random ticket + signed proof; the latter is the recommended minimum);
- exact signature encoding/canonicalization;
- credential broker transport mode compatible with each Harness;
- whether one grant permits one Harness process or a controlled subprocess tree;
- token renewal overlap and revocation SLA;
- exact operation IDs and current MCP tool mapping;
- AI-PM schema and application-service port design.

## 12. Status

This proposal closes the logical security model but not the exact wire/schema details. It must be reviewed with Runner enrollment, AI-PM MCP implementation architecture and the bilateral OpenAPI package. No code or migration is authorized.
