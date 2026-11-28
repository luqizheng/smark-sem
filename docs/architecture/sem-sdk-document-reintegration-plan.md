# SEM SDK Document Reintegration Plan

- Status: **PLAN / NOT EXECUTED** — reintegration itself is intentionally not performed in this round (WP-SEM-P0-CLOSURE-R1 §八: no SDK implementation; keep PR #4 as the stale sibling until the plan is approved).
- Author round: 2026-11-28, WP-SEM-P0-CLOSURE-R1.
- Disposition of this branch today: PR #4 (`docs/sem-sdk-consumer-contract`) is an **older sibling** of PR #3 (`docs/sem-d05-lifecycle-crash-consistency`). It MUST NOT be merged to main directly and MUST NOT be merged into PR #3/#5's history. Reintegration happens by rebasing this branch onto the ratified PR #3/#5 protocol baseline, then refreshing the SDK documents.

## 1. New normative protocol baseline (pin)

| Item | Value |
|---|---|
| smark-sem normative protocol branch | `docs/d05-linux-proof-contract` (PR #5; stacked on PR #3) |
| Baseline HEAD SHA | `36a1fb12fad1…` (2026-11-28, `docs(protocol): close P0-06/P0-07 contract artifacts and D-05 test classification`) |
| CI evidence | `validate-contracts` green on that SHA (runs 46109315080 push + 46109319751 PR sync) |
| Supersedes | the snapshots pinned in the SDK docs: PR #5 `813a0657…`, PR #3 `d4b31a0f…` / `dfe00314…` (all 2026-11-25) |

Everything below is defined at that SHA: six-event callback union, tagged `expected_binding` release request, `release_disposition` on release acceptance, `binding_epoch` on `409 BINDING_ALREADY_ESTABLISHED`, `released_unbound` snapshot state, protocol §7.1/§7.2 and D04-F01..F10 / H48..H51 / H89..H100 / H107.

## 2. Stale references in this branch (exact inventory)

1. `sem-sdk-public-api-design-draft.md` §3.3 release-request field list still documents untagged `expected_binding_epoch` — the single largest staleness. Replaced by `expected_binding: {state: unbound} | {state: bound, binding_epoch}` (strict oneOf; legacy alias schema-rejected).
2. Same file §5 `FencingConflict` description ("Expected binding epoch is stale") — wording must cover the tagged form plus the new `409 BINDING_ALREADY_ESTABLISHED` (dispatch-wins against `expected_binding=unbound`, carrying the actual epoch) and `412` stale-epoch semantics for the bound form.
3. Same file §12 traceability matrix release row — wire model must reference `ExecutionReleaseRequestedEnvelope` with the tagged condition and `ReleaseAcceptanceEnvelope.release_disposition` (`bound_release_accepted` | `unbound_release_fenced`); a duplicate echoes the original disposition.
4. Same file §7 callback boundary and §3 V1 scope — the SEM event catalogue is now a six-way discriminated union; SDK types re-exported from `sem-protocol` must include `UnboundReleaseAppliedEvent` (see §4 below for the boundary).
5. `sem-sdk-and-consumer-integration-contract-draft.md` §6 acceptance item ("stale binding_epoch release is rejected") and §9 item 14 (callback fixture conformance) — fixture set now includes the sixth event and the direction-confusion negatives (D04-F09/F10).
6. `sem-sdk-source-compatibility-audit.md` provenance sections (§9/§13/§14/§15) pin pre-closure SHAs — add a new refresh entry pinning `36a1fb12fad1…`; do NOT rewrite historical entries.
7. All three docs' headers that say the protocol is a five-event draft.

## 3. SDK public API deltas to apply (design-doc level, not implementation)

- `request_release` request type gains a tagged expected-binding enum (Rust shape for review: `ExpectedBinding::Unbound` | `ExpectedBinding::Bound { binding_epoch: u64 }`); no constructor may fabricate an epoch for the unbound case.
- `ReleaseAcceptance` response type gains `release_disposition`; a `duplicate` acceptance echoes the original disposition; a new typed error variant maps `409 BINDING_ALREADY_ESTABLISHED` → `FencingConflict { actual_binding_epoch }` so AI-PM can reconcile and re-release with the bound form.
- The three-method V1 surface is otherwise unchanged: unbound release adds no new HTTP operation, only the tagged request branch.
- Default policy stays no-auto-retry; an ambiguous release linearization is `OutcomeUnknown`, never a guessed disposition.

## 4. Sixth-event handling boundary for the SDK

The SDK is the **Platform→SEM** client. SEM→AI-PM callbacks are out of SDK scope (no callback server in V1, per the API design). Therefore the sixth event affects the SDK only through:

1. `sem-protocol` model re-exports (the SDK must not redefine wire models) — add the `execution.unbound_release_applied` envelope/payload types so any Platform-side logging/inspection of the catalogue stays type-complete;
2. documentation (event catalogue counts, fixture references) — the SDK docs must state that handling the tombstone is an AI-PM consumer obligation, not an SDK behavior;
3. negative boundary: the SDK MUST NOT send or accept an `execution.unbound_release_applied` shape on Platform→SEM request paths.

## 5. D-04 signature and response-verification requirements (unchanged, restated)

- RFC 9421 + RFC 9530 + Ed25519, per-direction service keys, no insecure escape hatch — unchanged by this round.
- Response verification must keep binding `X-SEM-Request-Id` to the authenticated `Idempotency-Key`/`request_id`; `BINDING_ALREADY_ESTABLISHED` bodies may carry `binding_epoch` but the correlation contract is unchanged.
- SDK acceptance must consume the existing D-04 signed 409/404 fixtures plus the new tagged-release fixtures from `tests/protocol/fixtures/payload-fixtures-v1.json` at the pinned SHA.

## 6. AI-PM Cargo workspace compatibility (from the source-compatibility audit)

- Unchanged conclusion: `sem-sdk` (release package `smark-sem-sdk`) reusing `sem-protocol`; tokio 1 + reqwest 0.12 remain candidates, not frozen; no AI-PM dependency on sem-server/sem-infrastructure.
- The Rust 1.88 MSRV gate applies to the **AI-PM callback Inbox canonicalizer** (`canonprims-json` spike), NOT to the SDK client. Do not raise the SDK MSRV because of it. SEM workspace stays at `rust-version = 1.85`.
- Integration seams unchanged: pm-application defines the port, pm-infrastructure adapts the SDK, ai-pm-worker drives the Outbox dispatch loop.

## 7. CI dual-repository dependency validation (to add during reintegration)

1. smark-sem: `validate-contracts` must be green on the pinned baseline SHA (already true) and stay green after the SDK doc refresh commit (docs-only commits still run it via `pull_request` paths — `docs/architecture/**` is NOT in the workflow path filter today; add a workflow trigger for `docs/architecture/sem-sdk-*.md` or accept no CI on doc-only SDK commits and record it).
2. ai-pm: PR #9 carries the standalone real-PostgreSQL acceptance harness (30/30 green, 2026-11-28); SDK reintegration must reference it as the consumer-side acceptance gate, not restate it as SDK evidence.
3. Cross-repo provenance: after rebase, re-run the audit's blob-SHA pinning pass so every `sem-protocol` type the SDK re-exports cites the pinned baseline SHA.
4. No PR merges as part of reintegration; PR #4 stays Draft and re-targets nothing.

## 8. Execution checklist (for the round that performs it)

1. `git rebase --onto docs/d05-linux-proof-contract docs/sem-authority-boundary-convergence docs/sem-sdk-consumer-contract` (or merge-free equivalent chosen at execution time); expect conflicts only in the two refreshed SDK docs and the register/README.
2. Apply §2 inventory edits + §3 type deltas + §4 boundary notes + §5 fixture pointers; add one new provenance section (do not rewrite history).
3. Update `SEM-DOCUMENTATION-COMPLETION-REGISTER.md` and repo `README.md` D-12 entries to the six-event baseline.
4. Push; record that PR #4 doc-only commits may run no CI (see §7.1) and state that honestly in the PR description.
5. Re-verify: no reference in this branch to the untagged `expected_binding_epoch` as a supported request form remains (grep gate), and the pinned baseline SHA appears in every snapshot header.
