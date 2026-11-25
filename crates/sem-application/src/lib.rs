//! Application orchestration and ports.
//!
//! Adapters are intentionally not implemented until the protocol and SEM
//! persistence schema are reviewed. Platform authority is accessed only
//! through an HTTP port; this crate must never depend on sqlx or Platform
//! persistence crates.

pub mod ports;
