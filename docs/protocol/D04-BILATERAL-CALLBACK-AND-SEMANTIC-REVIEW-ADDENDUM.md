# D-04 Bilateral Callback and Semantic-Conformance Review Addendum

- Review date: 2026-11-25
- SEM review branch: `docs/sem-d05-lifecycle-crash-consistency`
- SEM reviewed HEAD: `3736f39dea03850b7340f6e7e8487ebd1b33c63f`
- AI-PM review branch: `docs/sem-02e-architecture-convergence`
- AI-PM reviewed HEAD: `1e58b435fdc8b73bed41aef1894b2069f4b4fb82`
- Disposition: **CHANGES REQUIRED**
- Scope: D-04 contract consistency, fixtures/crypto CI evidence, SEM callback OpenAPI/JSON Schema, and AI-PM Inbox proposal.
- This is a documentation-only bilateral review. It is not a security certification, implementation test, ratification, or implementation authorization.

## 1. Verified current evidence

The SEM Protocol Contract Validation workflow passed on the reviewed SEM HEAD:

- Workflow run: [#54](https://github.com/luqizheng/smark-sem/actions/runs/45571938994)
- Commit: `3736f39dea03850b7340f6e7e8487ebd1b33c63f`
- All ten substantive steps completed, including OpenAPI 3.1/external-reference lint, JSON Schema meta-schema/discriminator validation, deterministic cryptographic vector checks, positive/negative payload fixtures, and independent Node JCS/Ed25519 verification.

This is meaningful contract-shape and deterministic-vector evidence. It does **not** prove a live HTTP signature implementation, replay store, WSS challenge lifecycle, event producer/receiver transaction, process-evidence semantics, or cross-repository interoperability.

The SEM fixture inventory covers 26 positive payload examples (19 Runner WSS application messages, 2 Platform requests, 5 SEM infrastructure events) and 78 schema-negative mutations. The cryptographic fixtures are deterministic TEST-ONLY examples; their private seeds must never be deployed.

## 2. Bilateral callback proposal — direction accepted, details not ratified

The AI-PM PR #9 draft proposes:

1. A dedicated service-authenticated `POST /internal/ai-pm/v1/sem-events` route; do not reuse the human-authenticated generic `POST /api/v1/events`.
2. A SEM-specific application port that writes the existing `integration.inbound_event` ledger without enqueuing `integration.job(job_type='ai_analysis')`.
3. `execution_id == delivery.task_run.id` for exactly one AI-PM delivery attempt.
4. A contiguous `execution_event_sequence` cursor on that attempt, with Inbox insert, append-only Run observation and cursor advance committed in one transaction.
5. Success ACK only after commit; retries retain the same event_id and exact body.
6. Infrastructure observations never set TaskStatus, Submitted, Completed, approval or acceptance.

This is directionally consistent with SEM authority boundaries. The proposal is still Draft and its open decisions OI-01..OI-06 remain unresolved. No AI-PM route, application code, migration or runtime change was made.

## 3. P0 findings requiring closure

### P0-BI-01 — Callback ACK sequence field is ambiguous across the two drafts

The SEM event envelope uses `execution_event_sequence`. The AI-PM transaction algorithm and cursor also use `execution_event_sequence`, but the current SEM acknowledgement schema returns `event_sequence`.

Required correction:
- Prefer returning `execution_event_sequence` in the ACK, matching the request and cursor terminology.
- If retaining `event_sequence`, explicitly define it as the exact echo of the accepted event's `execution_event_sequence`; do not let it be interpreted as the Runner journal sequence or WSS message sequence.
- Freeze the exact ACK JSON example, schema, OpenAPI response and AI-PM response implementation contract together.
- ACK must include the contiguous cursor and disposition; it is emitted only after the Inbox + Run observation + cursor transaction commits.

### P0-BI-02 — Shared Inbox uniqueness and transaction DDL are still recommendations, not a frozen storage contract

The AI-PM proposal recommends reuse of `integration.inbound_event`, plus a partial unique index for global SEM event-ID uniqueness and a `task_run.sem_last_event_sequence` cursor. It does not yet provide the exact migration DDL or prove the target constraints against the current full migration chain.

Required closure:
- Pin the exact current AI-PM migration head and source baseline.
- Specify exact partial unique index predicate and ensure it cannot collide with existing non-SEM sources.
- Specify the FK/tenant/project/run-kind constraints for the service actor and attempt mapping.
- Define canonical payload hashing bytes precisely (the exact received JSON bytes versus canonicalized JSON); both peers must produce the same conflict decision.
- Define the unique invariant for `(execution_id, execution_event_sequence)`, including whether it is enforced by a dedicated observation column/index or proven by serialized row-lock + append-only ledger constraints.
- Prove concurrent same-event and same-sequence deliveries with two-connection PostgreSQL tests.
- Prove Inbox row, Run observation and cursor update are atomic and rollback together.

### P0-BI-03 — Event identity and sequence conflict algorithm needs a fully executable bilateral fixture

The proposal's algorithm is sound in outline, but the current SEM CI validates JSON shape only. No cross-repository fixture currently exercises the receiver's transaction and ACK behavior.

Required closure includes:
- same event_id + same body + same sequence → duplicate ACK;
- same event_id + changed body or sequence → 409 conflict;
- same execution sequence + different event_id → 409 conflict;
- N+1 before N → gap response with expected N and no cursor advance;
- N then replay N+1 → accepted;
- concurrent duplicates → one durable application;
- crash before commit → no partial state/no success ACK;
- crash after commit before response → retry returns duplicate ACK;
- wrong tenant/project/run-kind and unknown execution → non-enumerating 404;
- no `ai_analysis` job and no HumanActor fabrication;
- infrastructure event cannot mutate Task status or formal human decisions.

### P0-BI-04 — Event schema shape does not yet enforce the D-05 identity/evidence tuple

The current strict event schemas reject unknown fields and missing basic required fields, but several identity and cross-field relationships remain narrative-only. Examples requiring an explicit decision and fixture:
- `ProcessObservedPayload.runner_key_version` is optional although the binding identity includes a Runner key version.
- Release/process evidence must be tied to the same execution, runner, boot, supervisor instance, binding epoch and launch/containment identity; independent field validity is insufficient.
- `release_state=process_exited` must require a verifiable process-exit evidence reference.
- Exit evidence must define whether exactly one of exit_code or exit_signal is required, and how unknown exit status is represented.
- A stale binding_epoch or mismatched Runner identity must be rejected by semantic validation, not merely stored as an observation.
- The producer mapping from each field to SEM ledger / Runner Supervisor durable evidence is not yet documented field-by-field.

Required closure: publish reusable identity definitions, field provenance mapping, semantic validation rules and positive/negative cross-field fixtures. Do not claim D-05 process-exit safety from JSON Schema shape alone.

## 4. HTTP signature and WSS transcript — remaining wire-level gaps

The primitive selection is approved, and deterministic vectors now pass. The following remain open:

- OpenAPI does not fully describe signed response headers and the response verification contract for every operation, including callback ACKs.
- The exact operation-specific RFC 9421 covered-component set, key IDs, response correlation headers, freshness bounds and nonce-retention policy are not fully frozen.
- The current security scheme is a useful header representation but does not itself specify interoperable RFC 9421 parsing/canonicalization behavior.
- WSS JCS cross-language verification currently covers the fixed ASCII/integer fixture subset, not the full RFC 8785 edge space (UTF-16 property ordering, escaping, Unicode, number serialization and malformed/non-canonical inputs).
- Challenge single-use/replay, key-version overlap/revocation and TLS audience/authority binding need executable lifecycle tests.

These are not reasons to change the approved algorithm families; they are reasons P0-01/P0-02 remain open.

## 5. Required bilateral decision sequence

1. AI-PM and SEM owners ratify the exact execution_id-to-attempt mapping.
2. Ratify shared Inbox reuse only after exact DDL, global event-ID uniqueness, payload-hash semantics and transaction tests are specified. Otherwise select the dedicated Inbox alternative; do not dual-write.
3. Align ACK field names and all error codes/statuses between OpenAPI, JSON Schema and AI-PM draft.
4. Freeze event identity/evidence provenance and cross-field invariants against D-05.
5. Add cross-repository fixtures and PostgreSQL transaction/concurrency tests.
6. Re-review HTTP signature responses/replay and full JCS edge coverage.
7. Re-run independent review against both updated PR heads.

## 6. Explicit non-goals

- No implementation, migration, route, database, Docker, deployment or runtime changes.
- No PR merge or ratification.
- No claim that the successful schema/vector workflow is end-to-end interoperability proof.

**Final disposition: D-04 remains CHANGES REQUIRED / NOT READY FOR IMPLEMENTATION.**
