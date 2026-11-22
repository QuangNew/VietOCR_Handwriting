#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use serde_json::{Value, json};
use std::sync::{
    Arc,
    atomic::{AtomicBool, AtomicU64, Ordering},
};
use tauri::{
    Manager, State,
    ipc::{Channel, InvokeResponseBody},
};
use tauri_plugin_dialog::DialogExt;
use tokio::sync::RwLock;
use uuid::Uuid;
use vietocr_client_core::{Client, Config, Draft};

struct Desktop {
    _workspace_lock: std::fs::File,
    client: RwLock<Arc<Client>>,
    camera_epoch: AtomicU64,
    frame_ready: AtomicBool,
}
impl Desktop {
    async fn client(&self) -> Arc<Client> {
        self.client.read().await.clone()
    }
}
#[tauri::command]
async fn bootstrap(state: State<'_, Desktop>) -> Result<Value, String> {
    let client = state.client().await;
    let session = client
        .session
        .lock()
        .await
        .as_ref()
        .map(|s| json!({"email":s.email,"userId":s.user_id}));
    let verified = client.verify().await.ok();
    let cached = client.drafts().await;
    let workspace_allowed = cached.is_ok();
    let drafts = cached.unwrap_or_default();
    Ok(
        json!({"config":{"gateway":client.config.gateway},"session":session,"verified":verified,"drafts":drafts,"workspaceAllowed":workspace_allowed}),
    )
}
#[tauri::command]
async fn configure(state: State<'_, Desktop>, gateway: String) -> Result<(), String> {
    let old = state.client().await;
    let config = Config {
        gateway,
        ..old.config.clone()
    };
    config.validate()?;
    old.stop_operations().await;
    state.camera_epoch.fetch_add(1, Ordering::SeqCst);
    vietocr_client_core::storage::atomic(
        &old.root.join("config.json"),
        &serde_json::to_vec(&config).map_err(|_| "Cấu hình không hợp lệ")?,
    )?;
    *state.client.write().await = Arc::new(Client::new(config, old.root.clone())?);
    Ok(())
}
#[tauri::command]
async fn login(state: State<'_, Desktop>) -> Result<Value, String> {
    state.client().await.login().await
}
#[tauri::command]
async fn logout(state: State<'_, Desktop>) -> Result<(), String> {
    state.camera_epoch.fetch_add(1, Ordering::SeqCst);
    state.client().await.logout().await
}
#[tauri::command]
async fn draft_image(state: State<'_, Desktop>, id: Uuid) -> Result<String, String> {
    state.client().await.image_url(id).await
}
#[tauri::command]
async fn pick_import(
    app: tauri::AppHandle,
    state: State<'_, Desktop>,
) -> Result<Vec<Draft>, String> {
    let client = state.client().await;
    let owner = client.user().await?;
    let selected = tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .add_filter("Ảnh JPEG / PNG / WebP", &["jpg", "jpeg", "png", "webp"])
            .blocking_pick_files()
    })
    .await
    .map_err(|_| "Không mở được hộp thoại")?;
    let mut result = Vec::new();
    for file in selected.unwrap_or_default() {
        let path = file.into_path().map_err(|_| "Đường dẫn không hợp lệ")?;
        if std::fs::metadata(&path)
            .map_err(|_| "Không đọc được ảnh")?
            .len()
            > 16 * 1024 * 1024
        {
            return Err("Ảnh vượt 16 MiB".into());
        }
        result.push(
            client
                .import_for(
                    owner,
                    std::fs::read(&path).map_err(|_| "Không đọc được ảnh")?,
                    path.file_name()
                        .unwrap_or_default()
                        .to_string_lossy()
                        .to_string(),
                )
                .await?,
        );
    }
    Ok(result)
}
#[tauri::command]
async fn cameras(state: State<'_, Desktop>) -> Result<Value, String> {
    state
        .client()
        .await
        .api(reqwest::Method::GET, "/api/v2/cameras", None)
        .await
}
#[tauri::command]
async fn history(state: State<'_, Desktop>) -> Result<Value, String> {
    state
        .client()
        .await
        .api(reqwest::Method::GET, "/api/v2/intents", None)
        .await
}
#[tauri::command]
async fn history_result(state: State<'_, Desktop>, id: Uuid) -> Result<Value, String> {
    state.client().await.result(id).await
}
#[tauri::command]
async fn record_log(state: State<'_, Desktop>, message: String) -> Result<(), String> {
    vietocr_client_core::diagnostics::append(&state.client().await.root, "client", &message);
    Ok(())
}
#[tauri::command]
async fn read_logs(state: State<'_, Desktop>) -> Result<String, String> {
    vietocr_client_core::diagnostics::read(&state.client().await.root)
}
#[tauri::command]
async fn capture(state: State<'_, Desktop>, id: String) -> Result<Draft, String> {
    state.client().await.snapshot(&id).await
}
#[tauri::command]
async fn camera_stream(
    app: tauri::AppHandle,
    state: State<'_, Desktop>,
    id: String,
    frames: Channel,
) -> Result<(), String> {
    let epoch = state.camera_epoch.fetch_add(1, Ordering::SeqCst) + 1;
    state.frame_ready.store(true, Ordering::SeqCst);
    let client = state.client().await;
    client
        .stream(&id, |frame| {
            let state = app.state::<Desktop>();
            if state.camera_epoch.load(Ordering::SeqCst) != epoch {
                return false;
            }
            if state.frame_ready.swap(false, Ordering::SeqCst) {
                return frames.send(InvokeResponseBody::Raw(frame)).is_ok();
            }
            true
        })
        .await
}
#[tauri::command]
fn camera_ack(state: State<'_, Desktop>) {
    state.frame_ready.store(true, Ordering::SeqCst);
}
#[tauri::command]
fn camera_stop(state: State<'_, Desktop>) {
    state.camera_epoch.fetch_add(1, Ordering::SeqCst);
}
#[tauri::command]
async fn send_draft(
    state: State<'_, Desktop>,
    id: Uuid,
    layout: String,
    correct: Option<bool>,
    progress: Channel<Value>,
) -> Result<Draft, String> {
    state
        .client()
        .await
        .submit_with_correction(id, &layout, correct.unwrap_or(false), |stage, done, total| {
            let _ = progress.send(json!({"stage":stage,"done":done,"total":total}));
        })
        .await
}
#[tauri::command]
async fn read_result(state: State<'_, Desktop>, id: Uuid) -> Result<Draft, String> {
    state.client().await.read_draft_result(id).await
}
#[tauri::command]
async fn prepare_send(state: State<'_, Desktop>, ids: Vec<Uuid>) -> Result<Vec<Draft>, String> {
    state.client().await.prepare_send(ids).await
}
#[tauri::command]
async fn stop_draft(state: State<'_, Desktop>, id: Uuid) -> Result<Draft, String> {
    state.client().await.cancel_draft(id).await
}
#[tauri::command]
async fn save_text(state: State<'_, Desktop>, id: Uuid, text: String) -> Result<(), String> {
    if text.len() > 2 * 1024 * 1024 {
        return Err("Văn bản quá lớn".into());
    }
    state.client().await.save_text(id, text).await
}
#[tauri::command]
async fn save_edit(
    state: State<'_, Desktop>,
    data: String,
    name: String,
    source_id: Option<Uuid>,
) -> Result<Draft, String> {
    let client = state.client().await;
    let source = if let Some(id) = source_id {
        Some(
            client
                .drafts()
                .await?
                .into_iter()
                .find(|d| d.id == id)
                .ok_or("Ảnh gốc không thuộc phiên này")?,
        )
    } else {
        None
    };
    let owner = source
        .as_ref()
        .map(|d| d.owner_id)
        .unwrap_or(client.user().await?);
    let draft = client
        .import_for(owner, vietocr_client_core::decode_png_edit(&data)?, name)
        .await?;
    if let Some(mut original) = source {
        original.included = false;
        client.save_draft(&original).await?;
    }
    Ok(draft)
}
#[tauri::command]
async fn set_included(
    state: State<'_, Desktop>,
    id: Uuid,
    included: bool,
) -> Result<Draft, String> {
    state.client().await.set_included(id, included).await
}
#[tauri::command]
async fn remove_draft(state: State<'_, Desktop>, id: Uuid) -> Result<(), String> {
    state.client().await.remove(id).await
}
#[tauri::command]
async fn export_images(
    app: tauri::AppHandle,
    state: State<'_, Desktop>,
    ids: Vec<Uuid>,
) -> Result<u32, String> {
    let chosen =
        tauri::async_runtime::spawn_blocking(move || app.dialog().file().blocking_pick_folder())
            .await
            .map_err(|_| "Không mở được thư mục")?;
    let Some(chosen) = chosen else {
        return Ok(0);
    };
    let folder = chosen.into_path().map_err(|_| "Đường dẫn không hợp lệ")?;
    let client = state.client().await;
    let all = client.drafts().await?;
    let mut count = 0;
    for id in ids {
        let draft = all.iter().find(|d| d.id == id).ok_or("Ảnh không tồn tại")?;
        let ext = match draft.media_type.as_str() {
            "image/jpeg" => "jpg",
            "image/webp" => "webp",
            _ => "png",
        };
        let path = folder.join(format!("VietHandOCR-{id}.{ext}"));
        if !path.exists() {
            vietocr_client_core::storage::atomic(&path, &client.image_bytes(id).await?)?;
        }
        count += 1;
    }
    Ok(count)
}
#[tauri::command]
async fn export_text(app: tauri::AppHandle, state: State<'_, Desktop>) -> Result<(), String> {
    let path = tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .set_file_name("VietHandOCR.txt")
            .blocking_save_file()
    })
    .await
    .map_err(|_| "Không mở được hộp thoại")?;
    if let Some(path) = path {
        let text = state
            .client()
            .await
            .drafts()
            .await?
            .iter()
            .filter(|d| !d.text.is_empty())
            .map(|d| d.text.clone())
            .collect::<Vec<_>>()
            .join("\n\n");
        vietocr_client_core::storage::atomic(
            &path.into_path().map_err(|_| "Đường dẫn lỗi")?,
            text.as_bytes(),
        )?;
    }
    Ok(())
}
fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let root = app.path().app_data_dir()?;
            std::fs::create_dir_all(&root)?;
            let Some(workspace_lock) = vietocr_client_core::storage::workspace_lock(&root)? else {
                eprintln!("VietHandOCR đang mở. Vui lòng dùng cửa sổ hiện có.");
                std::process::exit(0);
            };
            let panic_root = root.clone();
            let original_hook = std::panic::take_hook();
            std::panic::set_hook(Box::new(move |info| {
                let location = info
                    .location()
                    .map(|l| format!("{}:{}", l.file(), l.line()))
                    .unwrap_or_else(|| "unknown location".into());
                vietocr_client_core::diagnostics::append(&panic_root, "native_panic", &location);
                original_hook(info);
            }));
            vietocr_client_core::diagnostics::append(&root, "startup", env!("CARGO_PKG_VERSION"));
            let config = std::fs::read(root.join("config.json"))
                .ok()
                .and_then(|s| serde_json::from_slice::<Config>(&s).ok())
                .unwrap_or_else(|| {
                    let cloud: Value = serde_json::from_str(include_str!(
                        "../../../android/assets/config/supabase.json"
                    ))
                    .expect("public config JSON");
                    Config {
                        gateway: "https://api.quangnew.tech".into(),
                        supabase_url: cloud["url"].as_str().unwrap_or("").into(),
                        publishable_key: cloud["publishableKey"].as_str().unwrap_or("").into(),
                    }
                });
            let client = Client::new(config, root).map_err(std::io::Error::other)?;
            app.manage(Desktop {
                _workspace_lock: workspace_lock,
                client: RwLock::new(Arc::new(client)),
                camera_epoch: AtomicU64::new(0),
                frame_ready: AtomicBool::new(true),
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            bootstrap,
            configure,
            login,
            logout,
            draft_image,
            pick_import,
            cameras,
            history,
            history_result,
            record_log,
            read_logs,
            capture,
            camera_stream,
            camera_ack,
            camera_stop,
            send_draft,
            prepare_send,
            stop_draft,
            read_result,
            save_text,
            save_edit,
            set_included,
            remove_draft,
            export_images,
            export_text
        ])
        .run(tauri::generate_context!())
        .expect("VietHandOCR native runtime failed; check Windows/WebView2");
}
