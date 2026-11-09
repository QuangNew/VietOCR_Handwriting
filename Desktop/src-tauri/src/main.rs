#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use std::sync::{Arc,atomic::{AtomicBool,AtomicU64,Ordering}};
use tauri::{Manager,State,ipc::{Channel,InvokeResponseBody}};
use tauri_plugin_dialog::DialogExt;
use tokio::sync::RwLock;
use serde_json::{Value,json};
use uuid::Uuid;
use vietocr_client_core::{Client,Config,Draft};

struct Desktop {client:RwLock<Arc<Client>>,camera_epoch:AtomicU64,frame_ready:AtomicBool}
impl Desktop{async fn client(&self)->Arc<Client>{self.client.read().await.clone()}}
#[tauri::command]async fn bootstrap(state:State<'_,Desktop>)->Result<Value,String>{
    let client=state.client().await;
    let session=client.session.lock().await.as_ref().map(|s|json!({"email":s.email,"userId":s.user_id}));
    let verified=client.verify().await.ok();let cached=client.drafts().await;let workspace_allowed=cached.is_ok();let drafts=cached.unwrap_or_default();
    Ok(json!({"config":client.config,"session":session,"verified":verified,"drafts":drafts,"workspaceAllowed":workspace_allowed}))
}
#[tauri::command]async fn configure(state:State<'_,Desktop>,config:Config)->Result<(),String>{
    config.validate()?;state.camera_epoch.fetch_add(1,Ordering::SeqCst);
    let old=state.client().await;
    vietocr_client_core::storage::atomic(&old.root.join("config.json"),&serde_json::to_vec(&config).map_err(|_|"Cấu hình không hợp lệ")?)?;
    *state.client.write().await=Arc::new(Client::new(config,old.root.clone())?);Ok(())
}
#[tauri::command]async fn login(state:State<'_,Desktop>)->Result<Value,String>{state.client().await.login().await}
#[tauri::command]async fn logout(state:State<'_,Desktop>)->Result<(),String>{state.camera_epoch.fetch_add(1,Ordering::SeqCst);state.client().await.logout().await}
#[tauri::command]async fn draft_image(state:State<'_,Desktop>,id:Uuid)->Result<String,String>{state.client().await.image_url(id).await}
#[tauri::command]async fn pick_import(app:tauri::AppHandle,state:State<'_,Desktop>)->Result<Vec<Draft>,String>{
    let selected=tauri::async_runtime::spawn_blocking(move||app.dialog().file().add_filter("Ảnh JPEG / PNG / WebP",&["jpg","jpeg","png","webp"]).blocking_pick_files()).await.map_err(|_|"Không mở được hộp thoại")?;
    let client=state.client().await;let mut result=Vec::new();
    for file in selected.unwrap_or_default(){let path=file.into_path().map_err(|_|"Đường dẫn không hợp lệ")?;
        if std::fs::metadata(&path).map_err(|_|"Không đọc được ảnh")?.len()>16*1024*1024{return Err("Ảnh vượt 16 MiB".into());}
        result.push(client.import(std::fs::read(&path).map_err(|_|"Không đọc được ảnh")?,path.file_name().unwrap_or_default().to_string_lossy().to_string()).await?);}
    Ok(result)
}
#[tauri::command]async fn cameras(state:State<'_,Desktop>)->Result<Value,String>{state.client().await.api(reqwest::Method::GET,"/api/v2/cameras",None).await}
#[tauri::command]async fn history(state:State<'_,Desktop>)->Result<Value,String>{state.client().await.api(reqwest::Method::GET,"/api/v2/intents",None).await}
#[tauri::command]async fn history_result(state:State<'_,Desktop>,id:Uuid)->Result<Value,String>{state.client().await.result(id).await}
#[tauri::command]async fn record_log(state:State<'_,Desktop>,message:String){vietocr_client_core::diagnostics::append(&state.client().await.root,"client",&message);}
#[tauri::command]async fn read_logs(state:State<'_,Desktop>)->Result<String,String>{vietocr_client_core::diagnostics::read(&state.client().await.root)}
#[tauri::command]async fn capture(state:State<'_,Desktop>,id:String)->Result<Draft,String>{state.client().await.snapshot(&id).await}
#[tauri::command]async fn camera_stream(app:tauri::AppHandle,state:State<'_,Desktop>,id:String,frames:Channel)->Result<(),String>{
    let epoch=state.camera_epoch.fetch_add(1,Ordering::SeqCst)+1;state.frame_ready.store(true,Ordering::SeqCst);let client=state.client().await;
    client.stream(&id,|frame|{let state=app.state::<Desktop>();if state.camera_epoch.load(Ordering::SeqCst)!=epoch{return false;}
        if state.frame_ready.swap(false,Ordering::SeqCst){return frames.send(InvokeResponseBody::Raw(frame)).is_ok();}true}).await
}
#[tauri::command]fn camera_ack(state:State<'_,Desktop>){state.frame_ready.store(true,Ordering::SeqCst);}
#[tauri::command]fn camera_stop(state:State<'_,Desktop>){state.camera_epoch.fetch_add(1,Ordering::SeqCst);}
#[tauri::command]async fn send_draft(state:State<'_,Desktop>,id:Uuid,layout:String,progress:Channel<Value>)->Result<Draft,String>{
    state.client().await.submit(id,&layout,|stage,done,total|{let _=progress.send(json!({"stage":stage,"done":done,"total":total}));}).await
}
#[tauri::command]async fn read_result(state:State<'_,Desktop>,id:Uuid)->Result<Draft,String>{
    let client=state.client().await;let mut draft=client.drafts().await?.into_iter().find(|d|d.id==id).ok_or("Bản nháp không tồn tại")?;
    let job=draft.job_id.ok_or("Ảnh chưa gửi")?;let result=match client.result(job).await {
        Ok(value)=>value,
        Err(error) if error.contains("result_expired") || error.contains("intent_expired")=>{
            draft.state="expired".into();draft.error="Kết quả đã hết thời hạn lưu trên server. Ảnh gốc vẫn được giữ.".into();client.save_draft(&draft).await?;return Ok(draft);
        }
        Err(error)=>return Err(error)
    };
    draft.state=result["state"].as_str().unwrap_or("queued").into();draft.text=result["text"].as_str().unwrap_or("").into();draft.error=result["error"].as_str().unwrap_or("").into();client.save_draft(&draft).await?;Ok(draft)
}
#[tauri::command]async fn save_text(state:State<'_,Desktop>,id:Uuid,text:String)->Result<(),String>{
    if text.len()>2*1024*1024{return Err("Văn bản quá lớn".into());}let client=state.client().await;
    let mut draft=client.drafts().await?.into_iter().find(|d|d.id==id).ok_or("Không có bản nháp")?;draft.text=text;client.save_draft(&draft).await
}
#[tauri::command]async fn save_edit(state:State<'_,Desktop>,data:String,name:String)->Result<Draft,String>{state.client().await.import(vietocr_client_core::decode_png_edit(&data)?,name).await}
#[tauri::command]async fn remove_draft(state:State<'_,Desktop>,id:Uuid)->Result<(),String>{state.client().await.remove(id).await}
#[tauri::command]async fn export_images(app:tauri::AppHandle,state:State<'_,Desktop>,ids:Vec<Uuid>)->Result<u32,String>{
    let chosen=tauri::async_runtime::spawn_blocking(move||app.dialog().file().blocking_pick_folder()).await.map_err(|_|"Không mở được thư mục")?;
    let Some(chosen)=chosen else{return Ok(0);};let folder=chosen.into_path().map_err(|_|"Đường dẫn không hợp lệ")?;let client=state.client().await;let all=client.drafts().await?;let mut count=0;
    for id in ids {let draft=all.iter().find(|d|d.id==id).ok_or("Ảnh không tồn tại")?;let ext=match draft.media_type.as_str(){"image/jpeg"=>"jpg","image/webp"=>"webp",_=>"png"};
        let path=folder.join(format!("VietOCR-{id}.{ext}"));if !path.exists(){vietocr_client_core::storage::atomic(&path,&client.image_bytes(id).await?)?;}count+=1;}
    Ok(count)
}
#[tauri::command]async fn export_text(app:tauri::AppHandle,state:State<'_,Desktop>)->Result<(),String>{
    let path=tauri::async_runtime::spawn_blocking(move||app.dialog().file().set_file_name("VietOCR.txt").blocking_save_file()).await.map_err(|_|"Không mở được hộp thoại")?;
    if let Some(path)=path{let text=state.client().await.drafts().await?.iter().filter(|d|!d.text.is_empty()).map(|d|d.text.clone()).collect::<Vec<_>>().join("\n\n");vietocr_client_core::storage::atomic(&path.into_path().map_err(|_|"Đường dẫn lỗi")?,text.as_bytes())?;}Ok(())
}
fn main(){
    tauri::Builder::default().plugin(tauri_plugin_dialog::init()).setup(|app|{
        let root=app.path().app_data_dir()?;std::fs::create_dir_all(&root)?;
        let panic_root=root.clone();let original_hook=std::panic::take_hook();std::panic::set_hook(Box::new(move|info|{
            let location=info.location().map(|l|format!("{}:{}",l.file(),l.line())).unwrap_or_else(||"unknown location".into());
            vietocr_client_core::diagnostics::append(&panic_root,"native_panic",&location);original_hook(info);
        }));
        vietocr_client_core::diagnostics::append(&root,"startup",env!("CARGO_PKG_VERSION"));
        let config=std::fs::read(root.join("config.json")).ok().and_then(|s|serde_json::from_slice::<Config>(&s).ok()).unwrap_or_else(||{
            let cloud:Value=serde_json::from_str(include_str!("../../../Mobile/assets/config/supabase.json")).expect("public config JSON");
            Config{gateway:"https://api.quangnew.tech".into(),supabase_url:cloud["url"].as_str().unwrap_or("").into(),publishable_key:cloud["publishableKey"].as_str().unwrap_or("").into()}
        });
        let client=Client::new(config,root).map_err(std::io::Error::other)?;
        app.manage(Desktop{client:RwLock::new(Arc::new(client)),camera_epoch:AtomicU64::new(0),frame_ready:AtomicBool::new(true)});Ok(())
    }).invoke_handler(tauri::generate_handler![bootstrap,configure,login,logout,draft_image,pick_import,cameras,history,history_result,record_log,read_logs,capture,camera_stream,camera_ack,camera_stop,send_draft,read_result,save_text,save_edit,remove_draft,export_images,export_text])
    .run(tauri::generate_context!()).expect("VietOCR native runtime failed; check Windows/WebView2");
}
