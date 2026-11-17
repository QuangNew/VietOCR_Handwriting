//! Pi authorization and bounded byte relay. Compute is the DB credential boundary.
use crate::{
    auth::{Identity, bounded_bytes},
    config::ComputeConfig,
    error::ApiError,
};
use axum::{
    body::Body,
    http::{HeaderMap, StatusCode},
};
use reqwest::Method;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::sync::{Mutex, Semaphore};
use uuid::Uuid;
use vietocr_contracts::ImageIntent;

pub struct Compute {
    config: ComputeConfig,
    http: reqwest::Client,
    token: String,
    uploads: Semaphore,
    requests: Semaphore,
    last_scale: Mutex<Instant>,
}
#[derive(Deserialize, Default)]
#[serde(default, rename_all = "camelCase", deny_unknown_fields)]
pub struct Command {
    pub generation: u64,
}
impl Compute {
    pub fn public_origin(&self) -> &str {
        &self.config.public_results_origin
    }
    pub fn new(config: ComputeConfig) -> Result<Arc<Self>, String> {
        let token = std::fs::read_to_string(&config.token_file)
            .map_err(|_| "Cannot read compute machine token file")?
            .trim()
            .to_owned();
        if !(32..=256).contains(&token.len())
            || !token
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
        {
            return Err("Compute machine token must be 32..256 random URL-safe characters".into());
        }
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs(25))
            .connect_timeout(Duration::from_secs(3))
            .redirect(reqwest::redirect::Policy::none())
            .pool_max_idle_per_host(8)
            .build()
            .map_err(|_| "Cannot create compute transport")?;
        Ok(Arc::new(Self {
            uploads: Semaphore::new(config.concurrent_uploads),
            requests: Semaphore::new(32),
            config,
            http,
            token,
            last_scale: Mutex::new(Instant::now() - Duration::from_secs(90)),
        }))
    }
    async fn response(&self, response: reqwest::Response) -> Result<Value, ApiError> {
        let status = response.status();
        let bytes = bounded_bytes(response, 256 * 1024)
            .await
            .map_err(|_| ApiError::unavailable("compute_response_invalid"))?;
        let value: Value = serde_json::from_slice(&bytes)
            .map_err(|_| ApiError::unavailable("compute_response_invalid"))?;
        if !status.is_success() {
            let code = value["error"]
                .as_str()
                .filter(|s| {
                    s.len() <= 80
                        && s.bytes()
                            .all(|b| b.is_ascii_lowercase() || b == b'_' || b.is_ascii_digit())
                })
                .unwrap_or("compute_unavailable");
            return Err(ApiError {
                status,
                code: code.into(),
                retry_after: Some(3),
            });
        }
        Ok(value)
    }
    pub async fn call(&self, path: &str, body: Value) -> Result<Value, ApiError> {
        let _slot = self
            .requests
            .try_acquire()
            .map_err(|_| ApiError::busy("compute_capacity"))?;
        let response = self
            .http
            .post(format!(
                "{}/api/internal/v2/{path}",
                self.config.origin.trim_end_matches('/')
            ))
            .bearer_auth(&self.token)
            .json(&body)
            .send()
            .await
            .map_err(|_| ApiError::unavailable("compute_unreachable"))?;
        self.response(response).await
    }
    pub async fn create(
        &self,
        identity: &Identity,
        intent: ImageIntent,
    ) -> Result<Value, ApiError> {
        intent
            .validate(64 * 1024 * 1024)
            .map_err(|e| ApiError::new(StatusCode::BAD_REQUEST, e))?;
        let mut body = serde_json::to_value(intent)
            .map_err(|_| ApiError::new(StatusCode::BAD_REQUEST, "invalid_intent"))?;
        body["userId"] = json!(identity.claims.sub);
        body["sessionId"] = json!(identity.claims.session_id);
        self.call("intents", body).await
    }
    pub async fn command(
        self: &Arc<Self>,
        id: Uuid,
        action: &str,
        identity: &Identity,
        cmd: Command,
    ) -> Result<Value, ApiError> {
        let result=self.call(&format!("intents/{id}/{action}"),json!({"userId":identity.claims.sub,"sessionId":identity.claims.session_id,"generation":cmd.generation})).await;
        if action == "grant"
            && result
                .as_ref()
                .is_err_and(|e| e.code == "compute_queue_busy")
        {
            let mut last = self.last_scale.lock().await;
            if last.elapsed() > Duration::from_secs(60) {
                *last = Instant::now();
                let compute = self.clone();
                tokio::spawn(async move {
                    if let Ok(capacity) = compute.call("capacity", json!({})).await {
                        let desired = capacity["workers"]
                            .as_u64()
                            .unwrap_or(0)
                            .saturating_add(1)
                            .min(256);
                        let _ = compute
                            .call("scale", json!({"desiredWorkers":desired}))
                            .await;
                    }
                });
            }
        }
        if action == "result-ticket" {
            let value = result?;
            let result_url = value["resultUrl"]
                .as_str()
                .ok_or_else(|| ApiError::unavailable("result_origin_invalid"))?;
            let allowed = reqwest::Url::parse(&self.config.public_results_origin)
                .map_err(|_| ApiError::unavailable("result_origin_invalid"))?;
            let actual = reqwest::Url::parse(result_url)
                .map_err(|_| ApiError::unavailable("result_origin_invalid"))?;
            if actual.origin() != allowed.origin()
                || actual.path() != format!("/api/v2/results/{id}")
                || actual.query().is_some()
                || actual.fragment().is_some()
                || !actual.username().is_empty()
                || actual.password().is_some()
            {
                return Err(ApiError::unavailable("result_origin_invalid"));
            }
            return Ok(value);
        }
        result
    }
    pub async fn content(
        &self,
        id: Uuid,
        identity: &Identity,
        headers: HeaderMap,
        body: Body,
    ) -> Result<Value, ApiError> {
        let _slot = self
            .uploads
            .try_acquire()
            .map_err(|_| ApiError::busy("uploads_busy"))?;
        let number = |name: &str| {
            headers
                .get(name)
                .and_then(|v| v.to_str().ok())
                .and_then(|v| v.parse::<u64>().ok())
        };
        let length = number("content-length")
            .filter(|v| (1..=1048576).contains(v))
            .ok_or_else(|| ApiError::new(StatusCode::BAD_REQUEST, "chunk_length_required"))?;
        let offset = number("upload-offset")
            .ok_or_else(|| ApiError::new(StatusCode::BAD_REQUEST, "upload_offset_required"))?;
        let generation = number("x-ocr-generation")
            .filter(|v| *v > 0)
            .ok_or_else(|| ApiError::new(StatusCode::BAD_REQUEST, "generation_required"))?;
        let response = self
            .http
            .request(
                Method::PUT,
                format!(
                    "{}/api/internal/v2/intents/{id}/content",
                    self.config.origin.trim_end_matches('/')
                ),
            )
            .bearer_auth(&self.token)
            .header("x-ocr-user", identity.claims.sub.to_string())
            .header("x-ocr-session", identity.claims.session_id.to_string())
            .header("x-ocr-generation", generation)
            .header("upload-offset", offset)
            .header("content-length", length)
            .header("content-type", "application/octet-stream")
            .body(reqwest::Body::wrap_stream(body.into_data_stream()))
            .send()
            .await
            .map_err(|_| ApiError::unavailable("upload_interrupted"))?;
        self.response(response).await
    }
}
