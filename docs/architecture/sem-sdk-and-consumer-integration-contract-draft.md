# SEM SDK and Consumer Integration Contract (Draft)

- Status: **DRAFT / USER-CONFIRMED DIRECTION — NOT IMPLEMENTATION-AUTHORIZING**
- Owner: `luqizheng/smark-sem`
- Consumer: `luqizheng/ai-pm` (and future approved Platform consumers)
- Scope: the supported programmatic integration surface for consuming SEM.
- This document makes the SDK a first-class SEM deliverable. It does not authorize SDK/runtime implementation or PR merge.

## 1. Decision

**smark-sem provides and owns the SEM SDK; AI-PM consumes it.**

AI-PM must not independently maintain a second SEM HTTP client, wire-model implementation, signature implementation, retry policy or error-code mapping. The supported Rust SDK is the canonical consumer-facing client for SEM's versioned service API.

The SDK is a library distributed from the SEM repository/release pipeline. It is not a separately authoritative service, database, protocol or business layer.

## 2. Responsibility boundary

| Responsibility | Owner |
|---|---|
| SEM API definition, OpenAPI and JSON Schemas | smark-sem |
| Rust SDK source, release, versioning and compatibility policy | smark-sem |
| Typed request/response/event models and protocol fixtures | smark-sem |
| HTTP signing/authentication client, transport, timeout and retry primitives | smark-sem SDK |
| SEM execution/delivery/binding/release state and Runner infrastructure | smark-sem service |
| Outbox creation, business intent, authorization and retry scheduling | AI-PM |
| AI-PM business Run/attempt mapping and Task transitions | AI-PM |
| SEM callback ingress, service trust configuration, Inbox transaction and Run observation | AI-PM |
| AI-PM database schema and migrations | AI-PM |

The SDK must not contain AI-PM domain models, SQL, database migrations, Task state transitions, approval logic, or code that makes business decisions.

## 3. Supported V1 SDK

V1 consumer is Rust. The initial package name is proposed as `smark-sem-sdk`; the final crate/package naming and publication channel are open until the repository's Rust workspace and release strategy are audited.

The SDK should expose a small typed surface:

- `SemClient`: configured client, endpoint, transport, authentication/signing and schema version.
- `Executions`: submit an execution request, fetch execution status/details, and request release.
- `Events`: typed SEM event envelope/model support and callback contract utilities where safe to share.
- `Models`: canonical request, response, event and error types.
- `Error`: stable typed categories preserving HTTP status, SEM error code, retryability and correlation identifiers.
- `RetryPolicy`: optional bounded per-call retry helper for explicitly safe transient outcomes only; durable retry scheduling and business retry decisions remain with AI-PM. The SDK must not own a background scheduler.
- `Config`: explicit connect/request timeouts, private-network endpoint, HTTP/HTTPS selection, trust roots or explicit certificate/public-key pin.

The SDK should provide async APIs compatible with the SEM service and AI-PM Rust workspaces. The source compatibility audit recommends Tokio 1 + reqwest 0.12/native-tls as the initial candidate: AI-PM already pins Tokio 1.54.1 and reqwest 0.12.28/native-tls 0.2.18, while SEM PR #1 uses Tokio 1 and has not yet selected an outbound HTTP client. This remains a candidate, not a frozen dependency choice. The integrated workspace must resolve and test the exact dependency graph before implementation.

## 4. AI-PM usage pattern

AI-PM remains the authority for durable business intent. The expected flow is:

1. AI-PM commits its business decision and an Outbox record in one AI-PM database transaction.
2. The AI-PM Outbox worker reads a due record and calls the SEM SDK.
3. The SDK sends the versioned, authenticated and idempotent request to SEM.
4. SEM durably accepts or rejects the infrastructure request and returns a typed response.
5. AI-PM records the response against its Outbox delivery attempt; ambiguous timeout is reconciled by retrying the same idempotency identity and exact semantic body.
6. SEM later reports infrastructure events to the AI-PM callback endpoint. AI-PM applies those events in its own Inbox/Run-observation transaction.

The SDK must not own or poll AI-PM's Outbox, open AI-PM database connections, or silently create business retries. It performs one caller-requested API operation and returns a typed result. The caller owns durable scheduling and business retry policy.

Illustrative usage only (not a frozen API signature):

```rust
let client = SemClient::builder()
    .base_url(config.sem_endpoint)
    .transport(config.transport)
    .credentials(config.sem_service_credentials)
    .build()?;

let result = client
    .executions()
    .submit(request, idempotency_key)
    .await?;
```

The proposed three-method public API, request identity rules, conditional read behavior, release fencing, signing, error taxonomy and acceptance criteria are specified in [D-12 SEM SDK Public API Design](./sem-sdk-public-api-design-draft.md). That API design remains Draft pending D-04 and bilateral review.

## 5. Transport and trust

The SDK supports the confirmed internal deployment transports:

- HTTP is allowed only on the restricted company network. It does not provide wire confidentiality. Authentication, message integrity, replay defense, idempotency and audit remain mandatory.
- HTTPS is optional and must support enterprise CA trust or an explicitly configured self-signed certificate/public-key pin. CA-chain validation and explicit pin validation are separate acceptance requirements; the selected HTTP/TLS stack must prove both. Do not infer pinning support from ordinary certificate validation.
- TLS certificate/hostname/identity verification must never be disabled. No production `insecure`, `verify=false` or equivalent escape hatch.
- The same API schemas, message semantics and error contract apply to HTTP and HTTPS.
- Endpoint, trust roots/pins and credentials are explicit configuration; no public internet dependency is assumed.

The SDK must not conflate TLS server authentication, SEM service request signing, Runner key proof-of-possession or AI-PM delegated Harness grants. These are separate identities and trust domains.

## 6. Idempotency, retries and error semantics

- Mutating calls require caller-supplied stable idempotency identity derived from the durable AI-PM Outbox operation.
- Retries reuse the same idempotency identity and semantically identical request body.
- The SDK may perform only bounded, caller-requested in-call retries for explicitly classified transient transport/service failures, reusing the exact same idempotency key and semantic request body. Durable retry scheduling, attempt timing and reconciliation ownership remain with AI-PM.
- Authentication/authorization failures, schema/version errors, stale fencing tokens and idempotency conflicts are not silently retried.
- A timeout after request transmission is an uncertain outcome, not proof of rejection. The SDK returns an outcome that lets AI-PM reconcile/retry the same operation.
- SDK retries must never generate a new execution ID or a new business attempt.
- The SDK must expose server correlation/request identifiers and preserve structured SEM error codes.

## 7. Reverse direction: SEM events into AI-PM

The SDK does not turn AI-PM into a SEM-owned application and does not move AI-PM's database or business logic into the SDK.

SEM → AI-PM is a callback initiated by SEM against an AI-PM-owned service endpoint. The canonical event envelope/schema and conformance fixtures are maintained by smark-sem. AI-PM owns:

- callback route and service identity trust configuration;
- signature, digest, freshness and replay verification at its ingress boundary;
- resolving opaque `execution_id` to its own Run/attempt;
- Inbox idempotency and contiguous per-execution event cursor;
- atomic Inbox + infrastructure Run observation + cursor transaction;
- response ACK only after commit.

The existing SEM `sem-protocol` crate is the recommended owner of transport-neutral canonical Rust request/response/event types, re-exported by the SDK. Do not create a companion types crate without a demonstrated need. Do not include an AI-PM callback HTTP server in the SDK. Any shared signature-verification primitive remains undecided until D-04's final signed-message contract and AI-PM verifier ownership are closed.

The callback receiver is not an AI-PM SEM SDK client call. It remains an AI-PM-owned HTTP server boundary.

## 8. Versioning and compatibility

- SEM owns the SDK release and compatibility policy.
- SDK releases identify the supported SEM API/schema major version.
- API schema version and SDK crate version are distinct identifiers; they must have an explicit compatibility mapping.
- Within one API major version, additive optional fields may be compatible only where the schema's unknown-field policy permits them.
- Breaking field, semantic, authentication or idempotency changes require a new API major version and corresponding SDK major version unless a documented compatibility adapter is approved.
- SEM must publish release notes, supported-version window, deprecation dates and migration guidance.
- AI-PM pins an explicit SDK version; floating/unbounded dependency versions are prohibited in production builds.
- SEM CI must validate SDK models against the canonical OpenAPI/JSON Schema and protocol fixtures.
- Bilateral CI must compile the pinned SDK in AI-PM and run consumer contract tests against the same fixtures.

## 9. Test and acceptance requirements

Before SDK implementation is approved, define executable tests for:

1. Typed serialization/deserialization matches canonical JSON Schema fixtures.
2. HTTP and HTTPS carry identical protocol semantics.
3. Enterprise CA and explicitly pinned self-signed certificate validation succeed.
4. Invalid CA, pin mismatch, hostname mismatch and expired certificate fail closed.
5. Request signing, digest and replay protection match D-04 vectors and final production contract.
6. Same idempotency key/body returns the same SEM operation; changed body conflicts.
7. Timeout after server commit can be safely reconciled with the same key/body.
8. Retry policy retries transient errors only and preserves idempotency identity.
9. Stale binding_epoch release is rejected and surfaced as a typed non-retryable result.
10. SDK does not access AI-PM DB/Outbox or mutate AI-PM business state.
11. SEM callback events match the same canonical fixtures consumed by AI-PM.
12. A pinned SDK version compiles and passes contract tests in the AI-PM repository.

## 10. Open decisions

- Ratify in-workspace crate name `sem-sdk` and published package name `smark-sem-sdk`.
- Confirm the internal Kellnr registry as distribution channel and prove SEM CI publish/read access; AI-PM already consumes internal Rust packages from this registry. Do not use a floating Git branch or unbounded version.
- Final workspace placement and release permissions.
- Confirm Tokio 1 + reqwest 0.12/native-tls after integrated workspace dependency resolution; the source compatibility audit recommends this candidate based on the current AI-PM and SEM manifests.
- Confirm `sem-protocol` as the canonical model crate and SDK re-export boundary; avoid speculative companion crates.
- Prove CA trust, hostname validation, explicit certificate/public-key pinning and fail-closed behavior with the selected TLS stack. If pinning cannot be implemented safely, stop for a bilateral transport decision; never disable verification.
- Final ratification of the proposed public method signatures and builder/configuration ergonomics in [D-12 SEM SDK Public API Design](./sem-sdk-public-api-design-draft.md).
- Whether SEM provides a reusable callback-verification helper crate, and the boundary of that helper.
- SDK support window, semantic-versioning policy and release automation.
- Exact mapping of existing D-04 OpenAPI endpoints to SDK methods.

Source compatibility findings are recorded in [SEM SDK Source Compatibility Audit](./sem-sdk-source-compatibility-audit.md). The recommended shape is an isolated `sem-sdk` crate depending on canonical `sem-protocol`, using Tokio 1 + reqwest 0.12/native-tls as a candidate, with internal Kellnr distribution subject to CI access verification. The audit is source inspection only; no integrated build, TLS pinning proof or registry publish was run.

**Disposition: DRAFT / REVIEW.** The provider/consumer direction is fixed: smark-sem provides; AI-PM consumes. Detailed SDK API, release and conformance decisions remain open. No code, migration, runtime configuration or merge is authorized.
