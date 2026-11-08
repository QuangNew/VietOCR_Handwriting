pub mod auth;
pub mod camera;
pub mod config;
pub mod error;
pub mod mjpeg;
pub mod panel;
pub mod panel_canvas;
pub mod telemetry;

use auth::{Auth, Identity};
use axum::{
    Json, Router,
    extract::{Path, State},
    http::{HeaderMap, HeaderValue},
    middleware,
    response::Response,
    routing::{get, post},
};
use camera::CameraService;
use config::Config;
use error::ApiError;
use std::sync::Arc;
use telemetry::PanelUpdate;
use tokio::sync::{Semaphore, watch};

pub struct App {
    auth: Arc<Auth>,
    camera: CameraService,
    panel: watch::Receiver<PanelUpdate>,
    auth_admission: Semaphore,
}
impl App {
    pub fn new(
        config: &Config,
        panel: watch::Receiver<PanelUpdate>,
    ) -> Result<Arc<Self>, reqwest::Error> {
        Ok(Arc::new(Self {
            auth: Arc::new(Auth::new(config.auth.clone())?),
            camera: CameraService::new(config),
            panel,
            auth_admission: Semaphore::new(32),
        }))
    }
    pub fn start_capture(&self) {
        self.camera.start();
    }
    async fn identity(&self, headers: &HeaderMap) -> Result<Identity, ApiError> {
        let _permit = self
            .auth_admission
            .try_acquire()
            .map_err(|_| ApiError::busy("auth_capacity"))?;
        self.auth.authenticate(headers).await
    }
}
pub fn router(app: Arc<App>) -> Router {
    Router::new()
        .route("/health/live", get(|| async { Json(serde_json::json!({ "status": "alive", "apiVersion": "2", "phase": "foundation" })) }))
        .route("/api/v2/session", get(session))
        .route("/api/v2/cameras", get(cameras))
        .route("/api/v2/cameras/{id}/stream", get(stream))
        .route("/api/v2/cameras/{id}/snapshots", post(snapshot))
        .route("/api/v2/server/status", get(status))
        .layer(tower_http::limit::RequestBodyLimitLayer::new(16 * 1024))
        .layer(middleware::from_fn(|request: axum::extract::Request, next: middleware::Next| async move {
            let mut response = next.run(request).await;
            response.headers_mut().insert("cache-control", HeaderValue::from_static("no-store, private"));
            response.headers_mut().insert("x-content-type-options", HeaderValue::from_static("nosniff"));
            response
        }))
        .with_state(app)
}
async fn session(
    State(app): State<Arc<App>>,
    headers: HeaderMap,
) -> Result<Json<serde_json::Value>, ApiError> {
    let identity = app.identity(&headers).await?;
    Ok(Json(
        serde_json::json!({ "account": identity.account, "authProvider": "google", "apiVersion": "2",
        "quotaTimezone": vietocr_contracts::QUOTA_TIMEZONE, "cameraSource": "raspberry", "cameras": app.camera.views(),
        "ocrAvailable": false }),
    ))
}
async fn cameras(
    State(app): State<Arc<App>>,
    headers: HeaderMap,
) -> Result<Json<Vec<camera::CameraView>>, ApiError> {
    app.identity(&headers).await?;
    Ok(Json(app.camera.views()))
}
async fn stream(
    State(app): State<Arc<App>>,
    Path(id): Path<String>,
    headers: HeaderMap,
) -> Result<Response, ApiError> {
    let identity = app.identity(&headers).await?;
    app.camera
        .stream(app.camera.camera(&id)?, app.auth.clone(), identity)
}
async fn snapshot(
    State(app): State<Arc<App>>,
    Path(id): Path<String>,
    headers: HeaderMap,
) -> Result<Response, ApiError> {
    let identity = app.identity(&headers).await?;
    app.camera
        .snapshot(app.camera.camera(&id)?, &identity)
        .await
}
async fn status(
    State(app): State<Arc<App>>,
    headers: HeaderMap,
) -> Result<Json<PanelUpdate>, ApiError> {
    app.identity(&headers).await?;
    Ok(Json(app.panel.borrow().clone()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{
        body::Body,
        http::{Request, StatusCode},
    };
    use tower::ServiceExt;
    #[tokio::test]
    async fn health_needs_no_auth_but_camera_status_and_session_fail_closed() {
        let (_, rx) = watch::channel(PanelUpdate::default());
        let app = App::new(&Config::default(), rx).unwrap();
        let routes = router(app);
        for path in [
            "/api/v2/cameras",
            "/api/v2/server/status",
            "/api/v2/session",
            "/api/v2/cameras/desk/stream",
        ] {
            let response = routes
                .clone()
                .oneshot(Request::builder().uri(path).body(Body::empty()).unwrap())
                .await
                .unwrap();
            assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
            assert_eq!(
                response.headers().get("cache-control").unwrap(),
                "no-store, private"
            );
        }
        let response = routes
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v2/cameras/desk/snapshots")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
        let response = routes
            .oneshot(
                Request::builder()
                    .uri("/health/live")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
    }
    #[tokio::test]
    async fn permanent_api_key_or_query_token_cannot_open_camera() {
        let (_, rx) = watch::channel(PanelUpdate::default());
        let app = App::new(&Config::default(), rx).unwrap();
        let response = router(app)
            .oneshot(
                Request::builder()
                    .uri("/api/v2/cameras?token=not-a-credential")
                    .header("authorization", "Bearer voc_this_is_a_legacy_key_1234567")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    }
}
