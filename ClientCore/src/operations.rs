use super::*;
use tokio::sync::watch;

pub(super) struct Operation {
    pub stop: watch::Sender<bool>,
    pub gate: Mutex<()>,
}
impl Client {
    pub async fn set_included(&self, id: Uuid, included: bool) -> Result<Draft, String> {
        let operation = self.operation(id).await;
        let _guard = operation.gate.lock().await;
        let mut draft = self.draft(id).await?;
        draft.included = included;
        self.save_draft(&draft).await?;
        Ok(draft)
    }

    pub async fn save_text(&self, id: Uuid, text: String) -> Result<(), String> {
        let operation = self.operation(id).await;
        let _guard = operation.gate.lock().await;
        let mut draft = self.draft(id).await?;
        draft.text = text;
        self.save_draft(&draft).await
    }

    pub(super) async fn operation(&self, id: Uuid) -> Arc<Operation> {
        self.operations
            .lock()
            .await
            .entry(id)
            .or_insert_with(|| {
                let (stop, _) = watch::channel(false);
                Arc::new(Operation {
                    stop,
                    gate: Mutex::new(()),
                })
            })
            .clone()
    }

    pub async fn stop_operations(&self) {
        for operation in self.operations.lock().await.values() {
            operation.stop.send_replace(true);
        }
    }

    /// Only an explicit new Send re-arms a stopped operation. Unconfirmed remote
    /// cancellation keeps the original intent, even after restarting the app.
    pub async fn prepare_send(&self, ids: Vec<Uuid>) -> Result<Vec<Draft>, String> {
        let mut prepared = Vec::new();
        for id in ids {
            let operation = self.operation(id).await;
            let _guard = operation.gate.lock().await;
            let mut draft = self.draft(id).await?;
            if draft.state == "cancel_pending" {
                return Err("Cần xác nhận dừng lượt cũ với server trước khi gửi lại.".into());
            }
            if draft.state == "cancelled" {
                draft.request_id = Uuid::new_v4();
                draft.job_id = None;
                draft.layout = None;
                draft.state = "draft".into();
                draft.error.clear();
                draft.text.clear();
            }
            if !matches!(
                draft.state.as_str(),
                "draft" | "awaiting_upload" | "upload_granted" | "uploading"
            ) {
                return Err("Ảnh đã được server nhận; xem kết quả thay vì gửi lại.".into());
            }
            self.save_draft(&draft).await?;
            operation.stop.send_replace(false);
            prepared.push(draft);
        }
        Ok(prepared)
    }

    async fn draft(&self, id: Uuid) -> Result<Draft, String> {
        self.drafts()
            .await?
            .into_iter()
            .find(|d| d.id == id)
            .ok_or_else(|| "Bản nháp không tồn tại".into())
    }

    pub async fn cancel_draft(&self, id: Uuid) -> Result<Draft, String> {
        let operation = self.operation(id).await;
        operation.stop.send_replace(true);
        // Dropping the active HTTP future stops sending further bytes. Wait for
        // its gate before writing, so a late completion cannot overwrite Stop.
        let _guard = operation.gate.lock().await;
        let mut draft = self.draft(id).await?;
        if matches!(
            draft.state.as_str(),
            "succeeded" | "failed" | "cancelled" | "expired"
        ) {
            return Ok(draft);
        }
        if draft.layout.is_none() && draft.job_id.is_none() {
            draft.state = "cancelled".into();
            draft.error.clear();
            self.save_draft(&draft).await?;
            return Ok(draft);
        }
        draft.state = "cancel_pending".into();
        draft.error = "Đã dừng trên máy · đang xác nhận với server".into();
        self.save_draft(&draft).await?;
        match tokio::time::timeout(Duration::from_secs(12), self.cancel_remote(&mut draft)).await {
            Ok(Ok(())) => {}
            Ok(Err(error)) => {
                draft.error = format!("Đã dừng trên máy · chưa xác nhận server: {error}")
            }
            Err(_) => {
                draft.error =
                    "Đã dừng trên máy · server chưa phản hồi. Thử dừng lại khi có mạng.".into()
            }
        }
        self.save_draft(&draft).await?;
        Ok(draft)
    }

    async fn cancel_remote(&self, draft: &mut Draft) -> Result<(), String> {
        let owner = draft.owner_id;
        let job = if let Some(job) = draft.job_id {
            job
        } else {
            // A lost create acknowledgement may hide an existing intent. Resolve
            // the SAME request ID; this sends metadata only, never image content.
            let value = self
                .api_for(
                    Some(owner),
                    reqwest::Method::POST,
                    "/api/v2/intents",
                    Some(Self::intent_metadata(
                        draft,
                        draft.layout.as_deref().unwrap_or("auto"),
                    )),
                )
                .await?;
            let job = value["id"]
                .as_str()
                .ok_or("Thiếu job ID")?
                .parse()
                .map_err(|_| "Job ID lỗi")?;
            draft.job_id = Some(job);
            job
        };
        let value = self
            .api_for(
                Some(owner),
                reqwest::Method::DELETE,
                &format!("/api/v2/intents/{job}/cancel"),
                Some(json!({})),
            )
            .await?;
        let state = value["state"]
            .as_str()
            .unwrap_or(if value["released"] == true {
                "cancelled"
            } else {
                ""
            });
        if !matches!(state, "cancelled" | "succeeded" | "failed") {
            return Err("Server chưa xác nhận dừng công việc".into());
        }
        if state != "cancelled" {
            // The worker may have finished before cancellation. Fetch its text
            // directly from compute, never report a completed job as cancelled.
            let result = self.result(job).await?;
            draft.state = result["state"].as_str().unwrap_or(state).into();
            draft.text = result["text"].as_str().unwrap_or("").into();
            draft.error = result["error"].as_str().unwrap_or("").into();
        } else {
            draft.state = "cancelled".into();
            draft.error = if value["accepted"] == true {
                "Đã dừng · ảnh server đã nhận vẫn tính lượt".into()
            } else {
                String::new()
            };
        }
        Ok(())
    }

    pub async fn read_draft_result(&self, id: Uuid) -> Result<Draft, String> {
        let operation = self.operation(id).await;
        let _guard = operation.gate.lock().await;
        let mut stopped = operation.stop.subscribe();
        if *stopped.borrow() {
            return Err("operation_stopped".into());
        }
        tokio::select! {
            biased;
            _ = stopped.wait_for(|value| *value) => Err("operation_stopped".into()),
            result = self.read_draft_result_inner(id) => result,
        }
    }
    async fn read_draft_result_inner(&self, id: Uuid) -> Result<Draft, String> {
        let mut draft = self.draft(id).await?;
        if draft.state == "cancel_pending" {
            return Err("cancel_pending".into());
        }
        let job = draft.job_id.ok_or("Ảnh chưa gửi")?;
        let result = match self.result(job).await {
            Ok(value) => value,
            Err(error) if error.contains("result_expired") || error.contains("intent_expired") => {
                draft.state = "expired".into();
                draft.error =
                    "Kết quả đã hết thời hạn lưu trên server. Ảnh gốc vẫn được giữ.".into();
                self.save_draft(&draft).await?;
                return Ok(draft);
            }
            Err(error) => return Err(error),
        };
        draft.state = result["state"].as_str().unwrap_or("queued").into();
        draft.text = result["text"].as_str().unwrap_or("").into();
        draft.error = result["error"].as_str().unwrap_or("").into();
        self.save_draft(&draft).await?;
        Ok(draft)
    }
}
