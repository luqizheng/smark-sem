use std::net::SocketAddr;

use axum::{routing::get, Json, Router};
use serde::Serialize;
use tokio::net::TcpListener;

#[derive(Serialize)]
struct Liveness {
    status: &'static str,
}

async fn live() -> Json<Liveness> {
    Json(Liveness { status: "alive" })
}

/// Starts the SEM HTTP process with only a liveness endpoint.
///
/// Readiness, Platform connectivity, database health and business routes are
/// intentionally not reported as ready until their adapters are implemented.
pub async fn serve(bind_addr: SocketAddr) -> Result<(), std::io::Error> {
    let app = Router::new().route("/health/live", get(live));
    let listener = TcpListener::bind(bind_addr).await?;
    tracing::info!(%bind_addr, "SEM liveness server listening");
    axum::serve(listener, app).await
}
