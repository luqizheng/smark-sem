# SEM Modular-Monolith Skeleton

- Status: **Initial compile-oriented skeleton; not production-ready**
- Repository: luqizheng/smark-sem
- Branch: feat/sem-modular-monolith-skeleton

## Intent

Create one Rust workspace and one deployable SEM server. The crates are logical boundaries inside a modular monolith, not independently deployed microservices.

## Workspace layout

- apps/sem-server — binary entry point and process configuration
- crates/sem-domain — SEM-owned Runner/session/process primitives only
- crates/sem-protocol — versioned transport envelopes and constants
- crates/sem-application — orchestration and outbound ports
- crates/sem-infrastructure — HTTP server and future HTTP/WSS/database adapters

## Deliberately implemented

- HTTP process bootstrap
- GET /health/live liveness endpoint
- Explicit protocol version constants and generic message envelopes
- SEM-owned identity and supervision-mode primitives
- PlatformApi application port that makes the Platform HTTPS boundary explicit

## Deliberately not implemented

- No Platform PostgreSQL dependency or connection string
- No SEM database pool or migrations yet
- No Runner WSS listener or ticket verification yet
- No service JWT signing/verification yet
- No Outbox/Inbox handlers yet
- No Claim, Lease Renewal, process observation, command or E6 state mutation
- No process spawn/terminate logic yet
- No readiness endpoint; the service must not report readiness before required adapters exist
- No Docker/Compose deployment or production configuration yet

## Authority guardrails

- sem-application depends on ports, not Platform persistence.
- sem-infrastructure must never add a Platform SQL adapter.
- Run/Lease/Generation/HIR/Barrier business state remains in ai-pm.
- New SEM persistence is limited to the seven logical tables in the ownership and protocol documents.
- All protocol mutations must use stable idempotency keys and reconcile unknown outcomes.
