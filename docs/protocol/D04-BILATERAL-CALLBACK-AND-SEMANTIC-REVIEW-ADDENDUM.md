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


## 7. Follow-up contract hardening — 2026-11-25

The SEM Draft has now applied the following contract-level corrections:

- Event acknowledgement uses `execution_event_sequence`, matching the event envelope and AI-PM cursor; the ambiguous legacy `event_sequence` property is rejected by a positive/negative ACK fixture.
- Runner key version is named `runner_key_version` consistently and is required alongside `boot_id` and `supervisor_instance_id` on delivery, process, release and uncertainty observations.
- Process observation `exited` requires exact process identity and exit evidence with exactly one of `exit_code` or `exit_signal`.
- Release state `process_exited` requires `process_exit_evidence_id`.
- Added D04-H40..H47 acceptance scenarios and executable schema-fixture mutations for ambiguous ACK field, both exit discriminators, missing exit evidence and missing release evidence reference.
- The AI-PM PR #9 addendum now carries the same proposed ACK field and identity/evidence expectations.

The first CI run against an intermediate commit exposed a missing `supervisor_instance_id` property in the uncertainty payload schema. That defect was corrected in commit `6aaf3949bbd2960d5e800f6934b2aa79127aa483`. The latest HEAD's CI result has not yet been observed; do not treat the correction as validated until the workflow passes.

### Updated disposition of findings

- P0-BI-01: **SEM-side schema/protocol alignment applied; bilateral closure remains pending AI-PM adoption and CI/interoperability proof.**
- P0-BI-04: **schema-level required identity fields and selected cross-field constraints added; full cross-event evidence-reference and current-binding semantic validation remain open.**
- P0-BI-02 and P0-BI-03: **open** — exact AI-PM DDL, PostgreSQL atomicity/concurrency and cross-repository transaction fixtures remain unimplemented/unproven.

No runtime code, database migration or route was changed. No PR was merged or ratified.


## 8. AI-PM Inbox DDL/source audit update — 2026-11-25

AI-PM PR #9 now contains [Exact DDL and Concurrency Design](https://github.com/luqizheng/ai-pm/blob/docs/sem-02e-architecture-convergence/docs/architecture/server-execution-management/sem-callback-inbox-ddl-and-concurrency-design.md), based on a source audit of its PR base commit `d0e72fa6805aebeadf1b282e430deba493072fd6`, including the squashed baseline DDL, `pm-application/src/ingestion.rs`, and `migrations/0013_task_run_event.sql`.

### Corrected P0-BI-02 facts

The earlier wording that a new partial unique index is needed for global SEM event-ID uniqueness was inaccurate. The existing `integration.inbound_event.id` is already a global UUID primary key. The proposed mapping is therefore `SEM event_id → integration.inbound_event.id`; no second global unique index is needed.

The actual missing storage invariants are:

- unique `(execution_id, execution_event_sequence)` for SEM events;
- a nonnegative per-attempt contiguous cursor on `delivery.task_run`;
- an append-only `sem_infrastructure_observed` Run event type and unique sequence slot;
- exact tenant/project/execution identity enforcement;
- service-principal identity without HumanActor synthesis;
- canonical payload fingerprint agreement.

The existing generic `submit_event()` is definitively unsuitable: it hashes a language serializer representation and inserts an `integration.job(job_type='ai_analysis')` in the same transaction. The SEM-specific callback port must bypass it.

The new AI-PM design proposes RFC 8785 JCS UTF-8 bytes followed by SHA-256 for payload equality, explicit Run-row locking, and atomic Inbox + Run observation + cursor commit. These are proposals, not yet bilateral ratification. The proposed FK still needs a final composite tenant/project/run proof; `run_kind='delivery'` requires locked-row semantic validation or an equivalent database invariant.

### P0-BI-03 executable transaction/concurrency scope

The AI-PM design now specifies 24 deterministic PostgreSQL acceptance cases, including:

- same event ID/body duplicate and changed-body/changed-sequence conflicts;
- same execution sequence with different event IDs under concurrency;
- N+1 before N and concurrent N/N+1;
- crash before commit and crash after commit before ACK;
- wrong tenant/project, unknown execution and review-run non-enumeration;
- stale binding/key/boot identity and missing exit/release evidence;
- no `ai_analysis` job, no HumanActor fabrication, and no Task/business success mutation;
- preservation of generic non-SEM ingestion semantics.

This closes the **design specification gap**, not the implementation-proof gap. No live PostgreSQL two-connection test, migration replay, bilateral fixture runner, callback implementation, or ACK interoperability test has been run.

### Updated P0 disposition

- P0-BI-01: SEM-side ACK field is hardened to `execution_event_sequence`; AI-PM draft now adopts it. Bilateral executable response/interop proof remains open.
- P0-BI-02: **DDL proposal now exists and corrects the global-ID uniqueness analysis.** Still open pending live catalog/migration replay, final composite identity constraints, ratification, and PostgreSQL proof.
- P0-BI-03: **24-case executable test specification now exists.** Still open pending actual two-connection PostgreSQL tests and cross-repository fixture execution.
- P0-BI-04: schema-level identity fields exist; exact current-binding and evidence-reference semantic validation remains open.

No runtime code, route, migration, database schema, or deployment was changed. No PR was merged or ratified. D-04 remains **CHANGES REQUIRED / NOT READY FOR IMPLEMENTATION**.


## 9. AI-PM PR #9 follow-up re-review — 2026-11-25

The SEM reviewer directly revised the AI-PM PR #9 documentation branch after re-reading the latest DDL proposal. Current AI-PM PR #9 head at this update is `fb3317474c7326759a51eda19a9bfd0e0011d66b`.

Applied documentation corrections:

- `task_run_event` CHECK now explicitly requires `dedupe_tag IS NOT NULL` before checking its length; PostgreSQL CHECK's three-valued logic can otherwise allow NULL.
- Inbox source/sequence CHECK explicitly requires `source IS NOT NULL` so NULL cannot make the entire CHECK expression UNKNOWN and pass.
- The callback transaction is specified at READ COMMITTED. Higher-isolation serialization/snapshot conflicts retry the whole transaction with the exact same event identity/body.
- Inbox insertion uses `INSERT ... ON CONFLICT DO NOTHING RETURNING id`, followed by fresh-statement lookups of both global event_id and (execution_id, execution_event_sequence). The design no longer suggests issuing SELECT inside a transaction aborted by an ordinary unique violation.
- Duplicate is returned only when both uniqueness lookups resolve to the same row and execution ID, sequence and JCS hash match. Conflicting winners, changed tuple/body, same sequence/different event ID, or an unlocatable conflict fail closed without ACK.
- Added INBOX-25..28 for cross-Run global event-ID races, same-sequence competition, conflict-winner lookup and invariant-failure rollback.

This closes the identified **documentation algorithm gaps**, not the database proof. The candidate DDL remains unratified and no migration, route or runtime code was changed. The latest AI-PM commit has no observed PR workflow run. Required next evidence remains live PostgreSQL migration replay, source/catalog verification, two-connection concurrency tests, and bilateral callback/ACK tests.

### Updated bilateral disposition

- P0-BI-02: SQL CHECK NULL issue corrected in Draft; DDL/source/migration proof remains open.
- P0-BI-03: unique-conflict transaction algorithm now defines a recoverable READ COMMITTED path and four additional concurrency cases; actual PostgreSQL and bilateral execution remain open.
- Overall D-04 remains **CHANGES REQUIRED / NOT READY FOR IMPLEMENTATION**.


## 10. Full-envelope replay identity and shared JCS fixture follow-up — 2026-11-25

AI-PM PR #9 now carries a two-hash callback identity contract:
- `payload_hash`: JCS SHA-256 of the payload object.
- `event_envelope_hash`: JCS SHA-256 of the complete authenticated event envelope (`event_id`, `event_type`, `schema_version`, `occurred_at`, `execution_id`, `execution_event_sequence`, `payload`).

The SEM repository added the shared vector `tests/protocol/fixtures/platform-sem-callback-envelope-jcs-v1.json` at commit `ad09195d44d557b5a5d174d6bdfdef687dcef4b5`. SEM Python and Node independently verify exact canonical bytes and both hashes, and prove that changing `event_type`, `occurred_at` or optional `correlation_id` changes the envelope hash while member reordering does not. CI runs #208 and #209 passed all ten validation steps.

AI-PM PR #9 pins this fixture and adds INBOX-35, requiring the eventual Rust implementation to match it exactly. The vector is ASCII/integer-only and does not close full RFC 8785 Unicode/numeric edge coverage or production Rust parser behavior.

## 11. PostgreSQL CHECK correction follow-up

The latest AI-PM DDL review found that the SEM source CHECK needed explicit `IS NOT NULL` guards for both hashes: regex comparisons against NULL evaluate to UNKNOWN, and PostgreSQL CHECK accepts UNKNOWN. The candidate SQL was rewritten with explicit SEM/non-SEM branch grouping, both non-NULL hash guards and the existing `source IS NOT NULL` guard.

AI-PM PR #9 adds INBOX-36..38 for NULL payload_hash, NULL event_envelope_hash and the complete SQL parse/three-valued-logic truth table. Its bilateral review addendum now records 38 acceptance cases. Latest observed AI-PM PR #9 head: `4eaaca0005f29547f07e6b4a9a7e438aac25e84b`.

These are documentation and deterministic contract-test improvements only. The AI-PM DDL remains unratified pending actual PostgreSQL parse/replay, catalog inspection, two-connection concurrency and crash-atomicity evidence. No runtime implementation or migration has been added; no PR has been merged. D-04 remains **CHANGES REQUIRED / NOT READY FOR IMPLEMENTATION**.


## 12. Optional correlation_id correction

The Platform–SEM `EventBase` schema permits an optional top-level `correlation_id`. The first full-envelope hash field list omitted it, leaving an authenticated metadata mutation outside replay identity. The shared fixture now includes `correlation_id`; Python and Node verify its presence in canonical bytes and assert that changing it changes `event_envelope_hash`. The canonical fixture is pinned at `smark-sem@ad09195d44d557b5a5d174d6bdfdef687dcef4b5`.

The AI-PM contract now states that the hash covers every schema-defined envelope field present, including optional correlation_id; absent optional fields are omitted and unknown fields are rejected before hashing. This closes the design-level field-list omission only. Production Rust implementation, PostgreSQL replay/concurrency evidence and bilateral live callback tests remain open.
