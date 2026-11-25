# Runner Enrollment and Cryptographic Identity — Design Decision Draft

- Status: **Proposed design / review required**.
- Decision ID: SEM-D-01.
- Scope: Runner enrollment, proof of possession, SEM WSS authentication and AI-PM delegated-grant binding.
- Authority: AI-PM owns the trust decision for whether a Runner key may receive delegated Harness authority; SEM owns operational Runner registration and connectivity.
- This is a design proposal, not an approved implementation or migration.

## 1. Problem and source constraints

The current AI-PM device registry is not a cryptographic Runner identity system:
- Device registration accepts device metadata and an `is_runner` flag, but does not enroll a public key or certificate.
- Existing `cpk_` is a reusable device-wide secret. Authentication maps it to the device owner's HumanActor and project-membership model.
- Existing `cpk_` does not bind to execution_id, Task, Run/attempt, authorization_generation, Runner key or an operation allow-list.

Therefore the existing `cpk_` credential and device-owner attribution must not be reused for delegated Harness MCP access. The source evidence is recorded in [AI-PM Harness identity review §10](https://github.com/luqizheng/ai-pm/blob/docs/sem-02e-architecture-convergence/docs/architecture/server-execution-management/harness-identity-and-business-fencing-review.md).

## 2. Decision proposal

Adopt a **Runner keypair + AI-PM enrollment trust record + signed Runner Identity Attestation** model.

- Runner Supervisor generates and owns a per-installation asymmetric keypair.
- The private key never leaves the Runner host and is not stored in SEM or AI-PM.
- AI-PM maintains the minimal trust record needed to decide whether that exact Runner key is eligible to redeem a delegated execution grant.
- AI-PM issues a signed identity attestation after an owner-approved enrollment ceremony.
- SEM receives the attestation and public key through an authenticated Platform→SEM control message and uses them to authenticate the Runner WSS connection.
- AI-PM independently validates the Runner key against its own enrollment record when a delegated bootstrap ticket is redeemed. It never trusts a public-key thumbprint supplied only by SEM.

This is deliberately a split of responsibility:
- AI-PM trust record: identity and authorization trust anchor only.
- SEM Runner record: operational endpoint, capability, supervision, health and resource metadata.
- The two records share an immutable runner_id and key thumbprint, but neither database is shared.

## 3. Enrollment ceremony

### 3.1 Human-approved enrollment intent

1. An authorized AI-PM tenant/project administrator creates a Runner enrollment intent.
2. AI-PM allocates an immutable `runner_id`, a one-time enrollment nonce and an expiry.
3. The intent records tenant, approving actor, intended deployment label, allowed supervision modes and enrollment status.
4. The enrollment nonce is single-use, short-lived and stored hashed. It is not a reusable Runner credential.

No Runner becomes trusted merely because it connects to SEM or declares `is_runner=true`.

### 3.2 Runner key generation and proof of possession

1. Runner Supervisor generates a fresh Ed25519 signing keypair on the host.
2. Private key storage preference:
   - OS-protected keystore/TPM-backed storage when available;
   - otherwise a dedicated service-account-owned file with restrictive permissions and encrypted-at-rest host storage where available.
3. The Runner sends `runner_id`, enrollment nonce, public key, key algorithm/version and a proof-of-possession signature over the enrollment challenge to AI-PM over TLS.
4. AI-PM validates the one-time nonce, expiry, tenant/owner approval, signature and that the nonce has not already been consumed.
5. AI-PM stores the public key, thumbprint, key version, enrollment actor, created_at, status and revocation metadata in its trust record.

The private key is never sent to AI-PM or SEM. The enrollment nonce is not used for subsequent WSS or MCP authentication.

### 3.3 AI-PM identity attestation

After enrollment, AI-PM issues a signed Runner Identity Attestation containing only infrastructure identity claims:
- issuer and audience (SEM Runner edge);
- runner_id and tenant_id;
- public-key thumbprint and key algorithm;
- key_version and attestation serial/jti;
- issued_at, not_before and expires_at;
- enrollment status and permitted connection purpose.

The attestation must not contain Task, Project work scope, Run, execution_id, business permissions or MCP operations. It proves identity, not business authorization.

AI-PM publishes the attestation and public key to SEM through the authenticated Platform→SEM service channel. SEM stores it as the operational Runner trust material. SEM validates the attestation signature against an AI-PM verification key configured out of band or through a pinned, authenticated key-distribution process.

### 3.4 WSS connection authentication

Recommended WSS handshake:
1. Runner opens TLS/WSS to SEM.
2. SEM sends a fresh, short-lived challenge with server identity, connection nonce and protocol version.
3. Runner signs the canonical challenge using its enrolled private key.
4. SEM validates the signature against the public key in the AI-PM-signed attestation, and checks attestation validity/revocation state.
5. SEM establishes a Runner session bound to runner_id, key_version, connection_id and Runner boot_id.
6. All subsequent messages are associated with that authenticated session and carry execution_id/binding_epoch/event_id/event_sequence as appropriate.

A plain device ID, IP address, self-declared public key or replayed signature is insufficient. TLS protects the channel; the application-level challenge binds the Runner identity and prevents replay across sessions.

SEM must refresh/reconcile attestation revocation state. AI-PM remains authoritative for whether the key is trusted; SEM may deny a Runner earlier but may not override AI-PM revocation.

## 4. Delegated bootstrap binding

For the execution bootstrap in the companion contract:
- AI-PM looks up the enrolled Runner key by runner_id in its own trust record.
- AI-PM binds the one-time bootstrap ticket to runner_id, key thumbprint/key_version, execution_id, binding_epoch and the delegated grant.
- SEM transports the opaque ticket only to the matching current Runner binding.
- Runner proves possession by signing the redemption challenge with the enrolled private key.
- AI-PM verifies the signature against its own enrolled public-key record, not a key value supplied by SEM.
- The ticket is single-use; successful redemption consumes it atomically.
- The resulting short-lived MCP grant is scoped to the exact business attempt and operation allow-list.

SEM cannot redeem the ticket because it does not possess the Runner private key. Substituting another public key or changing runner_id/key_version fails AI-PM verification.

## 5. Rotation, revocation and recovery

### 5.1 Planned key rotation

1. Runner generates a new keypair and proves possession while authenticated with the current key.
2. AI-PM validates the current identity and an authorized rotation operation.
3. AI-PM creates the next key_version and publishes a new signed attestation to SEM.
4. A bounded overlap may be allowed for WSS reconnection only; delegated bootstrap tickets bind to one exact key_version and are never transferable.
5. AI-PM revokes the old key after the new key is confirmed active, or immediately if compromise is suspected.

### 5.2 Revocation

- AI-PM revokes the key in its trust record and emits a durable revocation event to SEM.
- AI-PM rejects future bootstrap redemption and delegated MCP requests bound to the revoked key/generation.
- SEM rejects new WSS sessions and stops new delivery to the revoked Runner.
- Revocation does not prove an already-running Harness process has stopped. AI-PM authorization revocation and Runner process termination remain separate actions.
- If the Runner is suspected compromised, quarantine its binding and require process/host isolation evidence before any replacement execution is dispatched.

### 5.3 Lost key / host reinstall

A lost private key cannot be recovered from SEM or AI-PM. The host must be re-enrolled through a new human-approved ceremony:
- revoke old key;
- issue new enrollment intent;
- generate a new keypair;
- approve the new key and update the SEM attestation;
- reconcile or quarantine any old process bindings before reusing capacity.

A copied `runner_id` or copied device metadata does not confer identity without the private key.

## 6. Trust and key management requirements

- AI-PM attestation signing key is separate from LMMS user-token signing keys unless a later explicit security review approves shared key infrastructure.
- SEM pins the AI-PM attestation verification key set and supports key rotation with explicit kid/key validity windows.
- Runner signing private keys are per installation, not per tenant and not shared among Runner hosts.
- Key material and attestation secrets never appear in prompts, Harness arguments, workspace files, ordinary logs or telemetry.
- Audit records include runner_id, key_version, attestation serial, enrollment/rotation/revocation actor and timestamps, but never private key or reusable bootstrap secret.
- Enrollment, rotation and revocation endpoints require human/administrative authorization and CSRF/anti-replay protections appropriate to their transport.

## 7. Rejected alternatives

| Alternative | Reason rejected |
|---|---|
| Reuse current `cpk_` | Static device-wide credential; owner HumanActor mapping; no proof of private-key possession or per-execution scope |
| Trust a public-key thumbprint sent by SEM | A compromised SEM could substitute its own key and obtain a Runner-bound ticket |
| Use SEM WSS credential as MCP credential | Infrastructure channel credential is not AI-PM business authorization |
| Put a reusable MCP token in prompt/body | Exposes credential to SEM, logs, Harness prompt history and unrelated process surfaces |
| Identify Runner by device_id/IP/hostname only | Copyable/spoofable metadata; no cryptographic proof of possession |
| Let SEM mint AI-PM delegated grants | Violates AI-PM business authorization authority |

## 8. Open implementation details

The architecture direction is proposed, but these details must be closed in the machine-readable security/API contract:
- exact attestation format (COSE_Sign1/JWS or X.509 certificate);
- exact canonical challenge encoding and signature domain separation;
- private-key storage guarantees on supported Runner OS platforms;
- attestation revocation propagation SLA and offline behavior;
- whether SEM validates each WSS message signature or relies on authenticated session + TLS;
- enrollment UX and bootstrap nonce delivery mechanism;
- audit schema and retention.

Recommended initial profile: Ed25519 signatures, short-lived enrollment nonce, AI-PM-signed JWS/COSE attestation, TLS-protected WSS with challenge-response, and per-request AI-PM grant validation. Select one exact encoding and key-management profile before implementation.

## 9. Acceptance tests

1. Unenrolled Runner cannot establish an authenticated SEM session.
2. Wrong, expired, reused or revoked enrollment nonce is rejected.
3. A public key without proof of private-key possession cannot enroll.
4. Replaying a WSS challenge signature on another connection is rejected.
5. Changing runner_id, key_version or thumbprint invalidates the attestation/proof.
6. SEM cannot substitute its own key and redeem a bootstrap ticket.
7. AI-PM rejects redemption if its own Runner trust record is revoked, even if SEM presents an old attestation.
8. Old key cannot redeem tickets after rotation/revocation.
9. Lost-key recovery requires a new human-approved enrollment.
10. Key revocation does not automatically release process reservations or count as process exit.
11. No private key, bootstrap secret or delegated MCP token appears in prompt, argv, workspace or ordinary logs.
12. A Runner identity attestation cannot be used as a Task/Run/MCP business grant.

## 10. Status

This is a recommended design candidate. It must be reviewed with the delegated-grant contract and deployment security model. Until approved, Runner identity enrollment and delegated credential bootstrap remain P0 blockers. No code or migration is authorized.
