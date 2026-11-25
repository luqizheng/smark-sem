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
4. The Runner generates its own asymmetric keypair locally and submits its public key with the registration token over the configured internal HTTP or HTTPS endpoint.
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
sem-runner register --registry http://sem.internal.example --registration-token <TOKEN>
~~~

The CLI sends the token only to the configured SEM origin on the company private network. The registry URL may use HTTP or HTTPS. For HTTPS, the client must validate a configured enterprise CA bundle or explicitly pinned certificate/public-key fingerprint; self-signed certificates are supported. Verification bypass is forbidden in production. HTTP is allowed only on a restricted internal network and provides no confidentiality.

Command-line arguments may be exposed through shell history, process listings or diagnostics. The CLI must also support interactive token input or protected token-file/stdin input. It should warn against pasting production registration tokens into shared shell sessions.

### 3.3 Key generation and redemption

1. The Runner CLI/Supervisor generates a fresh per-installation signing keypair on the Runner host before redemption.
2. Recommended initial algorithm: Ed25519.
3. The private key is persisted locally under the Runner service identity with restrictive OS permissions; use an OS-protected keystore/TPM-backed storage when supported. The private key never leaves the host.
4. The Runner submits the registration token, public key, algorithm/key version, installation-generated request ID and basic host metadata to SEM over the configured internal HTTP or HTTPS transport.
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

## 4.1 Online detection and dispatch eligibility over the existing WSS session

The Runner maintains one outbound, authenticated, long-lived WSS connection to SEM. SEM does not open a new TCP/WSS connection for each task and does not use an HTTP polling loop to discover Runner availability.

**A live WSS socket is necessary but not sufficient to declare a Runner dispatch-ready.** TCP/WSS can remain established while the Runner Supervisor is stalled, overloaded, draining, or unable to start a process. SEM therefore maintains separate connection, liveness and admission facts.

A Runner is eligible for a new dispatch only when all of the following are true:

1. Its WSS session completed the cryptographic challenge-response handshake and is bound to the current `runner_id`, key version, `connection_id` and `boot_id`.
2. The session is currently open and the most recent application-level Runner heartbeat is within the configured freshness window.
3. The latest resource/capacity report is fresh and belongs to the same `boot_id`; it reports sufficient CPU, memory and workspace-volume headroom after SEM's own reservations are deducted.
4. The Runner Supervisor reports `accepting_work=true`, is not draining, quarantined or revoked, and has not reported a local process-registry/recovery condition that prevents safe admission.
5. SEM has no conflicting active reservation or stale binding for the selected Runner.

### Heartbeat and liveness

- WSS transport ping/pong is used to detect broken transport paths, but it is not the sole application health signal.
- Runner sends an authenticated application heartbeat on the WSS session at a configured interval. It includes `runner_id`, `boot_id`, a monotonically increasing session sequence, Supervisor health, `accepting_work`, active execution count and the timestamp of the observation.
- SEM may also send an application-level `runner.health_probe` over the existing session and require a correlated `runner.health_report` before dispatch when the last heartbeat is approaching its freshness limit. This is a message on the existing WSS session, not a new connection.
- Missing heartbeat beyond the liveness deadline changes the connection/liveness view to `suspect` and then `disconnected`; it does not prove that any Harness process exited.
- A new WSS connection after reconnect must authenticate again and establish a new `connection_id`. The previous connection is fenced; messages from it are rejected even if they arrive late.

### Dispatch handshake and race handling

1. The scheduler selects only a Runner satisfying the eligibility predicate above.
2. SEM atomically creates a capacity reservation and the new `binding_epoch` before sending the execution offer. The reservation prevents another scheduler worker from allocating the same capacity.
3. SEM sends the execution delivery over that Runner's authenticated WSS session, carrying stable `execution_id`, `delivery_id`, `binding_epoch` and opaque business payload.
4. Runner Supervisor durably records the delivery and returns `execution.delivery_received` on the same authenticated session. This ACK means only “durably accepted by Supervisor”; it does not mean Harness started.
5. Runner then reports process-start observation only after the OS process/container has actually been created and its identity captured.
6. If the WSS session closes before delivery, SEM retries/reconciles according to the same `delivery_id`; it must not create a second logical execution.
7. If the delivery ACK is missing or its outcome is ambiguous, SEM marks the delivery/binding uncertain and reconciles with the Runner after reconnect. It must not immediately dispatch the same execution to another Runner merely because the socket disappeared: the first Runner may have durably accepted or started it.
8. A replacement Runner may be selected only after the old binding is fenced and SEM has evidence that no process was started, or after the old process is positively exited/isolated under the D-03 recovery rules.

A Runner may explicitly transition to draining. SEM stops assigning new executions to it while existing executions continue under their current bindings. Revocation or quarantine also blocks new dispatch immediately, but does not imply process termination.

### Operational status model

Do not collapse these states into a single `online` boolean:

| Dimension | Example values | Meaning |
|---|---|---|
| Transport | `connected`, `disconnected` | Authenticated WSS session state |
| Liveness | `healthy`, `suspect`, `stale` | Freshness of application heartbeat and Supervisor health |
| Admission | `accepting`, `draining`, `disabled`, `quarantined` | Whether new work may be assigned |
| Capacity | `available`, `constrained`, `unknown` | Fresh resource report plus reservations |
| Dispatch eligibility | `eligible`, `ineligible` | SEM-derived predicate over all dimensions |

The UI may summarize a Runner as “Online” only when transport is connected and liveness is healthy; it must show readiness/capacity separately. A Runner can be online but not eligible for dispatch.

### Acceptance tests for WSS liveness and dispatch

1. A disconnected or unauthenticated WSS session is never selected for new work.
2. An open WSS socket with a stale application heartbeat is not dispatch-eligible.
3. A fresh transport ping/pong without a fresh application heartbeat is insufficient.
4. A fresh heartbeat with `accepting_work=false`, draining or quarantine is not dispatch-eligible.
5. Stale capacity telemetry or a mismatched `boot_id` is treated as unknown, not unlimited capacity.
6. Concurrent scheduler workers cannot over-reserve one Runner's reported capacity.
7. A delivery is sent only after the reservation and binding epoch are durable.
8. Duplicate delivery with the same `delivery_id` returns the original durable receipt and does not start a second Harness process.
9. WSS loss before ACK causes reconciliation, not blind reassignment.
10. WSS reconnect creates a new authenticated connection generation; late messages from the prior connection are rejected.
11. Runner draining blocks new work but does not terminate already-running executions.
12. “Online” status never serves as evidence that an existing Harness process exited.

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
- For HTTPS/WSS, server certificate validation is mandatory in production and supports enterprise CA or explicitly pinned self-signed certificates; no insecure verification bypass is allowed. Registration credentials must not be sent to another origin after redirects. HTTP may be used only on the restricted internal network.

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

Transport configuration must define HTTP/HTTPS selection, trust-store/CA-bundle and certificate/public-key pin formats, hostname verification, redirect policy, certificate renewal/rotation/overlap/revocation, and how trust material is provisioned to Runner hosts. Self-signed certificates are supported when explicitly trusted; disabling certificate verification is not.

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
