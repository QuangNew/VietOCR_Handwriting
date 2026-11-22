use super::*;
#[test]
fn another_desktop_cannot_overwrite_the_same_workspace_and_exit_releases_lock() {
    let root = Temporary::new();
    let first = storage::workspace_lock(&root.0).unwrap().unwrap();
    assert!(storage::workspace_lock(&root.0).unwrap().is_none());
    drop(first);
    assert!(storage::workspace_lock(&root.0).unwrap().is_some());
}
#[test]
fn diagnostics_omit_credentials_before_persisting_or_exporting() {
    let root = Temporary::new();
    for message in [
        "authorization: bearer private-token",
        "sb_publishable_fixture",
        "CLIENT_SECRET=private-value",
        "eyJfixture.payload.signature",
    ] {
        diagnostics::append(&root.0, "client", message);
    }
    let text = diagnostics::read(&root.0).unwrap();
    assert!(!text.contains("private-token"));
    assert!(!text.contains("private-value"));
    assert!(!text.contains("sb_publishable_fixture"));
    assert!(!text.contains("eyJfixture"));
    assert!(text.contains("credential-like details omitted"));
}
use std::sync::{
    Arc,
    atomic::{AtomicBool, AtomicUsize, Ordering},
};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

struct Temporary(PathBuf);
impl Temporary {
    fn new() -> Self {
        Self(std::env::temp_dir().join(format!("vietocr-client-test-{}", Uuid::new_v4())))
    }
}
impl Drop for Temporary {
    fn drop(&mut self) {
        if self.0.parent() == Some(std::env::temp_dir().as_path())
            && self
                .0
                .file_name()
                .unwrap()
                .to_string_lossy()
                .starts_with("vietocr-client-test-")
        {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
}
async fn account(client: &Client, owner: Uuid) {
    *client.session.lock().await = Some(session::Session {
        access_token: format!("fixture-{owner}"),
        refresh_token: String::new(),
        user_id: owner,
        email: "fixture@example.invalid".into(),
        expires_at: u64::MAX,
    });
    storage::atomic(&client.root.join(format!("verified-{owner}")), b"verified").unwrap();
}
fn client(origin: String, root: PathBuf) -> Client {
    Client::new(
        Config {
            gateway: origin,
            supabase_url: "https://fixture.supabase.co".into(),
            publishable_key: "sb_publishable_fixture".into(),
        },
        root,
    )
    .unwrap()
}

#[tokio::test]
async fn completion_from_previous_account_cannot_write_to_the_next_accounts_cache() {
    let root = Temporary::new();
    let client = client("http://127.0.0.1:1".into(), root.0.clone());
    let a = Uuid::new_v4();
    let b = Uuid::new_v4();
    account(&client, a).await;
    let jpeg = include_bytes!("../../contracts/fixtures/images/test.jpg").to_vec();
    let mut draft = client
        .import(jpeg.clone(), "original.jpg".into())
        .await
        .unwrap();
    account(&client, b).await;
    draft.text = "Previous account result".into();
    assert!(client.save_draft(&draft).await.is_err());
    assert!(client.access_token_for(Some(a)).await.is_err());
    assert!(client.drafts().await.unwrap().is_empty());
    account(&client, a).await;
    assert_eq!(client.image_bytes(draft.id).await.unwrap(), jpeg);
    assert!(client.drafts().await.unwrap()[0].text.is_empty());
}

#[tokio::test]
async fn result_ticket_survives_pi_outage_but_not_expiry_or_account_switch() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let origin = format!("http://{}", listener.local_addr().unwrap());
    let offline = Arc::new(AtomicBool::new(false));
    let minted = Arc::new(AtomicUsize::new(0));
    let reads = Arc::new(AtomicUsize::new(0));
    let a = Uuid::new_v4();
    let job = Uuid::new_v4();
    let server = {
        let offline = offline.clone();
        let minted = minted.clone();
        let reads = reads.clone();
        let origin = origin.clone();
        tokio::spawn(async move {
            loop {
                let (mut socket, _) = listener.accept().await.unwrap();
                let offline = offline.clone();
                let minted = minted.clone();
                let reads = reads.clone();
                let origin = origin.clone();
                tokio::spawn(async move {
                    let mut request = vec![];
                    let mut buffer = [0; 1024];
                    while !request.windows(4).any(|b| b == b"\r\n\r\n") {
                        let n = socket.read(&mut buffer).await.unwrap();
                        if n == 0 {
                            return;
                        }
                        request.extend_from_slice(&buffer[..n]);
                        assert!(request.len() < 16384);
                    }
                    let header = String::from_utf8_lossy(&request);
                    let path = header
                        .lines()
                        .next()
                        .unwrap()
                        .split_whitespace()
                        .nth(1)
                        .unwrap();
                    let (status, body) = if path.starts_with("/api/v2/results/") {
                        assert!(
                            header
                                .to_lowercase()
                                .contains("authorization: bearer result-fixture")
                        );
                        reads.fetch_add(1, Ordering::SeqCst);
                        ("200 OK", json!({"state":"succeeded","text":"fixture"}))
                    } else if offline.load(Ordering::SeqCst) {
                        ("503 Unavailable", json!({"error":"pi_offline"}))
                    } else if path == "/api/v2/session" {
                        (
                            "200 OK",
                            json!({"account":{"userId":a},"resultsOrigin":origin}),
                        )
                    } else if path.ends_with("/result-ticket") {
                        minted.fetch_add(1, Ordering::SeqCst);
                        (
                            "200 OK",
                            json!({"resultUrl":format!("{origin}/api/v2/results/{job}"),"ticket":"result-fixture","expiresIn":300}),
                        )
                    } else {
                        panic!("Unexpected fixture route: {path}")
                    };
                    let body = body.to_string();
                    let response = format!(
                        "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                        body.len()
                    );
                    socket.write_all(response.as_bytes()).await.unwrap();
                });
            }
        })
    };
    let root = Temporary::new();
    let client = client(origin, root.0.clone());
    account(&client, a).await;
    assert_eq!(client.result(job).await.unwrap()["text"], "fixture");
    offline.store(true, Ordering::SeqCst);
    assert!(client.result(job).await.is_ok());
    assert_eq!(minted.load(Ordering::SeqCst), 1);
    assert_eq!(reads.load(Ordering::SeqCst), 2);
    client
        .result_tickets
        .lock()
        .await
        .get_mut(&job)
        .unwrap()
        .expires = Instant::now();
    assert!(client.result(job).await.is_err());
    client
        .result_tickets
        .lock()
        .await
        .get_mut(&job)
        .unwrap()
        .expires = Instant::now() + Duration::from_secs(200);
    account(&client, Uuid::new_v4()).await;
    assert!(client.result(job).await.is_err());
    assert_eq!(reads.load(Ordering::SeqCst), 2);
    server.abort();
}

#[tokio::test]
async fn stopping_a_local_draft_preserves_its_original_and_requires_explicit_resend() {
    let root = Temporary::new();
    let client = client("http://127.0.0.1:1".into(), root.0.clone());
    account(&client, Uuid::new_v4()).await;
    let image = include_bytes!("../../contracts/fixtures/images/test.jpg").to_vec();
    let draft = client
        .import(image.clone(), "original.jpg".into())
        .await
        .unwrap();
    let stopped = client.cancel_draft(draft.id).await.unwrap();
    assert_eq!(stopped.state, "cancelled");
    assert_eq!(stopped.request_id, draft.request_id);
    assert_eq!(client.image_bytes(draft.id).await.unwrap(), image);
    assert_eq!(
        client
            .submit(draft.id, "auto", |_, _, _| {})
            .await
            .unwrap_err(),
        "operation_stopped"
    );
    let prepared = client.prepare_send(vec![draft.id]).await.unwrap().remove(0);
    assert_eq!(prepared.state, "draft");
    assert_ne!(prepared.request_id, draft.request_id);
}

#[tokio::test]
async fn automatic_optimization_is_immutable_across_retries_and_preserves_original() {
    let root = Temporary::new();
    let client = client("http://127.0.0.1:1".into(), root.0.clone());
    account(&client, Uuid::new_v4()).await;
    let pixels = image::RgbImage::from_fn(512, 256, |x, y| {
        image::Rgb([(x % 255) as u8, if y % 25 < 3 { 20 } else { 240 }, 120])
    });
    let mut source = Vec::new();
    use image::ImageEncoder;
    image::codecs::png::PngEncoder::new_with_quality(
        &mut source,
        image::codecs::png::CompressionType::Uncompressed,
        image::codecs::png::FilterType::NoFilter,
    )
    .write_image(pixels.as_raw(), 512, 256, image::ExtendedColorType::Rgb8)
    .unwrap();
    let mut draft = client
        .import(source.clone(), "source.png".into())
        .await
        .unwrap();
    client.prepare_transfer(&mut draft).await.unwrap();
    let wire = client.transfer_bytes(&draft).await.unwrap();
    assert!(wire.len() + 1024 < source.len());
    assert_eq!(client.image_bytes(draft.id).await.unwrap(), source);
    let (_, width, height) = image_headers::inspect(&wire).unwrap();
    assert_eq!((width, height), (512, 256));
    let metadata = Client::intent_metadata(&draft, "auto", false);
    assert_eq!(metadata["imageBytes"], wire.len());
    assert_eq!(metadata["sha256"], format!("{:x}", Sha256::digest(&wire)));
    assert_eq!(metadata["correct"], false);
    assert_eq!(
        Client::intent_metadata(&draft, "auto", true)["correct"],
        true
    );
    client.prepare_transfer(&mut draft).await.unwrap();
    assert_eq!(client.transfer_bytes(&draft).await.unwrap(), wire);
    assert_eq!(Client::intent_metadata(&draft, "auto", false), metadata);
    assert_eq!(client.drafts().await.unwrap().len(), 1);
}

#[tokio::test]
async fn stop_interrupts_an_inflight_http_request_and_persists_unconfirmed_cancel_across_restart() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let origin = format!("http://{}", listener.local_addr().unwrap());
    let owner = Uuid::new_v4();
    let job = Uuid::new_v4();
    let requests = Arc::new(Mutex::new(Vec::<(String, Value)>::new()));
    let grant_started = Arc::new(tokio::sync::Notify::new());
    let online = Arc::new(AtomicBool::new(false));
    let server = {
        let requests = requests.clone();
        let grant_started = grant_started.clone();
        let online = online.clone();
        tokio::spawn(async move {
            loop {
                let (mut socket, _) = listener.accept().await.unwrap();
                let requests = requests.clone();
                let grant_started = grant_started.clone();
                let online = online.clone();
                tokio::spawn(async move {
                    let mut request = Vec::new();
                    let mut buffer = [0; 4096];
                    let header_end = loop {
                        let n = socket.read(&mut buffer).await.unwrap();
                        if n == 0 {
                            return;
                        }
                        request.extend_from_slice(&buffer[..n]);
                        if let Some(at) = request.windows(4).position(|b| b == b"\r\n\r\n") {
                            break at + 4;
                        }
                        assert!(request.len() < 16384);
                    };
                    let header = String::from_utf8_lossy(&request[..header_end]);
                    let route = header
                        .lines()
                        .next()
                        .unwrap()
                        .split_whitespace()
                        .take(2)
                        .collect::<Vec<_>>()
                        .join(" ");
                    let length = header
                        .lines()
                        .find_map(|line| {
                            line.to_lowercase()
                                .strip_prefix("content-length: ")
                                .and_then(|s| s.trim().parse::<usize>().ok())
                        })
                        .unwrap_or(0);
                    while request.len() < header_end + length {
                        let n = socket.read(&mut buffer).await.unwrap();
                        if n == 0 {
                            return;
                        }
                        request.extend_from_slice(&buffer[..n]);
                    }
                    let body =
                        serde_json::from_slice(&request[header_end..]).unwrap_or(Value::Null);
                    requests.lock().await.push((route.clone(), body));
                    let (status, value) = if route == "GET /api/v2/session" {
                        ("200 OK", json!({"account":{"userId":owner}}))
                    } else if route == "POST /api/v2/intents" {
                        ("200 OK", json!({"id":job,"state":"awaiting_upload"}))
                    } else if route.ends_with("/grant") {
                        grant_started.notify_one();
                        // There is no response until the native client drops the HTTP
                        // future. A Stop must not wait for the ordinary 30s timeout.
                        let _ = socket.read(&mut buffer).await;
                        return;
                    } else if route.starts_with("DELETE ") && route.ends_with("/cancel") {
                        if online.load(Ordering::SeqCst) {
                            ("200 OK", json!({"state":"cancelled","accepted":false}))
                        } else {
                            ("503 Unavailable", json!({"error":"compute_unreachable"}))
                        }
                    } else {
                        panic!("Unexpected route {route}");
                    };
                    let text = value.to_string();
                    let response = format!(
                        "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{text}",
                        text.len()
                    );
                    let _ = socket.write_all(response.as_bytes()).await;
                });
            }
        })
    };
    let root = Temporary::new();
    let client = Arc::new(client(origin.clone(), root.0.clone()));
    account(&client, owner).await;
    let draft = client
        .import(
            include_bytes!("../../contracts/fixtures/images/test.jpg").to_vec(),
            "photo.jpg".into(),
        )
        .await
        .unwrap();
    let sending = {
        let client = client.clone();
        tokio::spawn(async move { client.submit(draft.id, "line", |_, _, _| {}).await })
    };
    tokio::time::timeout(Duration::from_secs(15), grant_started.notified())
        .await
        .unwrap();
    let stopped = tokio::time::timeout(Duration::from_secs(3), client.cancel_draft(draft.id))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(sending.await.unwrap().unwrap_err(), "operation_stopped");
    assert_eq!(stopped.state, "cancel_pending");
    assert!(client.prepare_send(vec![draft.id]).await.is_err());
    drop(client);
    let reloaded = self::client(origin, root.0.clone());
    account(&reloaded, owner).await;
    assert_eq!(reloaded.drafts().await.unwrap()[0].state, "cancel_pending");
    online.store(true, Ordering::SeqCst);
    let stopped = reloaded.cancel_draft(draft.id).await.unwrap();
    assert_eq!(stopped.state, "cancelled");
    let fresh = reloaded
        .prepare_send(vec![draft.id])
        .await
        .unwrap()
        .remove(0);
    assert_ne!(fresh.request_id, stopped.request_id);
    let log = requests.lock().await;
    assert_eq!(
        log.iter()
            .filter(|(r, _)| r == "POST /api/v2/intents")
            .count(),
        1
    );
    assert!(
        !log.iter()
            .any(|(r, _)| r.contains("/content") || r.contains("/complete"))
    );
    server.abort();
}
