//! SEM-owned execution-side domain primitives.
//!
//! Platform business entities (Project, Task, Run, Lease, Generation, HIR)
//! deliberately do not live here. SEM stores references to Platform IDs and
//! owns only its Runner/session/process-side concepts.

use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct RunnerId(pub Uuid);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct ConnectionId(pub Uuid);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct DispatchOperationId(pub Uuid);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SupervisionMode {
    Unattended,
    Supervised,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProcessObservationKind {
    Started,
    Exited,
    Uncertain,
    Reconciled,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn supervision_mode_uses_stable_wire_names() {
        assert_eq!(serde_json::to_string(&SupervisionMode::Unattended).unwrap(), "\"unattended\"");
        assert_eq!(serde_json::to_string(&SupervisionMode::Supervised).unwrap(), "\"supervised\"");
    }
}
