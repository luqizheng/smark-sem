# SEM SDK Source Compatibility Audit

- Status: **SOURCE-VERIFIED DESIGN INPUT — NOT AN API APPROVAL**
- Audit date: 2026-11-25 (latest provenance refresh)
- Current review snapshot:
  - `smark-sem` PR #1 workspace candidate: `23224d6d7f3d541677f6e48fa14d61cdd0165d9a`
  - `smark-sem` PR #3 protocol candidate: `068d44f3742b1381d059f9435f26c34137c0cebb`
  - `smark-sem` PR #4 reviewed docs head before this provenance-only update: `600d0c5ce8944e79a55cd4139fe3f2a21aaa06cf`
  - `ai-pm` source baseline: `master` (manifest, lockfile and app manifests identified by blob SHA in §§9–11)
  - `ai-pm` PR #9 design-doc head: `2e19a7ed905a78d037de5ff172fc309256e68336` (Draft docs only)
- Method: GitHub source/manifest inspection only. No local compilation, combined dependency resolution, TLS handshake/pinning, registry publish, or runtime test was performed.
- Historical first-pass revisions are retained in §9; they are not the current reviewed heads.

## 1. Verified source facts

### 1.1 AI-PM Rust workspace

The inspected AI-PM root `Cargo.toml` defines a Rust 2021 workspace and centralizes these dependencies:

| Component | Declared dependency |
|---|---|
| Async runtime | `tokio = 1`, workspace feature set `full` |
| HTTP client | `reqwest = 0.12`, `default-features = false`, features `json,native-tls` |
| HTTP server | `axum = 0.8` |
| Serialization | `serde = 1`, `serde_json = 1` |
| Errors | `thiserror = 2`, `anyhow = 1` |
| Async traits | `async-trait = 0.1` |

The pinned AI-PM Cargo.lock resolves:
- Tokio `1.54.1`
- reqwest `0.12.28`
- native-tls `0.2.18`
- Hyper `1.12.0`
- Tower `0.5.3`

The `ai-pm-runner` binary already depends on workspace Tokio and reqwest. The `ai-pm-worker` binary depends on workspace Tokio. This is concrete evidence that Tokio 1 + reqwest 0.12/native-tls is an existing consumer-compatible baseline, not a proposed second runtime.

AI-PM's `.cargo/config.toml` configures an internal sparse Cargo registry named `kellnr` at the private endpoint `192.168.2.12:16444`; the root manifest already consumes internal `digua_*` packages through that registry. This makes an internal registry a plausible SDK distribution channel. It does not prove that SEM build/release infrastructure can currently reach or publish to it.

### 1.2 SEM Rust workspace skeleton

The inspected SEM PR #1 workspace is Rust 2021 with `rust-version = 1.85`. It currently contains:
- `sem-server`
- `sem-domain`
- `sem-protocol`
- `sem-application`
- `sem-infrastructure`

Its workspace declares Tokio 1 with a reduced feature set, Axum 0.8, Serde, UUID, Chrono, async-trait and thiserror. The current SEM skeleton does **not** declare reqwest or another outbound HTTP client.

The current `sem-protocol` crate contains neutral protocol dependencies (Chrono, Serde, UUID). The service/application/infrastructure crates are separate. No SDK crate exists in the inspected PR #1 head.

The PR #4 docs branch does not contain the PR #1 Cargo workspace because PR #4 is based on the authority-boundary documentation branch, not on PR #1. Therefore PR #1 and PR #4 are independent Draft branches; they must not be treated as one already-integrated tree.

### 1.3 AI-PM callback boundary

The current bilateral design continues to assign SEM event callback ingress, service authentication, Inbox persistence, per-execution cursor and ACK-after-commit to AI-PM. A client SDK used for AI-PM→SEM calls must not move that server-side responsibility into SEM or require AI-PM to embed a SEM server.

## 2. Recommended SDK placement and dependency direction

Recommended target shape, pending the PR #1 workspace integration and final review:

```text
smark-sem workspace
  crates/sem-protocol       canonical transport-neutral wire models
  crates/sem-sdk            supported outbound Rust client
  crates/sem-domain
  crates/sem-application
  crates/sem-infrastructure
  apps/sem-server
```

Dependency rules:
- `sem-sdk` may depend on `sem-protocol` and outbound-client/crypto dependencies.
- `sem-sdk` must not depend on `sem-infrastructure`, `sem-server`, SEM database adapters, or AI-PM crates.
- `sem-server` and `sem-sdk` may both depend on `sem-protocol`; neither should duplicate the canonical wire models.
- Keep canonical schemas/fixtures as the protocol authority. Rust types are generated or validated against them; they do not become a competing schema source.
- Do not create a companion protocol-types crate now: the existing `sem-protocol` is the natural owner. Revisit only if a real downstream non-Rust consumer or dependency-weight constraint requires it.

The package name `smark-sem-sdk` remains a reasonable proposed published package name while the in-workspace crate can be `sem-sdk`; package and crate naming must be made explicit before implementation.

## 3. Runtime and HTTP client recommendation

Use Tokio 1 and reqwest 0.12 as the first implementation candidate, with `native-tls` aligned to AI-PM's existing dependency policy. This avoids introducing a second async runtime and avoids silently switching the consumer to a different TLS backend.

Important qualifications:
- AI-PM's current reqwest feature set is evidence of compatibility preference, not proof that every required SDK TLS behavior is available through that exact feature set.
- Enterprise CA trust and explicit certificate/public-key pinning are distinct requirements. Do not claim pinning is implemented merely because native TLS validates a certificate chain. Prove CA loading, hostname verification, pin comparison, expiry rejection and fail-closed behavior with executable tests.
- If the selected reqwest/native-tls stack cannot safely implement the required pinning semantics, stop and review a narrowly scoped transport adapter or TLS backend change bilaterally. Never add an insecure-verification escape hatch.
- The SDK should expose async methods but should not spawn or own a Tokio runtime. The embedding application owns runtime lifecycle.
- Keep the initial feature surface minimal; do not enable broad reqwest defaults or introduce a second HTTP stack without a demonstrated requirement.

This is a compatibility recommendation, not a final dependency lock. Exact versions/features must be resolved in the integrated workspace and verified by CI.

## 4. Recommended AI-PM integration placement

Candidate layering, subject to checking the actual Outbox implementation before coding:
- `pm-application`: owns the application port/use-case contract for submitting, querying/reconciling and releasing SEM executions.
- `pm-infrastructure`: implements that port with the published SEM SDK and maps typed SEM outcomes into infrastructure-level results.
- `ai-pm-worker`: schedules and executes due Outbox deliveries; it owns durable retry timing, attempt accounting and reconciliation triggers.
- The SDK itself does not read the Outbox, open SQL connections, schedule jobs or transition Task/Run business state.

The SDK is not a replacement for an AI-PM application port. AI-PM must remain free to test its use case with a fake port and must not leak SEM HTTP details into domain/application business rules.

## 5. Distribution recommendation

Use the existing internal Cargo registry (`kellnr`) as the leading V1 distribution candidate, rather than requiring a public crates.io release or making AI-PM depend on a floating Git branch. AI-PM already uses the registry for internal `digua_*` crates.

Before selecting this:
1. Verify SEM CI/release runners can authenticate to the same internal registry.
2. Define package ownership, immutable version publication, checksum/lockfile behavior and rollback policy.
3. Publish the SDK only after the SEM API/schema major version is frozen.
4. Pin an exact SDK version in AI-PM and compile it in bilateral CI.
5. Do not publish internal endpoints, credentials or private registry tokens in repository files.

If SEM CI cannot access the internal registry, evaluate a pinned Git tag as a temporary distribution mechanism; never use a moving branch or floating dependency.

## 6. SDK surface corrections

Recommended initial public surface:
- `SemClient` and explicit `Config`.
- Typed execution operations: submit/create, get/reconcile, release.
- Canonical request/response/error types re-exported from `sem-protocol`.
- A structured error that distinguishes transport failure, timeout/uncertain outcome, authentication/authorization, validation/schema, conflict/fencing and server failure.
- Caller-provided idempotency key and stable semantic request body for every mutating operation.

Do not make `RetryPolicy` a hidden durable scheduler. AI-PM owns retry scheduling. At most, the SDK may offer a bounded per-call retry helper for explicitly safe transient failures, reusing the exact same idempotency key and body. An ambiguous timeout must remain observable as uncertain and must never be converted to a fresh operation.

Do not include an AI-PM callback HTTP server in the SDK. Shared callback event models may be re-exported from `sem-protocol`; signature verification helpers remain undecided until D-04's final signed-message contract and AI-PM's verifier ownership are closed.

## 7. Decisions still open

1. Ratify in-workspace crate name `sem-sdk` and published package name `smark-sem-sdk`.
2. Confirm Tokio 1 + reqwest 0.12/native-tls after integrated workspace dependency resolution.
3. Prove explicit pinning with the selected TLS stack; if not possible, decide a transport adapter/backend.
4. Confirm Kellnr publishing access from SEM CI and release permissions.
5. Freeze exact methods and request/response/error schemas after D-04 endpoint closure.
6. Decide whether any shared signature-verification primitive is truly transport-neutral and safe to share; do not create it speculatively.
7. Verify AI-PM Outbox application/infrastructure placement against the actual current source before implementation.

## 8. Audit limitations

This audit does not establish:
- a successful build of a combined SEM+SDK workspace;
- a resolved SDK dependency graph or final MSRV;
- live HTTP/HTTPS behavior, certificate pinning or request-signature interoperability;
- registry publish/read permissions;
- AI-PM callback route or PostgreSQL transaction runtime correctness;
- approval of PR #1, PR #4, PR #9, or authorization to implement.

**Disposition: useful source compatibility findings obtained; SDK design remains Draft.**


## 9. Revision and provenance correction — 2026-11-25

The original header above records the snapshots used for the first pass. Those identifiers are historical and must not be read as the current PR heads. This addendum is authoritative for the latest review snapshot:

| Evidence class | Repository/ref | Exact revision | What it proves |
|---|---|---|---|
| SEM workspace candidate | `smark-sem` PR #1, `feat/sem-modular-monolith-skeleton` | `23224d6d7f3d541677f6e48fa14d61cdd0165d9a` | Rust workspace/manifests only; independent Draft branch, not integrated with PR #4 |
| SEM protocol candidate | `smark-sem` PR #3, `docs/sem-d05-lifecycle-crash-consistency` | `068d44f3742b1381d059f9435f26c34137c0cebb` | D-04 draft OpenAPI/JSON Schemas and protocol review; not ratified |
| SEM SDK document branch, earlier snapshot | `smark-sem` PR #4 | `c240628bdc4bd623503a8d671e7c86a91465d3f5` | Earlier SDK document state only |
| SEM SDK document branch, current reviewed snapshot | `smark-sem` PR #4, `docs/sem-sdk-consumer-contract` | `600d0c5ce8944e79a55cd4139fe3f2a21aaa06cf` | Current reviewed SDK docs at time of review; no SDK implementation exists |
| AI-PM source baseline | `ai-pm` `master` | root Cargo manifest blob `9213f75ff75dba9abdf307de719524d28a75f239` | Current manifest declaration for workspace dependencies; not a compiled SEM consumer |
| AI-PM design-document branch, earlier snapshot | `ai-pm` PR #9 | `19cfa2682682bfeb75bfea0091544b53a57bfc50` | Earlier design state only |
| AI-PM design-document branch, current reviewed snapshot | `ai-pm` PR #9, `docs/sem-02e-architecture-convergence` | `2e19a7ed905a78d037de5ff172fc309256e68336` | Current Draft design docs only; not merged or runtime evidence |

Important qualification: the AI-PM Cargo manifest inspection is against `master`; PR #9 is a documentation branch and does not establish a changed runtime dependency graph. The AI-PM root manifest declares Tokio 1 and reqwest 0.12 with native-tls; the prior lockfile-resolution observations must be rechecked against the exact current master lockfile before pinning exact resolved versions. The earlier statement that runner/worker crate dependencies were individually inspected should be treated as an earlier snapshot observation, not as evidence of an integrated SEM SDK build.

## 10. Current CI evidence and limitations

At the review snapshot:
- SEM PR #1 commit `23224d6...`: workflow run #18 completed successfully (format/test/clippy as represented by the PR workflow).
- SEM PR #3 commit `068d44f...`: protocol contract validation run #77 completed successfully.
- SEM PR #4 current commit `600d0c5...`: no PR workflow run returned; no CI success claim.
- AI-PM PR #9 current commit `2e19a7e...`: no PR workflow run returned; no CI success claim.

These are independent branches and workflows. PR #1's successful skeleton CI does not compile PR #4's proposed SDK, and PR #3's schema/fixture validation does not prove live HTTP signatures, TLS pinning, callback transaction correctness or cross-repository interoperability.

**Updated disposition:** source compatibility remains a static design input only. No combined workspace build, dependency resolution with SDK, TLS pin test, registry publish/read, AI-PM SDK compile, or live interoperability test has been executed.


## 11. Manifest path verification addendum — 2026-11-25

The consumer dependency claims were rechecked against the current `ai-pm/master` file paths:

- `apps/ai-pm-runner/Cargo.toml` declares both `tokio = { workspace = true }` and `reqwest = { workspace = true }` (file blob `52e418317f944eea2cdd580ab2b3a88d3440d019`).
- `apps/ai-pm-worker/Cargo.toml` declares `tokio.workspace = true`; it does not declare reqwest (file blob `7bcd231a8a88a06528815adae790c8725b759746`).
- `apps/pm-worker/Cargo.toml` also declares Tokio, not reqwest (file blob `0ac736a3bad526cc8c72973d278b4aac4b36549f`).
- AI-PM root `Cargo.lock` blob `5cf4796f81113c89a506ba67903d0ddd47806731` resolves Tokio `1.54.1`, reqwest `0.12.28` and native-tls `0.2.18`.
- AI-PM `.cargo/config.toml` blob `2060af9d3c1e958f26b06b4cb136ee7c2594b119` configures sparse internal registry `kellnr` at `192.168.2.12:16444`; this endpoint is private infrastructure and is documented here only as source evidence, not a public dependency URL or proof SEM CI can access it.

This narrows the earlier statement: `ai-pm-runner` consumes reqwest; `ai-pm-worker` consumes Tokio for worker scheduling and is not shown to consume reqwest directly. These manifest observations do not establish that an SDK dependency has been integrated or compiled.
