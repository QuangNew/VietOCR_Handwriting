use crate::{
    auth::Identity,
    config::{CameraConfig, Config},
    error::ApiError,
    mjpeg::{MjpegParser, dimensions},
};
use axum::{
    body::Body,
    http::{HeaderValue, StatusCode},
    response::{IntoResponse, Response},
};
use bytes::Bytes;
use futures_util::{StreamExt, stream};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::{
    collections::{HashMap, VecDeque},
    sync::{Arc, Mutex},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tokio::sync::{Notify, OwnedSemaphorePermit, Semaphore, watch};
use uuid::Uuid;

pub fn unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

#[derive(Clone)]
pub struct Frame {
    pub jpeg: Bytes,
    pub sequence: u64,
    pub at: Instant,
    pub captured_unix_ms: u64,
    pub width: u16,
    pub height: u16,
}
#[derive(Clone, Default)]
pub struct CaptureState {
    pub frame: Option<Arc<Frame>>,
    pub error: Option<&'static str>,
}
pub struct Camera {
    pub config: CameraConfig,
    state: watch::Sender<CaptureState>,
    demand: Notify,
    max_frame: usize,
    http: reqwest::Client,
}
impl Camera {
    pub fn new(config: CameraConfig, max_frame: usize) -> Arc<Self> {
        let (state, _) = watch::channel(CaptureState::default());
        let http = reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(3))
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .expect("build trusted loopback camera client");
        Arc::new(Self {
            config,
            state,
            demand: Notify::new(),
            max_frame,
            http,
        })
    }
    pub fn subscribe(&self) -> watch::Receiver<CaptureState> {
        let rx = self.state.subscribe();
        self.demand.notify_one();
        rx
    }
    pub fn view(&self, fresh: Duration) -> CameraView {
        let state = self.state.borrow();
        let frame = state.frame.as_ref().filter(|f| f.at.elapsed() <= fresh);
        CameraView {
            id: self.config.id.clone(),
            name: self.config.name.clone(),
            online: frame.is_some(),
            width: frame.map(|f| f.width),
            height: frame.map(|f| f.height),
            error: state.error,
            active_consumers: self.state.receiver_count(),
        }
    }
    pub async fn run(self: Arc<Self>) {
        let mut sequence = 0;
        loop {
            while self.state.receiver_count() == 0 {
                self.demand.notified().await;
            }
            let error = self.receive(&mut sequence).await.err();
            self.state.send_replace(CaptureState { frame: None, error });
            if let Some(code) = error {
                tracing::warn!(
                    camera_id = self.config.id,
                    error = code,
                    "Capture upstream interrupted"
                );
            }
            tokio::time::sleep(Duration::from_secs(1)).await;
        }
    }
    async fn verify_online(&self) -> Result<(), &'static str> {
        let response = self
            .http
            .get(format!(
                "{}/state",
                self.config.upstream.trim_end_matches('/')
            ))
            .timeout(Duration::from_secs(1))
            .send()
            .await
            .map_err(|_| "camera_status_unreachable")?;
        if !response.status().is_success() {
            return Err("camera_status_unreachable");
        }
        let data = crate::auth::bounded_bytes(response, 64 * 1024)
            .await
            .map_err(|_| "camera_status_invalid")?;
        let value: serde_json::Value =
            serde_json::from_slice(&data).map_err(|_| "camera_status_invalid")?;
        if value["result"]["source"]["online"] != true {
            return Err("camera_offline");
        }
        Ok(())
    }
    async fn receive(&self, sequence: &mut u64) -> Result<(), &'static str> {
        self.verify_online().await?;
        let response = tokio::time::timeout(
            Duration::from_secs(4),
            self.http
                .get(format!(
                    "{}/stream",
                    self.config.upstream.trim_end_matches('/')
                ))
                .send(),
        )
        .await
        .map_err(|_| "camera_connect_timeout")?
        .map_err(|_| "camera_unreachable")?;
        if !response.status().is_success() {
            return Err("camera_upstream_rejected");
        }
        if !response
            .headers()
            .get("content-type")
            .and_then(|v| v.to_str().ok())
            .is_some_and(|v| {
                v.to_ascii_lowercase()
                    .starts_with("multipart/x-mixed-replace")
            })
        {
            return Err("camera_stream_type");
        }
        let mut source = response.bytes_stream();
        let mut parser = MjpegParser::new(self.max_frame);
        let mut status_tick = tokio::time::interval(Duration::from_secs(1));
        status_tick.tick().await;
        let mut last_bytes = Instant::now();
        while self.state.receiver_count() > 0 {
            let part = tokio::select! {
                _ = status_tick.tick() => { self.verify_online().await?; continue; }
                part = tokio::time::timeout_at(tokio::time::Instant::from_std(last_bytes + Duration::from_secs(3)), source.next()) => {
                    part.map_err(|_| "camera_frame_timeout")?.ok_or("camera_stream_closed")?.map_err(|_| "camera_stream_interrupted")?
                }
            };
            last_bytes = Instant::now();
            // Bound each parser append regardless of HTTP client chunk size; drain complete frames first.
            for part in part.chunks(16 * 1024) {
                parser.push(part)?;
                while let Some(jpeg) = parser.frame()? {
                    let (width, height) = dimensions(&jpeg)?;
                    *sequence += 1;
                    self.state.send_replace(CaptureState {
                        frame: Some(Arc::new(Frame {
                            jpeg,
                            sequence: *sequence,
                            at: Instant::now(),
                            captured_unix_ms: unix_ms(),
                            width,
                            height,
                        })),
                        error: None,
                    });
                }
            }
        }
        Ok(())
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CameraView {
    pub id: String,
    pub name: String,
    pub online: bool,
    pub width: Option<u16>,
    pub height: Option<u16>,
    pub error: Option<&'static str>,
    pub active_consumers: usize,
}

/// Permits live in response-body state, including slow/backpressured viewers, until that body is dropped.
pub struct ViewerGuard {
    _global: OwnedSemaphorePermit,
    budget: Arc<Mutex<Budget>>,
    user: Uuid,
}
impl Drop for ViewerGuard {
    fn drop(&mut self) {
        let mut b = self.budget.lock().unwrap_or_else(|p| p.into_inner());
        if let Some(n) = b.viewers.get_mut(&self.user) {
            *n -= 1;
            if *n == 0 {
                b.viewers.remove(&self.user);
            }
        }
    }
}
#[derive(Default)]
struct Budget {
    viewers: HashMap<Uuid, usize>,
    snapshots: HashMap<Uuid, VecDeque<Instant>>,
}
pub struct CameraService {
    pub cameras: HashMap<String, Arc<Camera>>,
    config: Config,
    viewers: Arc<Semaphore>,
    snapshots: Arc<Semaphore>,
    budget: Arc<Mutex<Budget>>,
}
impl CameraService {
    pub fn new(config: &Config) -> Self {
        Self {
            cameras: config
                .cameras
                .iter()
                .map(|c| (c.id.clone(), Camera::new(c.clone(), config.max_frame_bytes)))
                .collect(),
            config: config.clone(),
            viewers: Arc::new(Semaphore::new(config.max_viewers)),
            snapshots: Arc::new(Semaphore::new(config.max_snapshots)),
            budget: Arc::new(Mutex::new(Budget::default())),
        }
    }
    pub fn start(&self) {
        for c in self.cameras.values() {
            tokio::spawn(c.clone().run());
        }
    }
    pub fn camera(&self, id: &str) -> Result<Arc<Camera>, ApiError> {
        self.cameras
            .get(id)
            .cloned()
            .ok_or_else(|| ApiError::new(StatusCode::NOT_FOUND, "camera_not_found"))
    }
    pub fn views(&self) -> Vec<CameraView> {
        let mut cameras = self
            .cameras
            .values()
            .map(|c| c.view(Duration::from_millis(self.config.frame_fresh_ms)))
            .collect::<Vec<_>>();
        cameras.sort_by(|a, b| a.id.cmp(&b.id));
        cameras
    }
    fn viewer(&self, user: Uuid) -> Result<ViewerGuard, ApiError> {
        let permit = self
            .viewers
            .clone()
            .try_acquire_owned()
            .map_err(|_| ApiError::busy("camera_viewer_capacity"))?;
        let mut budget = self.budget.lock().unwrap_or_else(|p| p.into_inner());
        let active = budget.viewers.entry(user).or_default();
        if *active >= self.config.max_viewers_per_account {
            return Err(ApiError::busy("camera_account_viewer_capacity"));
        }
        *active += 1;
        drop(budget);
        Ok(ViewerGuard {
            _global: permit,
            budget: self.budget.clone(),
            user,
        })
    }
    pub fn stream(
        &self,
        camera: Arc<Camera>,
        auth: Arc<crate::auth::Auth>,
        identity: Identity,
    ) -> Result<Response, ApiError> {
        let guard = self.viewer(identity.claims.sub)?;
        let rx = camera.subscribe();
        let state = Viewer {
            _guard: guard,
            rx,
            auth,
            identity,
            sequence: 0,
            started: Instant::now(),
            last_auth: Instant::now(),
            max_life: Duration::from_secs(self.config.viewer_session_seconds),
            recheck: Duration::from_secs(self.config.auth_recheck_seconds),
            fresh: Duration::from_millis(self.config.frame_fresh_ms),
            pending: VecDeque::new(),
        };
        let body = stream::unfold(state, |mut v| async move {
            loop {
                if v.started.elapsed() >= v.max_life || unix_ms() / 1000 >= v.identity.claims.exp {
                    return None;
                }
                if v.last_auth.elapsed() >= v.recheck {
                    if v.auth
                        .authenticate_token(v.identity.token.clone())
                        .await
                        .is_err()
                    {
                        return None;
                    }
                    v.last_auth = Instant::now();
                }
                if let Some(bytes) = v.pending.pop_front() {
                    return Some((Ok::<Bytes, std::io::Error>(bytes), v));
                }
                let frame = v.rx.borrow().frame.clone();
                if let Some(f) =
                    frame.filter(|f| f.sequence != v.sequence && f.at.elapsed() <= v.fresh)
                {
                    v.sequence = f.sequence;
                    let headers = format!(
                        "--vietocr\r\nContent-Type: image/jpeg\r\nContent-Length: {}\r\nX-Captured-Unix-Ms: {}\r\n\r\n",
                        f.jpeg.len(),
                        f.captured_unix_ms
                    );
                    // Separate body chunks share the JPEG allocation across viewers; no per-viewer JPEG copy.
                    v.pending.extend([
                        Bytes::from(headers),
                        f.jpeg.clone(),
                        Bytes::from_static(b"\r\n"),
                    ]);
                    continue;
                }
                // Wake periodically to enforce token/session expiry even while the camera is unplugged.
                match tokio::time::timeout(Duration::from_secs(1), v.rx.changed()).await {
                    Ok(Err(_)) => return None,
                    _ => continue,
                }
            }
        });
        let mut response = Body::from_stream(body).into_response();
        response.headers_mut().insert(
            "content-type",
            HeaderValue::from_static("multipart/x-mixed-replace; boundary=vietocr"),
        );
        response
            .headers_mut()
            .insert("x-accel-buffering", HeaderValue::from_static("no"));
        Ok(response)
    }
    pub async fn snapshot(
        &self,
        camera: Arc<Camera>,
        identity: &Identity,
    ) -> Result<Response, ApiError> {
        let requested_at = Instant::now();
        let permit = self
            .snapshots
            .clone()
            .try_acquire_owned()
            .map_err(|_| ApiError::busy("camera_snapshot_capacity"))?;
        {
            let mut b = self.budget.lock().unwrap_or_else(|p| p.into_inner());
            // Remove inactive users to keep the per-account limiter bounded over long uptimes.
            b.snapshots.retain(|_, q| {
                q.back()
                    .is_some_and(|t| t.elapsed() < Duration::from_secs(10))
            });
            if b.snapshots.len() >= 4096 && !b.snapshots.contains_key(&identity.claims.sub) {
                return Err(ApiError::busy("camera_snapshot_capacity"));
            }
            let q = b.snapshots.entry(identity.claims.sub).or_default();
            while q
                .front()
                .is_some_and(|t| t.elapsed() >= Duration::from_secs(10))
            {
                q.pop_front();
            }
            if q.len() >= 6 {
                return Err(ApiError::busy("camera_snapshot_rate"));
            }
            q.push_back(Instant::now());
        }
        camera
            .verify_online()
            .await
            .map_err(ApiError::unavailable)?;
        let mut rx = camera.subscribe();
        let fresh = Duration::from_millis(self.config.frame_fresh_ms);
        let frame = tokio::time::timeout(Duration::from_secs(4), async {
            loop {
                if let Some(f) = rx
                    .borrow()
                    .frame
                    .clone()
                    .filter(|f| f.at >= requested_at && f.at.elapsed() <= fresh)
                {
                    return Ok(f);
                }
                rx.changed()
                    .await
                    .map_err(|_| ApiError::unavailable("camera_offline"))?;
            }
        })
        .await
        .map_err(|_| ApiError::unavailable("camera_no_fresh_frame"))??;
        camera
            .verify_online()
            .await
            .map_err(ApiError::unavailable)?;
        let image = frame.jpeg.clone();
        let hash = tokio::task::spawn_blocking(move || format!("{:x}", Sha256::digest(&image)))
            .await
            .map_err(|_| ApiError::unavailable("snapshot_failed"))?;
        let image = frame.jpeg.clone();
        let body = stream::unfold((Some(image), permit), |(image, permit)| async move {
            image.map(|image| (Ok::<Bytes, std::io::Error>(image), (None, permit)))
        });
        let mut response = Body::from_stream(body).into_response();
        response
            .headers_mut()
            .insert("content-type", HeaderValue::from_static("image/jpeg"));
        response
            .headers_mut()
            .insert("x-image-sha256", HeaderValue::from_str(&hash).unwrap());
        response
            .headers_mut()
            .insert("x-image-width", HeaderValue::from(frame.width));
        response
            .headers_mut()
            .insert("x-image-height", HeaderValue::from(frame.height));
        response.headers_mut().insert(
            "x-captured-unix-ms",
            HeaderValue::from(frame.captured_unix_ms),
        );
        Ok(response)
    }
}

struct Viewer {
    _guard: ViewerGuard,
    rx: watch::Receiver<CaptureState>,
    auth: Arc<crate::auth::Auth>,
    identity: Identity,
    sequence: u64,
    started: Instant,
    last_auth: Instant,
    max_life: Duration,
    recheck: Duration,
    fresh: Duration,
    pending: VecDeque<Bytes>,
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn account_and_global_permits_release_on_drop() {
        let cfg = Config {
            max_viewers: 2,
            max_viewers_per_account: 1,
            ..Default::default()
        };
        let service = CameraService::new(&cfg);
        let a = Uuid::new_v4();
        let b = Uuid::new_v4();
        let ga = service.viewer(a).unwrap();
        assert!(service.viewer(a).is_err());
        let gb = service.viewer(b).unwrap();
        assert!(service.viewer(Uuid::new_v4()).is_err());
        drop(ga);
        assert!(service.viewer(a).is_ok());
        drop(gb);
        assert!(service.budget.lock().unwrap().viewers.is_empty());
    }
    #[tokio::test]
    async fn slow_consumers_skip_to_latest_frame_without_unbounded_queue() {
        let c = Camera::new(
            CameraConfig {
                id: "desk".into(),
                name: "Desk".into(),
                upstream: "http://127.0.0.1".into(),
            },
            1024,
        );
        let rx = c.subscribe();
        for sequence in 1..=1000 {
            c.state.send_replace(CaptureState {
                frame: Some(Arc::new(Frame {
                    jpeg: Bytes::from_static(b"jpeg"),
                    sequence,
                    at: Instant::now(),
                    captured_unix_ms: unix_ms(),
                    width: 1920,
                    height: 1080,
                })),
                error: None,
            });
        }
        assert_eq!(rx.borrow().frame.as_ref().unwrap().sequence, 1000);
        assert_eq!(c.state.receiver_count(), 1);
    }
    fn identity() -> Identity {
        let user = Uuid::new_v4();
        Identity {
            token: Arc::from("test-only-not-a-network-token"),
            claims: crate::auth::Claims {
                sub: user,
                session_id: Uuid::new_v4(),
                exp: unix_ms() / 1000 + 300,
            },
            account: crate::auth::Account {
                user_id: user,
                client_id: user.to_string(),
                ocr_id: "ocr_fixture".into(),
                daily_limit: 500,
                rate_per_minute: 30,
                used_today: 0,
            },
        }
    }
    #[tokio::test]
    async fn body_holds_viewer_permit_until_dropped_even_before_its_first_frame() {
        let cfg = Config {
            cameras: vec![CameraConfig {
                id: "desk".into(),
                name: "Desk".into(),
                upstream: "http://127.0.0.1:1".into(),
            }],
            max_viewers: 1,
            max_viewers_per_account: 1,
            ..Default::default()
        };
        let service = CameraService::new(&cfg);
        let auth = Arc::new(crate::auth::Auth::new(cfg.auth.clone()).unwrap());
        let identity = identity();
        let response = service
            .stream(service.camera("desk").unwrap(), auth, identity.clone())
            .unwrap();
        assert!(service.viewer(identity.claims.sub).is_err());
        let body = response.into_body();
        assert_eq!(service.viewers.available_permits(), 0);
        drop(body);
        assert_eq!(service.viewers.available_permits(), 1);
        assert_eq!(service.camera("desk").unwrap().state.receiver_count(), 0);
    }
    #[tokio::test]
    async fn snapshot_waits_for_a_new_frame_keeps_full_jpeg_and_never_enqueues_ocr() {
        use http_body_util::BodyExt;
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let host = tokio::spawn(async move {
            axum::serve(
                listener,
                axum::Router::new().route(
                    "/state",
                    axum::routing::get(|| async {
                        axum::Json(serde_json::json!({"result":{"source":{"online":true}}}))
                    }),
                ),
            )
            .await
            .unwrap()
        });
        let cfg = Config {
            cameras: vec![CameraConfig {
                id: "desk".into(),
                name: "Desk".into(),
                upstream: format!("http://{address}"),
            }],
            max_snapshots: 1,
            ..Default::default()
        };
        let service = Arc::new(CameraService::new(&cfg));
        let c = service.camera("desk").unwrap();
        let jpeg = Bytes::from(crate::mjpeg::jpeg_fixture());
        c.state.send_replace(CaptureState {
            frame: Some(Arc::new(Frame {
                jpeg: Bytes::from_static(b"old thumbnail"),
                sequence: 1,
                at: Instant::now(),
                captured_unix_ms: 1,
                width: 101,
                height: 76,
            })),
            error: None,
        });
        let requester = service.clone();
        let ident = identity();
        let pending = tokio::spawn(async move {
            requester
                .snapshot(requester.camera("desk").unwrap(), &ident)
                .await
        });
        tokio::time::sleep(Duration::from_millis(20)).await;
        assert!(!pending.is_finished());
        c.state.send_replace(CaptureState {
            frame: Some(Arc::new(Frame {
                jpeg: jpeg.clone(),
                sequence: 2,
                at: Instant::now(),
                captured_unix_ms: unix_ms(),
                width: 1920,
                height: 1080,
            })),
            error: None,
        });
        let response = pending.await.unwrap().unwrap();
        assert_eq!(response.headers()["x-image-width"], "1920");
        assert_eq!(response.headers()["x-image-height"], "1080");
        assert_eq!(service.snapshots.available_permits(), 0);
        let bytes = response.into_body().collect().await.unwrap().to_bytes();
        assert_eq!(bytes, jpeg);
        assert_eq!(service.snapshots.available_permits(), 1);
        host.abort();
    }
    #[tokio::test]
    async fn two_consumers_share_one_native_upstream_connection_and_recover_after_it_closes() {
        use std::sync::atomic::{AtomicUsize, Ordering};
        let hits = Arc::new(AtomicUsize::new(0));
        let handler_hits = hits.clone();
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let jpeg = crate::mjpeg::jpeg_fixture();
        let original = jpeg.clone();
        let upstream = axum::Router::new().route("/state", axum::routing::get(|| async { axum::Json(serde_json::json!({"result":{"source":{"online":true}}})) })).route("/stream", axum::routing::get(move || {
            let h = handler_hits.clone(); let jpeg = jpeg.clone(); async move {
                h.fetch_add(1, Ordering::Relaxed);
                let body = stream::unfold(0, move |n| { let jpeg = jpeg.clone(); async move {
                    if n == 5 { return None; } tokio::time::sleep(Duration::from_millis(15)).await;
                    let mut part = format!("--upstream\r\nContent-Type: image/jpeg\r\nContent-Length: {}\r\n\r\n", jpeg.len()).into_bytes();
                    part.extend(&jpeg); part.extend(b"\r\n"); Some((Ok::<_, std::io::Error>(Bytes::from(part)), n + 1))
                }});
                ([("content-type", "multipart/x-mixed-replace; boundary=upstream")], Body::from_stream(body))
            }
        }));
        let host = tokio::spawn(async move { axum::serve(listener, upstream).await.unwrap() });
        let camera = Camera::new(
            CameraConfig {
                id: "desk".into(),
                name: "Desk".into(),
                upstream: format!("http://{address}"),
            },
            1024,
        );
        let mut a = camera.subscribe();
        let mut b = camera.subscribe();
        let producer = tokio::spawn(camera.clone().run());
        tokio::time::timeout(Duration::from_secs(2), a.changed())
            .await
            .unwrap()
            .unwrap();
        tokio::time::timeout(Duration::from_secs(2), b.changed())
            .await
            .unwrap()
            .unwrap();
        assert_eq!(hits.load(Ordering::Relaxed), 1);
        assert_eq!(a.borrow().frame.as_ref().unwrap().jpeg.as_ref(), original);
        let first = a.borrow().frame.as_ref().unwrap().sequence;
        tokio::time::timeout(Duration::from_secs(4), async {
            loop {
                a.changed().await.unwrap();
                if hits.load(Ordering::Relaxed) >= 2
                    && a.borrow()
                        .frame
                        .as_ref()
                        .is_some_and(|f| f.sequence > first)
                {
                    break;
                }
            }
        })
        .await
        .unwrap();
        drop(a);
        drop(b);
        producer.abort();
        host.abort();
    }
}
