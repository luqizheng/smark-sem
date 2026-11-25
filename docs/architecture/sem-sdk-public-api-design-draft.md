# D-12 — SEM Rust SDK Public API Design (Draft)

- Status: **DRAFT / ARCHITECTURE REVIEW — NOT IMPLEMENTATION-AUTHORIZING**
- Owner: `smark-sem`
- Consumer: `ai-pm`
- Protocol baseline reviewed: SEM PR #3, commit `068d44f3742b1381d059f9435f26c34137c0cebb`
- Consumer source baseline reviewed: AI-PM PR #9, commit `19cfa2682682bfeb75bfea0091544b53a57bfc50`
- Companion: [SEM SDK source compatibility audit](./sem-sdk-source-compatibility-audit.md)
- Protocol source: [Platform–SEM execution message protocol](https://github.com/luqizheng/smark-sem/blob/docs/sem-d05-lifecycle-crash-consistency/docs/protocol/PLATFORM-SEM-EXECUTION-MESSAGE-PROTOCOL-DRAFT.md)
- OpenAPI source: [Platform–SEM OpenAPI draft](https://github.com/luqizheng/smark-sem/blob/docs/sem-d05-lifecycle-crash-consistency/docs/protocol/openapi/platform-sem-v1-draft.yaml)

This document proposes the first public SDK surface. It does not ratify D-04, freeze wire schemas, authorize implementation, or authorize merging PR #1/#3/#4/#9.

## 1. V1 scope

The SDK is the supported Rust client for AI-PM → SEM. It exposes only the Platform-owned operations currently defined by the D-04 OpenAPI draft:

| SDK operation | HTTP operation | Meaning |
|---|---|---|
| `submit_execution` | `POST /internal/sem/v1/executions` | Durably submit an opaque execution request |
| `get_execution` | `GET /internal/sem/v1/executions/{execution_id}` | Read/reconcile SEM infrastructure state |
| `request_release` | `POST /internal/sem/v1/executions/{execution_id}/release` | Persist a binding-fenced release intent |

No V1 SDK API may:
- create or mutate AI-PM Task/Run/Requirement/Approval state;
- read/write AI-PM Outbox or PostgreSQL;
- schedule durable retries or decide business retry eligibility;
- select or control a Runner directly;
- launch/stop a Harness process directly;
- host the SEM→AI-PM callback endpoint or own AI-PM Inbox transactions;
- redeem Harness delegated MCP credentials (that is a separate Runner Broker ↔ AI-PM contract).

The SDK sends the opaque prompt as supplied. It must not parse or reinterpret prompt content.

## 2. Package and crate placement

Proposed names:
- workspace crate: `sem-sdk`;
- published Cargo package: `smark-sem-sdk`;
- canonical protocol model crate: existing `sem-protocol`.

Target dependency direction:

```text
sem-server ─────┐
                ├──> sem-protocol
sem-sdk ────────┘

ai-pm pm-infrastructure ──> smark-sem-sdk
ai-pm pm-application     ──> AI-PM-owned SEM port (no SEM HTTP types)
ai-pm worker             ──> AI-PM Outbox use case/scheduler
```

The SDK may depend on `sem-protocol`, HTTP/TLS, serialization and cryptographic support. It must not depend on `sem-server`, `sem-infrastructure`, SEM database adapters, or AI-PM crates. The server and SDK must not maintain duplicate wire models.

The published package name, workspace crate name and package ownership remain proposed until the workspace integration PR and release pipeline are reviewed.

## 3. Proposed public API shape

Illustrative Rust API (names and exact field types remain subject to the canonical schemas):

```rust
pub struct SemClient { /* private transport and protocol state */ }

pub struct SemClientConfig {
    pub base_url: Url,
    pub transport_security: TransportSecurityConfig,
    pub request_signer: Arc<dyn HttpMessageSigner>,
    pub response_verifier: Arc<dyn HttpMessageVerifier>,
    pub peer_key_resolver: Arc<dyn PeerKeyResolver>,
    pub request_timeout: Duration,
    pub max_response_bytes: usize,
}

impl SemClient {
    pub fn new(config: SemClientConfig) -> Result<Self, SemSdkConfigError>;

    pub async fn submit_execution(
        &self,
        request: SubmitExecutionRequest,
    ) -> Result<ExecutionAcceptance, SemSdkError>;

    pub async fn get_execution(
        &self,
        execution_id: ExecutionId,
        condition: Option<ExecutionReadCondition>,
    ) -> Result<ExecutionRead, SemSdkError>;

    pub async fn request_release(
        &self,
        request: ReleaseExecutionRequest,
    ) -> Result<ReleaseAcceptance, SemSdkError>;
}
```

The public API must be async but must not create, own, or shut down a Tokio runtime. The embedding application owns runtime lifecycle. The SDK must not spawn background workers.

### 3.1 Submit request

The request type carries the canonical D-04 fields:
- caller-supplied stable `request_id` / idempotency key;
- caller-supplied `message_id`;
- `correlation_id` where available;
- `execution_id`;
- opaque prompt content type and body;
- Harness profile;
- infrastructure-only Runner requirements, including capabilities and supervision mode.

The SDK must serialize the canonical envelope and set the `Idempotency-Key` and `X-SEM-Message-Id` headers to the exact corresponding envelope values. It must reject local header/envelope disagreement rather than send it.

The SDK must not generate a new request_id after an ambiguous result. A retry by AI-PM must preserve the exact request identity and semantic body.

### 3.2 Read/reconciliation request

`get_execution` returns only SEM infrastructure state and associated infrastructure identifiers/observations defined by the canonical snapshot schema. It never returns an AI-PM Task status or business outcome.

The optional read condition represents the HTTP `If-None-Match` validator. The result must distinguish:
- `Modified(snapshot, etag)` for HTTP 200;
- `NotModified` for HTTP 304.

The current OpenAPI draft defines an ETag response header for 200 but does not explicitly define it for 304. Before freezing the Rust return type, D-04 must decide whether 304 echoes ETag (recommended) and add the corresponding OpenAPI header and signed-response coverage. Until then the SDK must not promise an ETag value on the 304 branch.

A 404 means the execution identifier is unknown to SEM; it must not be silently translated into an empty/queued execution.

### 3.3 Release request

The release request carries:
- `execution_id`;
- caller-supplied stable `request_id` / idempotency key and `message_id`;
- `release_id`;
- `expected_binding_epoch`;
- the protocol-defined stop policy.

A stale binding epoch (HTTP 412 in the current OpenAPI draft) is a typed fencing conflict, not a transient retry. The SDK must never retry it with a modified epoch. AI-PM must reconcile current infrastructure state and make a new business decision before issuing a new request.

The SDK must ensure the path execution_id and body execution_id are identical.

## 4. Identity and signing

The Platform↔SEM protocol uses service-owned Ed25519 HTTP Message Signatures (RFC 9421) and Content-Digest (RFC 9530), independent of TLS and Runner identity.

The SDK must:
- sign every request using the AI-PM service signing identity;
- verify every authenticated SEM response before exposing its status/body as trusted;
- cover exactly the components frozen by the D-04 bilateral profile;
- enforce created/expires/nonce and key-id policy;
- reject unknown, expired, revoked or mismatched peer keys;
- fail closed on missing or invalid signatures/digests;
- never offer `insecure`, `verify=false`, unsigned fallback or production signature bypass.

The API should accept signer/verifier/key-resolver abstractions so the consumer can bind keys to its existing secret-management mechanism. Whether the production implementation uses a built-in Ed25519 provider or a consumer-supplied provider must be decided after D-04 closes. Do not expose raw private-key bytes in Debug output, errors, logs or serialized config.

TLS server identity validation is additional to HTTP message signing:
- support enterprise CA trust;
- support explicitly provisioned self-signed certificate/public-key pins;
- validate hostname/identity and certificate validity;
- prove CA trust and explicit pin matching separately;
- no downgrade from HTTPS to HTTP after a TLS failure.

The current AI-PM reqwest/native-tls dependency is a compatibility candidate, not evidence that pinning is already implemented. The chosen transport implementation must pass the TLS acceptance suite before API ratification.

## 5. Error contract

The public error model must preserve uncertainty and protocol meaning. Proposed categories:

| Error | Meaning | Caller action |
|---|---|---|
| `Configuration` | Invalid local URL, trust or signer configuration | Fix configuration; do not send |
| `Authentication` | Request signing rejected or peer authentication failed | Security/configuration investigation |
| `Protocol` | Invalid schema, unsupported version, invalid response/signature | Fail closed; investigate compatibility |
| `Validation` | Request violates a protocol invariant | Correct request; do not retry unchanged |
| `IdempotencyConflict` | Same idempotency key reused with different semantic body | Stop; reconcile caller state |
| `FencingConflict` | Expected binding epoch is stale | Reconcile; never blindly retry |
| `NotFound` | Execution unknown to SEM | Reconcile with AI-PM business record |
| `RateLimited` | SEM returned 429 | Honor bounded Retry-After |
| `TransientService` | Explicit retryable 5xx/service outcome | Caller-owned retry policy may retry same operation |
| `Transport` | Connection failed before request transmission is known | Preserve transport stage where known |
| `OutcomeUnknown` | Request may have reached SEM, but no authenticated definitive response was received | Reconcile using same request identity; never create a new attempt automatically |

The SDK must distinguish a definitive rejection from an ambiguous outcome. It must not collapse timeout, connection reset after write, malformed response or invalid response signature into a definitive failure.

## 6. Retry and idempotency

Default SDK behavior: **no automatic operation retry**. This keeps durable scheduling, backoff, attempt accounting and reconciliation with the AI-PM Outbox worker.

An optional bounded per-call retry helper may be considered later, but only if:
- the response/error is explicitly classified safe to retry;
- the same message_id, request_id/idempotency key and exact semantic body are reused;
- no new execution_id or business attempt is generated;
- retry count/deadline is bounded and caller-controlled;
- ambiguous outcomes are returned to the caller for reconciliation rather than hidden.

For 429, preserve Retry-After. For 5xx, follow the protocol's retryability classification. Never retry 412 fencing conflicts, 409 idempotency conflicts, authentication failures, schema failures or other definitive protocol rejections.

## 7. Callback boundary

The SDK does not expose a callback server or callback database adapter.

SEM owns:
- canonical SEM event types and schemas;
- event production, durable event identity and at-least-once delivery;
- protocol fixtures for SEM-produced events.

AI-PM owns:
- callback route and service authentication;
- signature/freshness/replay verification on ingress;
- mapping execution_id to the exact AI-PM Run/attempt;
- durable Inbox deduplication and per-execution sequence cursor;
- atomic Inbox + infrastructure Run observation + cursor transaction;
- ACK only after commit, and its retry/dead-letter policy.

The SDK may re-export transport-neutral event models from `sem-protocol` if that does not couple AI-PM to SEM server implementation. Sharing signature-verification code is not assumed; decide only after D-04 closes and the two sides prove identical verification semantics.

## 8. Versioning and distribution

Proposed:
- SDK package major version maps to Platform–SEM API major version.
- SDK minor versions may add backward-compatible methods/types only when the wire contract permits them.
- Breaking wire or public API changes require a major version.
- AI-PM pins an exact SDK version in Cargo.toml/Cargo.lock; no floating branch dependency.
- Internal Kellnr is the leading V1 distribution candidate because AI-PM already consumes internal Rust packages there. SEM CI publish/read access, immutable version policy, credentials and rollback must be verified before selecting it.
- Every SDK release must publish versioned protocol/schema compatibility metadata and run bilateral consumer compilation/contract tests.
- No public crates.io publication is required for the internal-only V1 deployment.

## 9. Acceptance criteria before API ratification

1. Canonical D-04 OpenAPI and JSON Schemas are ratified and the three methods map one-to-one to them.
2. Request/header/envelope identity equality is tested.
3. RFC 9421 request signing and signed-response verification interoperate across independent implementations.
4. RFC 9530 digest calculation and covered-component canonicalization are tested.
5. Replay nonce store semantics and key rotation/revocation are closed bilaterally.
6. Enterprise CA and explicit pinning both pass positive, negative, expiry and hostname tests.
7. Invalid/missing signatures and TLS trust failures fail closed.
8. Ambiguous timeout is distinguishable from definitive rejection.
9. Idempotent replay returns the same durable disposition; changed body conflicts.
10. 412 stale epoch is typed and never automatically retried.
11. 200/304 conditional read and 404 semantics are tested; the 304 ETag response-header omission in the current OpenAPI draft is resolved.
12. No automatic durable retry, Outbox access, DB access, Task transition or callback server exists in SDK.
13. AI-PM compiles against the published immutable SDK version in bilateral CI.
14. SEM CI verifies public API compatibility and package publication provenance.
15. SDK docs include supported Rust/MSRV, runtime, TLS, registry and upgrade policy.

## 10. Blocking open decisions

- D-04 exact request/response/event schema and signature profile closure, including the currently unspecified ETag response header on 304.
- Final signer/verifier/key-resolver interfaces and crypto implementation ownership.
- Whether reqwest 0.12/native-tls can meet explicit pinning requirements safely.
- SEM CI access to internal Kellnr and immutable publish permissions.
- Exact SDK and protocol crate/package names.
- Exact public Rust type names, constructors, builder/config ergonomics and error source chain.
- AI-PM application port and infrastructure adapter placement, confirmed against current source.
- Bilateral CI mechanism and compatibility support window.

**Disposition: proposed public API contract is now detailed enough for bilateral review, but remains Draft / Changes Required until the blockers and acceptance criteria close. No SDK implementation is authorized by this document.**
