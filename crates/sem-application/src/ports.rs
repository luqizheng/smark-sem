use async_trait::async_trait;
use sem_domain::{DispatchOperationId, RunnerId};

#[derive(Debug, Clone)]
pub struct ClaimRequest {
    pub claim_request_id: String,
    pub runner_id: RunnerId,
    pub dispatch_operation_id: DispatchOperationId,
    pub task_id: Option<String>,
}

#[derive(Debug, Clone)]
pub enum ClaimResult {
    Claimed { run_id: String, generation: i32 },
    NoWork,
}

/// Platform is the authority for eligibility, Claim, Lease and Generation.
/// The implementation belongs in sem-infrastructure and uses HTTPS only.
#[async_trait]
pub trait PlatformApi: Send + Sync {
    async fn claim(&self, request: ClaimRequest) -> Result<ClaimResult, PlatformApiError>;
}

#[derive(Debug, thiserror::Error)]
pub enum PlatformApiError {
    #[error("platform outcome is unknown; retry with the same idempotency key")]
    OutcomeUnknown,
    #[error("platform rejected the request: {0}")]
    Rejected(String),
}
