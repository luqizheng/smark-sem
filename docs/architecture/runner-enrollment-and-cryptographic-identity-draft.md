# Runner Enrollment and Cryptographic Identity — Revised Design Draft

- Status: **Revised proposal / user review required**.
- Decision ID: SEM-D-01.
- Scope: Runner enrollment, cryptographic identity, SEM WSS authentication, and identity binding for AI-PM delegated execution grants.
- Authority: **SEM owns Runner infrastructure identity and enrollment. AI-PM owns business authorization and delegated Harness grants.**
- Design inspiration: GitLab Runner's operator workflow (create a registration credential in the control plane, then register from the Runner host using the SEM URL and credential). The registration token is not a permanent Runner credential.
- This is a design proposal, not an approved implementation or migration. No code or migration is authorized.

## 1. Decision direction

Adopt a **SEM-issued one-time registration token + Runner-generated keypair + SEM-issued Runner identity** model.

Desired operator flow:

1. An administrator signs in to SEM and creates a Runner registration record.
2. SEM generates a registration token and displays a registration command/configuration.
3. An operator runs the registration command on the Runner host, supplying the SEM registry URL and registration token.
4. The Runner generates its own asymmetric keypair locally and submits its public key with the registration token over HTTPS.
5. SEM atomically consumes the token, creates the permanent runner_id, binds the public key, and returns the Runner identity/configuration.
6. The Runner starts its service and authenticates to SEM over WSS using proof of possession of its private key.

## 2. Authority boundary

- SEM is authoritative for Runner infrastructure identity: enrollment, runner_id, public-key binding, key versions, Runner status, connection eligibility, revocation and operational metadata.
- AI-PM is authoritative for business authorization: Task/Run/attempt scope, authorization_generation, delegated grant creation/revocation, allowed MCP operations and business outcomes.
- AI-PM does not need to create or approve each SEM Runner registration. SEM administrators control which infrastructure is admitted to SEM.
- AI-PM must validate the Runner identity assertion issued by SEM when binding a delegated grant to a Runner. It must not accept an arbitrary runner_id or public-key thumbprint supplied by a caller.
- SEM cannot create, widen, redeem or approve AI-PM business grants. A valid Runner identity is not business authorization.
- The services keep independent databases and exchange authenticated versioned API messages; no shared database or cross-database transaction is introduced.

## 3. Registration credential

### 3.1 Creation in SEM

An authenticated SEM administrator creates a registration record with at least:

- target Runner pool/group;
- permitted Runner supervision mode(s), with unattended as the default;
- optional labels/capability constraints;
- registration expiry;
- maximum successful registrations (default: one);
- administrator/audit identity.

SEM generates a cryptographically random, high-entropy token (recommended minimum: 256 bits of entropy). The raw token is displayed only at creation time. SEM stores only a verifier/hash, never the raw token.

Recommended V1 policy:

- single-use by default;
- short expiry (recommended default: 10 minutes, configurable within a safe bounded range);
- bound to one SEM instance and one target pool;
- revocable before redemption;
- atomically consumed with Runner creation so concurrent redemption cannot create multiple Runners;
- never reused for reconnects, heartbeats, WSS sessions or task delivery.

The registration token is a bootstrap secret, not a Runner identity and not a delegated Harness credential.

### 3.2 Runner host registration

Illustrative CLI (exact command and flags remain to be frozen):

~~~bash
sem-runner register --registry https://sem.example.com --registration-token <TOKEN>
~~~

The CLI sends the token only to the configured HTTPS SEM endpoint. It must validate TLS normally and must not permit insecure TLS bypass in production.

Command-line arguments may be exposed through shell history, process listings or diagnostics. The CLI must also support interactive token input or protected token-file/stdin input. It should warn against pasting production registration tokens into shared shell sessions.

### 3.3 Key generation and redemption

1. The Runner CLI/Supervisor generates a fresh per-installation signing keypair on the Runner host before redemption.
2. Recommended initial algorithm: Ed25519.
3. The private key is persisted locally under the Runner service identity with restrictive OS permissions; use an OS-protected keystore/TPM-backed storage when supported. The private key never leaves the host.
4. The Runner submits the registration token, public key, algorithm/key version, installation-generated request ID and basic host metadata to SEM over HTTPS.
5. SEM validates token scope, expiry, revocation and remaining use count; it atomically consumes the token while creating the Runner record.
6. SEM returns the assigned immutable runner_id, key version and SEM connection configuration.
7. If the response is lost after SEM commits redemption, an idempotent request ID or narrowly scoped recovery mechanism must recover the same result without creating a second Runner or making the token reusable for a new identity.

The registration token is never used after successful enrollment and must not be stored in steady-state Runner configuration.

## 4. WSS authentication and Runner lifecycle

1. Runner opens outbound TLS/WSS to SEM; no inbound Runner port is required.
2. SEM sends a fresh, short-lived challenge bound to the connection/session and protocol version.
3. Runner signs the canonical challenge using its enrolled private key.
4. SEM validates the signature against the public key bound to runner_id and checks Runner/key status.
5. SEM establishes a session bound to runner_id, key_version, connection_id and boot_id.
6. Heartbeats, resource telemetry, delivery acknowledgements and process observations are accepted only on the authenticated session.

A Runner ID, IP address, hostname, self-declared public key or registration token alone is insufficient to authenticate a steady-state connection.

SEM supports key rotation and revocation:
- Planned rotation: authenticated Runner proves possession of the current key and submits a new public key; SEM creates the next key version. Any overlap is bounded. Execution grants remain bound to one exact key version/identity generation.
- Compromise: SEM revokes the key/Runner, rejects new WSS sessions and stops new deliveries. Revocation does not prove an already-running Harness process has stopped.
- Lost key/reinstalled host: revoke the old key and perform a new administrator-authorized registration. Do not recover or copy the old private key from SEM.
- Re-registration must not silently inherit old process bindings, reservations or execution authority.

## 5. AI-PM delegated-grant binding

The SEM Runner identity is infrastructure identity only.

- AI-PM creates the delegated grant and binds it to the exact runner_id, SEM identity issuer, key version/identity generation, execution, binding epoch, authorization generation and operation allow-list.
- AI-PM validates the Runner identity using an authenticated SEM-signed identity assertion or authenticated SEM control-plane lookup. Exact assertion format and key-distribution mechanism are D-04/D-06 contract work.
- SEM transports the opaque one-time bootstrap ticket only to the matching authenticated Runner session.
- Runner proves possession of the bound private key during redemption; AI-PM validates the SEM identity assertion and ticket/grant scope.
- SEM cannot redeem or widen the grant. AI-PM remains the sole issuer and authority for delegated MCP credentials.
- A revoked Runner identity or changed key generation cannot redeem a grant bound to the old identity generation.
- Runner identity revocation, AI-PM grant revocation and process termination are distinct operations with distinct evidence.

This replaces the earlier proposal that AI-PM creates each Runner enrollment intent and signs the primary Runner identity attestation. That approach unnecessarily makes the business platform the owner of infrastructure enrollment.

## 6. Security requirements

- Registration tokens are high entropy, short-lived, single-use by default, scope-bound and stored only as hashes/verifiers.
- Token redemption is atomic and replay-safe; concurrent redemption cannot create duplicate Runner identities.
- Registration tokens, private keys, delegated MCP tokens and bootstrap tickets must never appear in prompts, workspace files, ordinary logs or telemetry.
- Private keys are unique per Runner installation and never shared across hosts.
- SEM identity-signing keys (if signed assertions are used) are separate from Runner keys and protected as control-plane secrets.
- AI-PM pins/trusts SEM identity verification keys through an authenticated, versioned key-distribution process. Rotation and emergency revocation are explicit.
- SEM registration endpoints require authenticated administrator authorization; Runner redemption endpoints are rate-limited and audited.
- Registration must not expose arbitrary pool selection or privilege escalation through caller-controlled metadata.
- TLS certificate validation is mandatory in production; registration credentials must not be sent to another origin after redirects.

## 7. Rejected alternatives

| Alternative | Reason rejected |
|---|---|
| Reuse existing AI-PM cpk_ | Reusable device-wide secret mapped to HumanActor; not a cryptographic Runner identity or per-execution grant |
| Use registration token as permanent Runner credential | A leaked bootstrap token would permit persistent impersonation; no key rotation or proof-of-possession boundary |
| Let AI-PM create every Runner enrollment intent | Couples infrastructure enrollment to business project administration |
| Trust runner_id/IP/hostname only | Copyable or spoofable metadata without cryptographic proof |
| Let SEM mint AI-PM delegated grants | Violates AI-PM business authorization authority |
| Use WSS credential as MCP credential | Infrastructure channel authentication is not business authorization |

## 8. Open details to close in D-04/D-09

- Exact registration API path, request/response schema and idempotency semantics.
- Exact token encoding/prefix, hash/KDF choice, storage and rate limits.
- Exact CLI command name and secure token input modes.
- Runner private-key storage profile for Linux and Windows service deployments.
- WSS challenge canonicalization, signature domain separation and replay window.
- SEM identity assertion format (e.g. JWS/COSE) or authenticated identity lookup contract for AI-PM.
- SEM signing-key distribution, rotation and emergency revocation.
- Recovery behavior when SEM commits redemption but the response is lost.
- Whether a registration record can permit multiple registrations; default remains one.
- Audit retention and administrative recovery procedures.

## 9. Acceptance tests

1. Unauthenticated SEM users cannot create registration records.
2. Wrong, expired, revoked or already-consumed registration tokens are rejected.
3. A registration token cannot be redeemed outside its configured SEM instance/pool scope.
4. Concurrent redemption produces at most one Runner identity.
5. A Runner generates its private key locally; private key material never reaches SEM.
6. A Runner without proof of private-key possession cannot establish WSS.
7. Replayed challenge signatures and signatures from another connection are rejected.
8. Changing runner_id, key version or public-key thumbprint invalidates authentication.
9. A lost registration response can be recovered idempotently without creating a second Runner.
10. Revoked/lost keys cannot reconnect or receive new work.
11. AI-PM rejects a delegated grant request with an untrusted or revoked SEM Runner identity.
12. SEM cannot create or widen an AI-PM delegated grant.
13. Runner identity revocation does not count as process exit or automatically release process reservations.
14. No registration token, private key, bootstrap ticket or delegated MCP token appears in prompts, argv, workspace or ordinary logs.
15. A registration token cannot be used for WSS authentication or MCP access after enrollment.

## 10. Status

This revised proposal captures the GitLab-Runner-style operator workflow and the infrastructure/business authority split. It supersedes the previous D-01 proposal's AI-PM-created enrollment intent and AI-PM-issued primary Runner identity attestation.

**Pending user ratification.** D-01 is not implementation-ready until open details affecting security and interoperability are closed in D-04/D-09. No code or migration is authorized.
