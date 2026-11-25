//! Versioned wire-level protocol primitives.
//!
//! Normative semantics are documented in
//! docs/protocol/PLATFORM-SEM-RUNNER-PROTOCOL-V1.md.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

pub const HTTP_API_VERSION: &str = "v1";
pub const RUNNER_WSS_SUBPROTOCOL: &str = "smark.runner.v1";
pub const SCHEMA_VERSION_V1: u16 = 1;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RunnerMessage<T> {
    pub message_id: Uuid,
    pub message_type: String,
    pub schema_version: u16,
    pub connection_id: Uuid,
    pub connection_epoch: u64,
    pub sent_at: DateTime<Utc>,
    pub correlation_id: Option<Uuid>,
    pub payload: T,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PlatformAggregate {
    pub aggregate_type: String,
    pub id: Uuid,
    pub project_id: Uuid,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PlatformEvent<T> {
    pub event_id: Uuid,
    pub event_type: String,
    pub schema_version: u16,
    pub occurred_at: DateTime<Utc>,
    pub aggregate: PlatformAggregate,
    pub correlation_id: Uuid,
    pub payload: T,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn protocol_versions_are_explicit() {
        assert_eq!(HTTP_API_VERSION, "v1");
        assert_eq!(RUNNER_WSS_SUBPROTOCOL, "smark.runner.v1");
        assert_eq!(SCHEMA_VERSION_V1, 1);
    }
}
