use super::*;
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
    let jpeg = include_bytes!("../../Mobile/assets/samples/test.jpg").to_vec();
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
