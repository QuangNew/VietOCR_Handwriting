use super::*;

/// Immutable upload derivative. The editable/exportable original is never replaced.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TransferImage {
    pub media_type: String,
    pub image_bytes: u64,
    pub sha256: String,
}

impl Client {
    pub(super) async fn prepare_transfer(&self, draft: &mut Draft) -> Result<(), String> {
        if draft.transfer.is_some() || !draft.transfer_note.is_empty() {
            return Ok(());
        }
        // The permit lives inside the blocking encoder: cancelling an async send
        // cannot leave several detached, memory-heavy encoders running together.
        static ENCODER: Semaphore = Semaphore::const_new(1);
        let slot = ENCODER.acquire().await.map_err(|_| "Ứng dụng đã đóng")?;
        let bytes = self.image_bytes(draft.id).await?;
        let optimized = tokio::task::spawn_blocking(move || {
            let _slot = slot;
            image_transfer::optimize(&bytes)
        })
        .await
        .map_err(|_| "Không tối ưu được ảnh")??;
        if let Some(image) = optimized {
            let root = self.account_path(draft.owner_id)?;
            storage::atomic(&root.join(format!("{}.upload", draft.id)), &image.bytes)?;
            draft.transfer = Some(TransferImage {
                media_type: image.media.into(),
                image_bytes: image.bytes.len() as u64,
                sha256: format!("{:x}", Sha256::digest(&image.bytes)),
            });
            draft.transfer_note = if image.lossless {
                "Đã tối ưu PNG · giữ nguyên pixel và độ phân giải"
            } else {
                "Đã tối ưu JPEG95 · giữ nguyên độ phân giải"
            }
            .into();
        } else {
            draft.transfer_note = "Giữ bản gốc · ảnh đã gọn hoặc cần giữ profile màu".into();
        }
        self.save_draft(draft).await
    }

    pub(super) fn intent_metadata(draft: &Draft, layout: &str, correct: bool) -> Value {
        let transfer = draft.transfer.as_ref();
        json!({
            "requestId": draft.request_id,
            "sha256": transfer.map(|t| t.sha256.as_str()).unwrap_or(&draft.sha256),
            "imageBytes": transfer.map(|t| t.image_bytes).unwrap_or(draft.image_bytes),
            "mediaType": transfer.map(|t| t.media_type.as_str()).unwrap_or(&draft.media_type),
            "layout": layout,
            "imageVersion": draft.version,
            "correct": correct
        })
    }

    pub(super) async fn transfer_bytes(&self, draft: &Draft) -> Result<Vec<u8>, String> {
        if let Some(transfer) = &draft.transfer {
            let bytes = std::fs::read(
                self.account_root()
                    .await?
                    .join(format!("{}.upload", draft.id)),
            )
            .map_err(|_| "Thiếu bản ảnh gửi. Giữ ảnh gốc và dừng lượt cũ trước khi gửi lại.")?;
            if bytes.len() as u64 != transfer.image_bytes
                || format!("{:x}", Sha256::digest(&bytes)) != transfer.sha256
            {
                return Err("Bản ảnh gửi không toàn vẹn; dừng lượt cũ trước khi gửi lại.".into());
            }
            Ok(bytes)
        } else {
            self.image_bytes(draft.id).await
        }
    }
}
