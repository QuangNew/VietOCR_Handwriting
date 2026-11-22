use axum::{
    Json,
    http::{HeaderValue, StatusCode},
    response::{IntoResponse, Response},
};
use serde::Serialize;

#[derive(Debug)]
pub struct ApiError {
    pub status: StatusCode,
    pub code: String,
    pub retry_after: Option<u32>,
}
impl ApiError {
    pub fn unauthorized() -> Self {
        Self::new(StatusCode::UNAUTHORIZED, "google_session_required")
    }
    pub fn new(status: StatusCode, code: &'static str) -> Self {
        Self {
            status,
            code: code.into(),
            retry_after: None,
        }
    }
    pub fn busy(code: &'static str) -> Self {
        Self {
            status: StatusCode::TOO_MANY_REQUESTS,
            code: code.into(),
            retry_after: Some(3),
        }
    }
    pub fn unavailable(code: &'static str) -> Self {
        Self {
            status: StatusCode::SERVICE_UNAVAILABLE,
            code: code.into(),
            retry_after: Some(3),
        }
    }
}
impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        #[derive(Serialize)]
        #[serde(rename_all = "camelCase")]
        struct Payload {
            error: String,
            retry_after_seconds: Option<u32>,
        }
        let mut response = (
            self.status,
            Json(Payload {
                error: self.code,
                retry_after_seconds: self.retry_after,
            }),
        )
            .into_response();
        if let Some(seconds) = self.retry_after {
            response
                .headers_mut()
                .insert("retry-after", HeaderValue::from(seconds));
        }
        response
    }
}
