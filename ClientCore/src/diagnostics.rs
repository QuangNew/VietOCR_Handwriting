//! Bounded local diagnostics. Never log tokens, images or recognised text.
use std::{
    path::Path,
    sync::Mutex,
    time::{SystemTime, UNIX_EPOCH},
};
static LOG_LOCK: Mutex<()> = Mutex::new(());
const MAX_BYTES: usize = 256 * 1024;
pub fn append(root: &Path, category: &str, message: &str) {
    let _guard = LOG_LOCK.lock().unwrap_or_else(|p| p.into_inner());
    let folder = root.join("logs");
    if std::fs::create_dir_all(&folder).is_err() {
        return;
    }
    let path = folder.join("client.log");
    let mut previous = std::fs::read_to_string(&path).unwrap_or_default();
    if previous.len() > MAX_BYTES - 4096 {
        let mut start = previous.len() - (MAX_BYTES - 4096);
        while !previous.is_char_boundary(start) {
            start += 1;
        }
        previous.drain(..start);
    }
    let safe = if [
        "Bearer ",
        "refresh_token",
        "access_token",
        "sb_secret_",
        "eyJ",
    ]
    .iter()
    .any(|p| message.contains(p))
    {
        "[credential-like details omitted]".into()
    } else {
        message
            .chars()
            .filter(|c| !c.is_control())
            .take(400)
            .collect::<String>()
    };
    let category = category
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || *c == '_')
        .take(24)
        .collect::<String>();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    previous.push_str(&format!("{now} {category}: {safe}\n"));
    let _ = std::fs::write(path, previous);
}
pub fn read(root: &Path) -> Result<String, String> {
    let _guard = LOG_LOCK.lock().unwrap_or_else(|p| p.into_inner());
    let path = root.join("logs/client.log");
    if !path.is_file() {
        return Ok(String::new());
    }
    let bytes = std::fs::read(path).map_err(|_| "Không đọc được log")?;
    Ok(String::from_utf8_lossy(&bytes[bytes.len().saturating_sub(MAX_BYTES)..]).into_owned())
}
