//! Native client owns credentials/files/network; the webview only renders UI.
pub mod diagnostics;
pub mod image_headers;
pub mod image_transfer;
mod operations;
pub mod session;
pub mod storage;
#[cfg(test)]
mod tests;
mod transfer;
use base64::{Engine, engine::general_purpose::STANDARD};
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::HashMap,
    path::{Path, PathBuf},
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::sync::{Mutex, Semaphore};
pub use transfer::TransferImage;
use uuid::Uuid;
use vietocr_contracts::mjpeg::MjpegParser;

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Config {
    pub gateway: String,
    pub supabase_url: String,
    pub publishable_key: String,
}
impl Config {
    pub fn validate(&self) -> Result<(), String> {
        if !secure_origin(&self.gateway)
            || !secure_origin(&self.supabase_url)
            || !self.supabase_url.ends_with(".supabase.co")
            || !self.publishable_key.starts_with("sb_publishable_")
        {
            return Err("Cần HTTPS gateway, Supabase project và publishable key công khai.".into());
        }
        Ok(())
    }
}
pub fn secure_origin(value: &str) -> bool {
    reqwest::Url::parse(value).is_ok_and(|u| {
        (u.scheme() == "https"
            || u.scheme() == "http"
                && matches!(u.host_str(), Some("localhost" | "127.0.0.1" | "[::1]")))
            && u.path() == "/"
            && u.username().is_empty()
            && u.password().is_none()
            && u.query().is_none()
            && u.fragment().is_none()
    })
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Draft {
    pub id: Uuid,
    #[serde(default)]
    pub owner_id: Uuid,
    pub name: String,
    pub media_type: String,
    pub image_bytes: u64,
    #[serde(default)]
    pub width: u32,
    #[serde(default)]
    pub height: u32,
    pub sha256: String,
    pub version: u32,
    pub state: String,
    #[serde(default = "included_by_default")]
    pub included: bool,
    pub request_id: Uuid,
    pub job_id: Option<Uuid>,
    pub text: String,
    pub error: String,
    #[serde(default)]
    pub layout: Option<String>,
    #[serde(default)]
    pub transfer_note: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub transfer: Option<transfer::TransferImage>,
}
fn included_by_default() -> bool {
    true
}
#[derive(Clone)]
struct CachedResultTicket {
    owner: Uuid,
    url: reqwest::Url,
    bearer: String,
    expires: Instant,
}
pub struct Client {
    pub config: Config,
    pub root: PathBuf,
    pub http: reqwest::Client,
    pub session: Mutex<Option<session::Session>>,
    pub draft_lock: Mutex<()>,
    result_tickets: Mutex<HashMap<Uuid, CachedResultTicket>>,
    result_slots: Semaphore,
    operations: Mutex<HashMap<Uuid, Arc<operations::Operation>>>,
}
impl Client {
    pub async fn remove(&self, id: Uuid) -> Result<(), String> {
        let operation = self.operation(id).await;
        let _operation_guard = operation.gate.lock().await;
        let _lock = self.draft_lock.lock().await;
        let root = self.account_root().await?;
        let mut all = self.read_drafts(&root)?;
        if all.iter().any(|d| {
            d.id == id
                && !matches!(
                    d.state.as_str(),
                    "draft" | "succeeded" | "failed" | "cancelled" | "expired"
                )
        }) {
            return Err("Dừng lượt gửi và xác nhận với server trước khi xoá ảnh".into());
        }
        all.retain(|d| d.id != id);
        storage::atomic(
            &root.join("drafts.json"),
            &serde_json::to_vec(&all).map_err(|_| "Không lưu được danh sách")?,
        )?;
        let _ = std::fs::remove_file(root.join(format!("{id}.image")));
        let _ = std::fs::remove_file(root.join(format!("{id}.upload")));
        Ok(())
    }
    pub fn new(config: Config, root: PathBuf) -> Result<Self, String> {
        config.validate()?;
        std::fs::create_dir_all(&root).map_err(|_| "Không tạo được thư mục ứng dụng")?;
        let session = session::load(&root).ok();
        Ok(Self {
            config,
            root,
            http: reqwest::Client::builder()
                .redirect(reqwest::redirect::Policy::none())
                .connect_timeout(Duration::from_secs(10))
                .build()
                .map_err(|_| "Không tạo được kết nối")?,
            session: Mutex::new(session),
            draft_lock: Mutex::new(()),
            result_tickets: Mutex::new(HashMap::new()),
            result_slots: Semaphore::new(4),
            operations: Mutex::new(HashMap::new()),
        })
    }
    pub async fn response(response: reqwest::Response) -> Result<Value, String> {
        let status = response.status();
        let bytes = bounded(response, 2 * 1024 * 1024).await?;
        let value: Value =
            serde_json::from_slice(&bytes).map_err(|_| "Phản hồi JSON không hợp lệ")?;
        if !status.is_success() {
            return Err(format!(
                "{} (HTTP {})",
                value["error"].as_str().unwrap_or("network_error"),
                status.as_u16()
            ));
        }
        Ok(value)
    }
    pub async fn api(
        &self,
        method: reqwest::Method,
        path: &str,
        body: Option<Value>,
    ) -> Result<Value, String> {
        self.api_for(None, method, path, body).await
    }
    async fn api_for(
        &self,
        owner: Option<Uuid>,
        method: reqwest::Method,
        path: &str,
        body: Option<Value>,
    ) -> Result<Value, String> {
        let token = self.access_token_for(owner).await?;
        let mut request = self
            .http
            .request(
                method,
                format!("{}{}", self.config.gateway.trim_end_matches('/'), path),
            )
            .bearer_auth(token)
            .timeout(Duration::from_secs(30));
        if let Some(body) = body {
            request = request.json(&body);
        }
        Self::response(
            request
                .send()
                .await
                .map_err(|_| "Không kết nối được Raspberry")?,
        )
        .await
    }
    pub async fn verify(&self) -> Result<Value, String> {
        let value = self
            .api(reqwest::Method::GET, "/api/v2/session", None)
            .await?;
        let user = self.user().await?;
        if value["account"]["userId"].as_str() != Some(&user.to_string()) {
            return Err("Phiên Raspberry không trùng tài khoản".into());
        }
        storage::atomic(&self.root.join(format!("verified-{user}")), b"verified")?;
        Ok(value)
    }
    pub async fn user(&self) -> Result<Uuid, String> {
        self.session
            .lock()
            .await
            .as_ref()
            .map(|s| s.user_id)
            .ok_or_else(|| "Đăng nhập Google trước".into())
    }
    async fn account_root(&self) -> Result<PathBuf, String> {
        self.account_path(self.user().await?)
    }
    fn account_path(&self, user: Uuid) -> Result<PathBuf, String> {
        if !self.root.join(format!("verified-{user}")).is_file() {
            return Err("Xác minh phiên với Raspberry trước".into());
        }
        let path = self.root.join("accounts").join(user.to_string());
        std::fs::create_dir_all(&path).map_err(|_| "Không tạo được bản nháp")?;
        Ok(path)
    }
    pub async fn drafts(&self) -> Result<Vec<Draft>, String> {
        let _lock = self.draft_lock.lock().await;
        self.read_drafts(&self.account_root().await?)
    }
    fn read_drafts(&self, root: &Path) -> Result<Vec<Draft>, String> {
        let path = root.join("drafts.json");
        if !path.exists() {
            return Ok(vec![]);
        }
        let mut drafts: Vec<Draft> =
            serde_json::from_slice(&std::fs::read(path).map_err(|_| "Không đọc được bản nháp")?)
                .map_err(|_| "Danh sách bản nháp lỗi")?;
        let owner: Uuid = root
            .file_name()
            .and_then(|s| s.to_str())
            .ok_or("Tài khoản lỗi")?
            .parse()
            .map_err(|_| "Tài khoản lỗi")?;
        for draft in &mut drafts {
            if draft.owner_id.is_nil() {
                draft.owner_id = owner;
            }
            if draft.owner_id != owner {
                return Err("Bản nháp không thuộc tài khoản".into());
            }
        }
        Ok(drafts)
    }
    pub async fn save_draft(&self, draft: &Draft) -> Result<(), String> {
        let _lock = self.draft_lock.lock().await;
        let session = self.session.lock().await;
        let owner = session.as_ref().ok_or("Đăng nhập Google trước")?.user_id;
        if draft.owner_id != owner {
            return Err("Tài khoản đã thay đổi; giữ bản nháp ở tài khoản gốc".into());
        }
        let root = self.account_path(owner)?;
        let mut all = self.read_drafts(&root)?;
        if let Some(i) = all.iter().position(|d| d.id == draft.id) {
            all[i] = draft.clone();
        } else {
            all.push(draft.clone());
        }
        storage::atomic(
            &root.join("drafts.json"),
            &serde_json::to_vec(&all).map_err(|_| "Không lưu được bản nháp")?,
        )
    }
    pub async fn import(&self, bytes: Vec<u8>, name: String) -> Result<Draft, String> {
        self.import_for(self.user().await?, bytes, name).await
    }
    pub async fn import_for(
        &self,
        owner: Uuid,
        bytes: Vec<u8>,
        name: String,
    ) -> Result<Draft, String> {
        if bytes.len() < 16 || bytes.len() > 16 * 1024 * 1024 {
            return Err("Ảnh hỗ trợ 16 byte..16 MiB; crop ảnh lớn trước".into());
        }
        let (media, width, height) = image_headers::inspect(&bytes)?;
        let id = Uuid::new_v4();
        let root = self.account_path(owner)?;
        storage::atomic(&root.join(format!("{id}.image")), &bytes)?;
        let draft = Draft {
            id,
            owner_id: owner,
            name: name.chars().take(160).collect(),
            media_type: media.into(),
            image_bytes: bytes.len() as u64,
            width,
            height,
            sha256: format!("{:x}", Sha256::digest(&bytes)),
            version: 1,
            state: "draft".into(),
            included: true,
            request_id: Uuid::new_v4(),
            job_id: None,
            text: String::new(),
            error: String::new(),
            layout: None,
            transfer_note: String::new(),
            transfer: None,
        };
        self.save_draft(&draft).await?;
        Ok(draft)
    }
    pub async fn image_bytes(&self, id: Uuid) -> Result<Vec<u8>, String> {
        std::fs::read(self.account_root().await?.join(format!("{id}.image")))
            .map_err(|_| "Không đọc được ảnh gốc".into())
    }
    pub async fn image_url(&self, id: Uuid) -> Result<String, String> {
        let draft = self
            .drafts()
            .await?
            .into_iter()
            .find(|d| d.id == id)
            .ok_or("Không có ảnh")?;
        Ok(format!(
            "data:{};base64,{}",
            draft.media_type,
            STANDARD.encode(self.image_bytes(id).await?)
        ))
    }
    pub async fn snapshot(&self, camera: &str) -> Result<Draft, String> {
        let camera = checked_camera(camera)?;
        let owner = self.user().await?;
        let token = self.access_token_for(Some(owner)).await?;
        let response = self
            .http
            .post(format!(
                "{}/api/v2/cameras/{camera}/snapshots",
                self.config.gateway.trim_end_matches('/')
            ))
            .bearer_auth(token)
            .timeout(Duration::from_secs(20))
            .send()
            .await
            .map_err(|_| "Không chụp được camera")?;
        if !response.status().is_success() {
            return Err("Camera chưa sẵn sàng".into());
        }
        let expected = response
            .headers()
            .get("x-image-sha256")
            .and_then(|h| h.to_str().ok())
            .map(str::to_owned);
        let bytes = bounded(response, 8 * 1024 * 1024).await?;
        if expected.is_some_and(|h| h != format!("{:x}", Sha256::digest(&bytes))) {
            return Err("Ảnh sai mã toàn vẹn".into());
        }
        self.import_for(
            owner,
            bytes,
            format!("Raspberry-{}.jpg", Uuid::new_v4().simple()),
        )
        .await
    }
    pub async fn stream(
        &self,
        camera: &str,
        mut on_frame: impl FnMut(Vec<u8>) -> bool,
    ) -> Result<(), String> {
        let camera = checked_camera(camera)?;
        let token = self.access_token().await?;
        let response = self
            .http
            .get(format!(
                "{}/api/v2/cameras/{camera}/stream",
                self.config.gateway.trim_end_matches('/')
            ))
            .bearer_auth(token)
            .send()
            .await
            .map_err(|_| "Không mở được camera")?;
        if !response.status().is_success() {
            return Err("Camera từ chối kết nối".into());
        }
        let mut stream = response.bytes_stream();
        let mut parser = MjpegParser::new(8 * 1024 * 1024);
        while let Some(part) = tokio::time::timeout(Duration::from_secs(20), stream.next())
            .await
            .map_err(|_| "Camera hết thời gian chờ")?
        {
            let part = part.map_err(|_| "Stream bị ngắt")?;
            for chunk in part.chunks(16 * 1024) {
                parser.push(chunk).map_err(str::to_owned)?;
                while let Some(frame) = parser.frame().map_err(str::to_owned)? {
                    if !on_frame(frame.to_vec()) {
                        return Ok(());
                    }
                }
            }
        }
        Ok(())
    }
    pub async fn submit(
        &self,
        id: Uuid,
        layout: &str,
        on_progress: impl FnMut(&str, u64, u64),
    ) -> Result<Draft, String> {
        let operation = self.operation(id).await;
        let _guard = operation.gate.lock().await;
        let mut stopped = operation.stop.subscribe();
        if *stopped.borrow() {
            return Err("operation_stopped".into());
        }
        tokio::select! {
            biased;
            _ = stopped.wait_for(|value| *value) => Err("operation_stopped".into()),
            result = self.submit_inner(id, layout, on_progress) => result,
        }
    }
    async fn submit_inner(
        &self,
        id: Uuid,
        layout: &str,
        mut on_progress: impl FnMut(&str, u64, u64),
    ) -> Result<Draft, String> {
        if !matches!(layout, "auto" | "line") {
            return Err("Cách đọc không hợp lệ".into());
        }
        self.verify().await?;
        let mut draft = self
            .drafts()
            .await?
            .into_iter()
            .find(|d| d.id == id)
            .ok_or("Bản nháp không tồn tại")?;
        let owner = draft.owner_id;
        if draft.state == "cancel_pending" {
            return Err("cancel_pending: Xác nhận dừng lượt cũ trước khi gửi lại".into());
        }
        if draft.layout.is_none() && draft.job_id.is_none() {
            on_progress("optimizing", 0, 0);
            self.prepare_transfer(&mut draft).await?;
        }
        // Retrying a partial upload keeps the original layout/idempotency key.
        let layout = draft.layout.get_or_insert_with(|| layout.into()).clone();
        self.save_draft(&draft).await?;
        let bytes = self.transfer_bytes(&draft).await?;
        let intent = self
            .api_for(
                Some(owner),
                reqwest::Method::POST,
                "/api/v2/intents",
                Some(Self::intent_metadata(&draft, &layout)),
            )
            .await?;
        let job: Uuid = intent["id"]
            .as_str()
            .ok_or("Thiếu job ID")?
            .parse()
            .map_err(|_| "Job ID lỗi")?;
        draft.job_id = Some(job);
        draft.state = intent["state"].as_str().unwrap_or("awaiting_upload").into();
        self.save_draft(&draft).await?;
        if matches!(
            draft.state.as_str(),
            "queued" | "running" | "succeeded" | "failed" | "cancelled"
        ) {
            return Ok(draft);
        }
        if matches!(
            draft.state.as_str(),
            "awaiting_upload" | "upload_granted" | "uploading"
        ) {
            let grant = self
                .api_for(
                    Some(owner),
                    reqwest::Method::POST,
                    &format!("/api/v2/intents/{job}/grant"),
                    Some(json!({})),
                )
                .await?;
            if grant["accepted"] != true {
                let generation = grant["generation"].as_u64().ok_or("Thiếu generation")?;
                let mut offset = grant["offset"].as_u64().ok_or("Thiếu offset")?;
                let image_bytes = bytes.len() as u64;
                while offset < image_bytes {
                    let end = (offset + 1048576).min(image_bytes);
                    on_progress("uploading", offset, image_bytes);
                    let response = self
                        .http
                        .put(format!(
                            "{}/api/v2/intents/{job}/content",
                            self.config.gateway.trim_end_matches('/')
                        ))
                        .bearer_auth(self.access_token_for(Some(owner)).await?)
                        .header("upload-offset", offset)
                        .header("x-ocr-generation", generation)
                        .timeout(Duration::from_secs(30))
                        .body(bytes[offset as usize..end as usize].to_vec())
                        .send()
                        .await
                        .map_err(|_| "Upload gián đoạn; nhấn Gửi để tiếp tục")?;
                    let result = Self::response(response).await?;
                    offset = result["offset"]
                        .as_u64()
                        .filter(|n| *n == end)
                        .ok_or("Offset server không hợp lệ")?;
                }
                self.api_for(
                    Some(owner),
                    reqwest::Method::POST,
                    &format!("/api/v2/intents/{job}/complete"),
                    Some(json!({"generation":generation})),
                )
                .await?;
            }
        }
        draft.state = "queued".into();
        self.save_draft(&draft).await?;
        Ok(draft)
    }
    pub async fn result(&self, id: Uuid) -> Result<Value, String> {
        let _slot = self
            .result_slots
            .acquire()
            .await
            .map_err(|_| "Client đã đóng")?;
        let owner = self.user().await?;
        let cached = self
            .result_tickets
            .lock()
            .await
            .get(&id)
            .filter(|t| t.owner == owner && t.expires > Instant::now())
            .cloned();
        let access = if let Some(ticket) = cached {
            ticket
        } else {
            self.mint_result_ticket(id, owner).await?
        };
        let response = self
            .http
            .get(access.url)
            .query(&[("wait", "8")])
            .bearer_auth(access.bearer)
            .timeout(Duration::from_secs(20))
            .send()
            .await
            .map_err(|_| "Chưa nhận được kết quả; thử lại")?;
        if matches!(response.status().as_u16(), 401 | 403 | 410) {
            self.result_tickets.lock().await.remove(&id);
        }
        Self::response(response).await
    }
    async fn mint_result_ticket(
        &self,
        id: Uuid,
        owner: Uuid,
    ) -> Result<CachedResultTicket, String> {
        let account = self
            .api_for(Some(owner), reqwest::Method::GET, "/api/v2/session", None)
            .await?;
        let origin = account["resultsOrigin"]
            .as_str()
            .ok_or("Chưa có result origin")?;
        if !secure_origin(origin) {
            return Err("Result origin không hợp lệ".into());
        }
        let ticket = self
            .api_for(
                Some(owner),
                reqwest::Method::POST,
                &format!("/api/v2/intents/{id}/result-ticket"),
                Some(json!({})),
            )
            .await?;
        let url = reqwest::Url::parse(ticket["resultUrl"].as_str().ok_or("Result URL thiếu")?)
            .map_err(|_| "Result URL lỗi")?;
        let expected = reqwest::Url::parse(origin).map_err(|_| "Origin lỗi")?;
        if url.origin() != expected.origin()
            || url.path() != format!("/api/v2/results/{id}")
            || url.query().is_some()
            || url.fragment().is_some()
            || !url.username().is_empty()
            || url.password().is_some()
        {
            return Err("Result URL không đúng server".into());
        }
        if self.user().await? != owner {
            return Err("Tài khoản đã thay đổi".into());
        }
        let access = CachedResultTicket {
            owner,
            url,
            bearer: ticket["ticket"].as_str().ok_or("Thiếu vé kết quả")?.into(),
            expires: Instant::now()
                + Duration::from_secs(
                    ticket["expiresIn"]
                        .as_u64()
                        .unwrap_or(60)
                        .min(300)
                        .saturating_sub(15)
                        .max(1),
                ),
        };
        let mut cache = self.result_tickets.lock().await;
        cache.retain(|_, t| t.owner == owner && t.expires > Instant::now());
        if cache.len() >= 64 {
            cache.clear();
        }
        cache.insert(id, access.clone());
        Ok(access)
    }
}
pub async fn bounded(response: reqwest::Response, max: usize) -> Result<Vec<u8>, String> {
    if response.content_length().is_some_and(|n| n > max as u64) {
        return Err("Phản hồi quá lớn".into());
    }
    let mut result = Vec::new();
    let mut stream = response.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|_| "Kết nối gián đoạn")?;
        if chunk.len() > max.saturating_sub(result.len()) {
            return Err("Phản hồi quá lớn".into());
        }
        result.extend_from_slice(&chunk);
    }
    Ok(result)
}
fn checked_camera(camera: &str) -> Result<&str, String> {
    if camera.is_empty()
        || camera.len() > 48
        || !camera
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
    {
        return Err("Camera ID lỗi".into());
    }
    Ok(camera)
}
pub fn decode_png_edit(data: &str) -> Result<Vec<u8>, String> {
    let value = data
        .strip_prefix("data:image/png;base64,")
        .ok_or("Ảnh sửa phải là PNG")?;
    if value.len() > 23 * 1024 * 1024 {
        return Err("Ảnh sửa quá lớn".into());
    }
    let bytes = STANDARD.decode(value).map_err(|_| "PNG không hợp lệ")?;
    if bytes.len() > 16 * 1024 * 1024 || !bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
        return Err("PNG không hợp lệ".into());
    }
    Ok(bytes)
}
