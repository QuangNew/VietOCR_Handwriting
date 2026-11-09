use super::{Client, bounded, storage};
use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    path::Path,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use uuid::Uuid;

#[derive(Serialize, Deserialize)]
pub struct Session {
    pub access_token: String,
    pub refresh_token: String,
    pub user_id: Uuid,
    pub email: String,
    pub expires_at: u64,
}
fn seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}
pub fn load(root: &Path) -> Result<Session, String> {
    let bytes = std::fs::read(root.join("session.dpapi")).map_err(|_| "Chưa đăng nhập Google")?;
    serde_json::from_slice(&storage::protect(&bytes, true)?)
        .map_err(|_| "Phiên lưu không hợp lệ".into())
}
fn save(root: &Path, s: &Session) -> Result<(), String> {
    storage::atomic(
        &root.join("session.dpapi"),
        &storage::protect(
            &serde_json::to_vec(s).map_err(|_| "Phiên không hợp lệ")?,
            false,
        )?,
    )
}
impl Client {
    async fn auth_token(&self, grant: &str, body: Value) -> Result<Session, String> {
        let response = self
            .http
            .post(format!(
                "{}/auth/v1/token?grant_type={grant}",
                self.config.supabase_url.trim_end_matches('/')
            ))
            .header("apikey", &self.config.publishable_key)
            .json(&body)
            .timeout(Duration::from_secs(20))
            .send()
            .await
            .map_err(|_| "Không kết nối được Supabase Auth")?;
        if !response.status().is_success() {
            return Err("Đăng nhập hết hạn hoặc cấu hình Google chưa đúng".into());
        }
        let data: Value = serde_json::from_slice(&bounded(response, 128 * 1024).await?)
            .map_err(|_| "Phiên Google không hợp lệ")?;
        Ok(Session {
            access_token: data["access_token"]
                .as_str()
                .filter(|s| s.len() <= 8192)
                .ok_or("Thiếu access token")?
                .into(),
            refresh_token: data["refresh_token"]
                .as_str()
                .filter(|s| s.len() <= 8192)
                .ok_or("Thiếu refresh token")?
                .into(),
            user_id: data["user"]["id"]
                .as_str()
                .ok_or("Thiếu tài khoản")?
                .parse()
                .map_err(|_| "Tài khoản không hợp lệ")?,
            email: data["user"]["email"].as_str().unwrap_or("").into(),
            expires_at: seconds() + data["expires_in"].as_u64().unwrap_or(3600),
        })
    }
    pub async fn access_token(&self) -> Result<String, String> {
        let mut current = self.session.lock().await;
        let session = current.as_ref().ok_or("Đăng nhập Google trước")?;
        if session.expires_at < seconds() + 90 {
            let next = self
                .auth_token(
                    "refresh_token",
                    json!({"refresh_token":session.refresh_token}),
                )
                .await?;
            save(&self.root, &next)?;
            *current = Some(next);
        }
        Ok(current
            .as_ref()
            .ok_or("Không có phiên")?
            .access_token
            .clone())
    }
    pub async fn login(&self) -> Result<Value, String> {
        let _listener = tokio::net::TcpListener::bind("127.0.0.1:47821")
            .await
            .map_err(|_| "Cổng đăng nhập 47821 đang được dùng")?;
        let verifier = format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple());
        let challenge = URL_SAFE_NO_PAD.encode(Sha256::digest(verifier.as_bytes()));
        let nonce = Uuid::new_v4().simple().to_string();
        let redirect = format!("http://127.0.0.1:47821/auth/callback?state={nonce}");
        let mut url = reqwest::Url::parse(&format!(
            "{}/auth/v1/authorize",
            self.config.supabase_url.trim_end_matches('/')
        ))
        .map_err(|_| "Supabase URL sai")?;
        url.query_pairs_mut().extend_pairs([
            ("provider", "google"),
            ("redirect_to", redirect.as_str()),
            ("code_challenge", challenge.as_str()),
            ("code_challenge_method", "s256"),
            ("prompt", "select_account"),
        ]);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            std::process::Command::new("rundll32.exe")
                .args(["url.dll,FileProtocolHandler", url.as_str()])
                .creation_flags(0x08000000)
                .spawn()
                .map_err(|_| "Không mở được trình duyệt")?;
        }
        #[cfg(not(windows))]
        {
            return Err("Đăng nhập desktop hỗ trợ Windows".into());
        }
        #[allow(unreachable_code)]
        let code=tokio::time::timeout(Duration::from_secs(180),async{
            loop{
                let(mut socket,_)=_listener.accept().await.map_err(|_|"Đóng callback")?;let mut data=Vec::new();
                let read=tokio::time::timeout(Duration::from_secs(3),async{let mut part=[0u8;1024];while data.len()<8192&&!data.windows(4).any(|v|v==b"\r\n\r\n"){let n=socket.read(&mut part).await?;if n==0{break;}data.extend_from_slice(&part[..n]);}Ok::<_,std::io::Error>(())}).await;
                if !matches!(read,Ok(Ok(()))){continue;}
                let line=std::str::from_utf8(&data).unwrap_or("").lines().next().unwrap_or("");let mut fields=line.split_whitespace();
                if fields.next()!=Some("GET"){continue;}let Some(path)=fields.next()else{continue;};
                let Ok(callback)=reqwest::Url::parse(&format!("http://127.0.0.1:47821{path}"))else{continue;};
                let params=callback.query_pairs().collect::<std::collections::HashMap<_,_>>();
                let valid=callback.path()=="/auth/callback"&&params.get("state").is_some_and(|s|s==&nonce);
                let code=params.get("code").filter(|s|s.len()<4096&&!s.is_empty()).map(|s|s.to_string());
                let text=if valid&&code.is_some(){"Đã trở về VietOCR. Có thể đóng tab này."}else{"Callback không hợp lệ. Quay lại VietOCR và thử đăng nhập."};
                let response=format!("HTTP/1.1 {}\r\nContent-Type: text/plain; charset=utf-8\r\nCache-Control: no-store\r\nConnection: close\r\nContent-Length: {}\r\n\r\n{text}",if valid{"200 OK"}else{"400 Bad Request"},text.len());
                let _=socket.write_all(response.as_bytes()).await;
                if valid&&let Some(code)=code{return Ok::<_,String>(code);}
            }
        }).await.map_err(|_|"Đăng nhập quá hạn 3 phút")??;
        #[allow(unreachable_code)]
        {
            let next = self
                .auth_token("pkce", json!({"auth_code":code,"code_verifier":verifier}))
                .await?;
            save(&self.root, &next)?;
            *self.session.lock().await = Some(next);
            self.verify().await
        }
    }
    pub async fn logout(&self) -> Result<(), String> {
        if let Ok(token) = self.access_token().await {
            let _ = self
                .http
                .post(format!(
                    "{}/auth/v1/logout?scope=local",
                    self.config.supabase_url.trim_end_matches('/')
                ))
                .header("apikey", &self.config.publishable_key)
                .bearer_auth(token)
                .timeout(Duration::from_secs(8))
                .send()
                .await;
        }
        *self.session.lock().await = None;
        match std::fs::remove_file(self.root.join("session.dpapi")) {
            Ok(()) => Ok(()),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(_) => Err("Không xoá được phiên DPAPI".into()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn secrets_roundtrip_current_windows_user_only() {
        if cfg!(windows) {
            let secret = b"test-only-refresh-token";
            let cipher = storage::protect(secret, false).unwrap();
            assert_ne!(cipher, secret);
            assert_eq!(storage::protect(&cipher, true).unwrap(), secret);
        }
    }
    #[test]
    fn client_rejects_credentials_redirects_and_remote_http() {
        for url in [
            "http://public.example.com",
            "https://a.example/x",
            "https://u:p@a.example",
            "https://a.example/?token=x",
        ] {
            assert!(!super::super::secure_origin(url));
        }
        assert!(super::super::secure_origin("https://pi.example.com"));
    }
}
