//! SSH-only, loopback-only load fixture. Real gateway/auth/relay code, ephemeral
//! ES256 identities and fake local DB/compute. Never touches Supabase or OCR quota.
use axum::{
    Json, Router,
    extract::State,
    http::{HeaderMap, StatusCode},
    routing::{get, post},
};
use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use jsonwebtoken::{Algorithm, EncodingKey, Header, encode};
use ring::{
    rand::SystemRandom,
    signature::{ECDSA_P256_SHA256_FIXED_SIGNING, EcdsaKeyPair, KeyPair},
};
use serde_json::{Value, json};
use std::{
    collections::HashMap,
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicUsize, Ordering},
    },
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tokio::sync::watch;
use uuid::Uuid;
use vietocr_gateway::{
    App,
    config::{AuthConfig, ComputeConfig, Config},
    router,
    telemetry::PanelUpdate,
};

struct Fixture {
    jwks: Value,
    accounts: HashMap<String, Value>,
    machine: String,
    jwks_reads: AtomicUsize,
    machine_calls: AtomicUsize,
    compute_offline: AtomicBool,
    banned: AtomicBool,
}
fn bearer(headers: &HeaderMap) -> &str {
    headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.strip_prefix("Bearer "))
        .unwrap_or("")
}
async fn jwks(State(f): State<Arc<Fixture>>) -> Json<Value> {
    f.jwks_reads.fetch_add(1, Ordering::Relaxed);
    Json(f.jwks.clone())
}
async fn account(State(f): State<Arc<Fixture>>, headers: HeaderMap) -> (StatusCode, Json<Value>) {
    tokio::time::sleep(Duration::from_millis(20)).await;
    if f.banned.load(Ordering::Relaxed) {
        return (StatusCode::FORBIDDEN, Json(json!({"error":"fixture_ban"})));
    }
    match f.accounts.get(bearer(&headers)) {
        Some(value) => (StatusCode::OK, Json(value.clone())),
        None => (
            StatusCode::UNAUTHORIZED,
            Json(json!({"error":"fixture_unknown_identity"})),
        ),
    }
}
async fn intent(
    State(f): State<Arc<Fixture>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> (StatusCode, Json<Value>) {
    if bearer(&headers) != f.machine {
        return (
            StatusCode::UNAUTHORIZED,
            Json(json!({"error":"fixture_machine_auth"})),
        );
    }
    f.machine_calls.fetch_add(1, Ordering::Relaxed);
    if f.compute_offline.load(Ordering::Relaxed) {
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({"error":"compute_unavailable"})),
        );
    }
    (
        StatusCode::OK,
        Json(json!({"id":body["requestId"],"state":"awaiting_upload","layout":body["layout"]})),
    )
}
fn memory() -> Value {
    let status = std::fs::read_to_string("/proc/self/status").unwrap_or_default();
    let kb = |prefix: &str| {
        status
            .lines()
            .find(|line| line.starts_with(prefix))
            .and_then(|line| line.split_whitespace().nth(1))
            .and_then(|n| n.parse::<u64>().ok())
    };
    json!({"rssKiB":kb("VmRSS:"),"peakRssKiB":kb("VmHWM:"),"openFds":std::fs::read_dir("/proc/self/fd").ok().map(|d|d.count())})
}
async fn submit(
    http: &reqwest::Client,
    origin: &str,
    token: &str,
    request: Uuid,
) -> Result<(u16, u128), Box<dyn std::error::Error + Send + Sync>> {
    let opened = Instant::now();
    let response=http.post(format!("{origin}/api/v2/intents")).bearer_auth(token)
        .json(&json!({"requestId":request,"sha256":"0".repeat(64),"imageBytes":1024,"mediaType":"image/jpeg","layout":"line","imageVersion":1}))
        .send().await?;
    let status = response.status().as_u16();
    let _ = response.bytes().await?;
    Ok((status, opened.elapsed().as_millis()))
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let clients = std::env::args()
        .nth(1)
        .map(|s| s.parse::<usize>())
        .transpose()?
        .unwrap_or(1000)
        .clamp(1, 1000);
    let rounds = std::env::args()
        .nth(2)
        .map(|s| s.parse::<usize>())
        .transpose()?
        .unwrap_or(1)
        .clamp(1, 30);
    let local = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let local_origin = format!("http://{}", local.local_addr()?);
    let random = SystemRandom::new();
    let private = EcdsaKeyPair::generate_pkcs8(&ECDSA_P256_SHA256_FIXED_SIGNING, &random)?;
    let key =
        EcdsaKeyPair::from_pkcs8(&ECDSA_P256_SHA256_FIXED_SIGNING, private.as_ref(), &random)?;
    let public = key.public_key().as_ref();
    let mut header = Header::new(Algorithm::ES256);
    header.kid = Some("load-fixture".into());
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let mut accounts = HashMap::new();
    let mut tokens = Vec::with_capacity(clients);
    for _ in 0..clients {
        let user = Uuid::new_v4();
        let session = Uuid::new_v4();
        let token = encode(
            &header,
            &json!({"sub":user,"session_id":session,"exp":now+3600,"iss":format!("{local_origin}/auth/v1"),"aud":"authenticated"}),
            &EncodingKey::from_ec_der(private.as_ref()),
        )?;
        accounts.insert(token.clone(),json!({"userId":user,"clientId":user,"ocrId":user,"dailyLimit":500,"ratePerMinute":30,"usedToday":0}));
        tokens.push(token);
    }
    let machine = format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple());
    let temp = std::env::temp_dir().join(format!("vietocr-load-probe-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&temp)?;
    let token_file = temp.join("machine.token");
    std::fs::write(&token_file, &machine)?;
    let fixture = Arc::new(Fixture {
        jwks: json!({"keys":[{"kty":"EC","crv":"P-256","alg":"ES256","use":"sig","kid":"load-fixture","x":URL_SAFE_NO_PAD.encode(&public[1..33]),"y":URL_SAFE_NO_PAD.encode(&public[33..])}]}),
        accounts,
        machine,
        jwks_reads: AtomicUsize::new(0),
        machine_calls: AtomicUsize::new(0),
        compute_offline: AtomicBool::new(false),
        banned: AtomicBool::new(false),
    });
    let fixture_routes = Router::new()
        .route("/auth/v1/.well-known/jwks.json", get(jwks))
        .route("/rest/v1/rpc/ocr_gateway_session", post(account))
        .route("/api/internal/v2/intents", post(intent))
        .with_state(fixture.clone());
    let fixture_task =
        tokio::spawn(async move { axum::serve(local, fixture_routes).await.unwrap() });
    let config = Config {
        // Only this diagnostic constructs in-memory loopback auth config; the
        // production executable's Config::load continues to require HTTPS.
        auth: AuthConfig {
            supabase_url: local_origin.clone(),
            publishable_key: "sb_publishable_fixture".into(),
            database_concurrency: 8,
        },
        compute: Some(ComputeConfig {
            origin: local_origin,
            public_results_origin: "https://results.example.invalid".into(),
            token_file: token_file.to_string_lossy().into(),
            concurrent_uploads: 4,
        }),
        ..Config::default()
    };
    let (_, panel) = watch::channel(PanelUpdate::default());
    let app = App::new(&config, panel)?;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let origin = format!("http://{}", listener.local_addr()?);
    let gateway_task =
        tokio::spawn(async move { axum::serve(listener, router(app)).await.unwrap() });
    let http = reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(8))
        .pool_max_idle_per_host(16)
        .build()?;
    let before = memory();
    let began = Instant::now();
    let mut reports = Vec::new();
    for round in 0..rounds {
        let mut tasks = tokio::task::JoinSet::new();
        for token in &tokens {
            let http = http.clone();
            let origin = origin.clone();
            let token = token.clone();
            tasks.spawn(async move {
                let opened = Instant::now();
                let request = Uuid::new_v4();
                let mut deferred = 0u64;
                for attempt in 0..120 {
                    match submit(&http, &origin, &token, request).await {
                        Ok((200, _)) => return (true, deferred, opened.elapsed().as_millis()),
                        Ok((429 | 503, _)) => {
                            deferred += 1;
                            tokio::time::sleep(Duration::from_millis(
                                100 + (request.as_u128() % 200) as u64
                                    + (attempt as u64 * 5).min(500),
                            ))
                            .await;
                        }
                        _ => return (false, deferred, opened.elapsed().as_millis()),
                    }
                }
                (false, deferred, opened.elapsed().as_millis())
            });
        }
        let mut latencies = Vec::new();
        let mut admitted = 0;
        let mut deferred = 0;
        while let Some(result) = tasks.join_next().await {
            let (ok, retries, ms) = result?;
            admitted += usize::from(ok);
            deferred += retries;
            latencies.push(ms);
        }
        latencies.sort_unstable();
        reports.push(json!({"round":round+1,"clients":clients,"metadataAdmitted":admitted,"deferredAttempts":deferred,"p50Ms":latencies[latencies.len()/2],"p95Ms":latencies[(latencies.len()*95/100).min(latencies.len()-1)]}));
        if admitted != clients {
            return Err("fixture load did not admit every metadata intent".into());
        }
    }
    fixture.compute_offline.store(true, Ordering::SeqCst);
    let offline = submit(&http, &origin, &tokens[0], Uuid::new_v4()).await?.0;
    fixture.compute_offline.store(false, Ordering::SeqCst);
    let calls = fixture.machine_calls.load(Ordering::SeqCst);
    fixture.banned.store(true, Ordering::SeqCst);
    let banned = submit(&http, &origin, &tokens[0], Uuid::new_v4()).await?.0;
    let ban_forwarded = fixture.machine_calls.load(Ordering::SeqCst) - calls;
    let health = http
        .get(format!("{origin}/health/live"))
        .send()
        .await?
        .status()
        .as_u16();
    if offline != 503 || banned != 403 || ban_forwarded != 0 || health != 200 {
        return Err("fixture failure isolation check failed".into());
    }
    println!(
        "{}",
        json!({"scope":"loopback real Rust gateway + ES256, fake local Supabase/compute; combined process includes fixtures and load clients","rounds":reports,"elapsedSeconds":began.elapsed().as_secs_f64(),"before":before,"after":memory(),"jwksFetches":fixture.jwks_reads.load(Ordering::Relaxed),"upstreamOfflineHttp":offline,"bannedHttp":banned,"bannedForwarded":ban_forwarded,"healthAfterLoad":health,"ocrImagesUploaded":0,"realDatabaseWrites":0,"realGoogleLogins":0})
    );
    gateway_task.abort();
    fixture_task.abort();
    if temp.parent() == Some(std::env::temp_dir().as_path())
        && temp
            .file_name()
            .unwrap()
            .to_string_lossy()
            .starts_with("vietocr-load-probe-")
    {
        std::fs::remove_dir_all(temp)?;
    }
    Ok(())
}
