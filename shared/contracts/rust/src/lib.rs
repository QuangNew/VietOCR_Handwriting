//! Versioned, transport-neutral v2 contracts. No bearer tokens or image data in job metadata.
use serde::{Deserialize, Serialize};
use uuid::Uuid;
pub mod mjpeg;

pub const API_VERSION: &str = "2";
pub const DAILY_IMAGE_CAP: u32 = 500;
pub const MINUTE_REQUEST_CAP: u32 = 30;
pub const QUOTA_TIMEZONE: &str = "Asia/Ho_Chi_Minh";

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AccountLimits {
    pub daily_images: u32,
    pub requests_per_minute: u32,
}
impl Default for AccountLimits {
    fn default() -> Self {
        Self {
            daily_images: DAILY_IMAGE_CAP,
            requests_per_minute: MINUTE_REQUEST_CAP,
        }
    }
}
impl AccountLimits {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1..=DAILY_IMAGE_CAP).contains(&self.daily_images)
            || !(1..=MINUTE_REQUEST_CAP).contains(&self.requests_per_minute)
        {
            return Err("account_limits_exceed_policy");
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Layout {
    Auto,
    Line,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum JobState {
    AwaitingUpload,
    UploadGranted,
    Uploading,
    Queued,
    Running,
    Succeeded,
    Failed,
    Cancelled,
}
impl JobState {
    pub fn is_terminal(self) -> bool {
        matches!(self, Self::Succeeded | Self::Failed | Self::Cancelled)
    }
    /// Requeue/retry requires a new fenced attempt; it is not a client state transition.
    pub fn can_transition_to(self, next: Self) -> bool {
        use JobState::*;
        matches!(
            (self, next),
            (AwaitingUpload, UploadGranted | Cancelled)
                | (UploadGranted, Uploading | AwaitingUpload | Cancelled)
                | (Uploading, Queued | AwaitingUpload | Cancelled)
                | (Queued, Running | Failed | Cancelled)
                | (Running, Succeeded | Failed | Cancelled)
        )
    }
}

/// Encode raw bytes as lowercase hexadecimal (used for SHA-256 digests).
pub fn hex_lower(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0f) as usize] as char);
    }
    out
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ImageIntent {
    pub request_id: Uuid,
    pub sha256: String,
    pub image_bytes: u64,
    pub media_type: String,
    pub layout: Layout,
    pub image_version: u32,
    #[serde(default)]
    pub correct: bool,
}
impl ImageIntent {
    pub fn validate(&self, max_bytes: u64) -> Result<(), &'static str> {
        if self.request_id.is_nil() || self.image_version == 0 {
            return Err("invalid_intent");
        }
        if self.sha256.len() != 64
            || !self
                .sha256
                .bytes()
                .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
        {
            return Err("invalid_sha256");
        }
        if !(16..=max_bytes).contains(&self.image_bytes) {
            return Err("image_size");
        }
        if !["image/jpeg", "image/png", "image/webp"].contains(&self.media_type.as_str()) {
            return Err("image_type");
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ServerStats {
    pub server_id: String,
    pub sampled_at_unix_ms: u64,
    pub uptime_seconds: f64,
    pub ready: bool,
    pub cpu_percent: Option<f64>,
    pub ram_used_percent: Option<f64>,
    pub idle_workers: u32,
    pub busy_workers: u32,
    pub starting_workers: u32,
    pub draining_workers: u32,
    pub queued_jobs: u32,
}
impl ServerStats {
    pub fn worker_used_percent(&self) -> Option<f64> {
        let total = u64::from(self.idle_workers) + u64::from(self.busy_workers);
        (total > 0).then(|| f64::from(self.busy_workers) * 100.0 / total as f64)
    }
    pub fn alarm_inputs(&self) -> [Option<f64>; 3] {
        [
            self.cpu_percent,
            self.ram_used_percent,
            self.worker_used_percent(),
        ]
    }
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.server_id.is_empty()
            || self.server_id.len() > 80
            || !self.uptime_seconds.is_finite()
            || self.uptime_seconds < 0.0
        {
            return Err("invalid_server_stats");
        }
        if self
            .alarm_inputs()
            .into_iter()
            .flatten()
            .any(|n| !n.is_finite() || !(0.0..=100.0).contains(&n))
        {
            return Err("invalid_server_stats");
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn quotas_allow_lowering_but_never_raising_caps() {
        let shared: serde_json::Value =
            serde_json::from_str(include_str!("../../fixtures/policy.json")).unwrap();
        assert_eq!(shared["dailyImageCap"], DAILY_IMAGE_CAP);
        assert_eq!(shared["minuteRequestCap"], MINUTE_REQUEST_CAP);
        assert!(AccountLimits::default().validate().is_ok());
        assert!(
            AccountLimits {
                daily_images: 20,
                requests_per_minute: 2
            }
            .validate()
            .is_ok()
        );
        for value in [
            AccountLimits {
                daily_images: 501,
                requests_per_minute: 30,
            },
            AccountLimits {
                daily_images: 500,
                requests_per_minute: 31,
            },
            AccountLimits {
                daily_images: 0,
                requests_per_minute: 1,
            },
        ] {
            assert!(value.validate().is_err());
        }
    }
    #[test]
    fn capture_and_draft_are_not_ocr_states() {
        assert!(serde_json::from_str::<JobState>("\"captured\"").is_err());
        assert!(!JobState::AwaitingUpload.can_transition_to(JobState::Running));
        assert!(!JobState::Succeeded.can_transition_to(JobState::Running));
        assert!(JobState::Uploading.can_transition_to(JobState::Queued));
        assert!(JobState::Uploading.can_transition_to(JobState::AwaitingUpload));
    }
    #[test]
    fn worker_denominator_excludes_loading_draining_and_errors() {
        let stats = ServerStats {
            server_id: "compute-1".into(),
            sampled_at_unix_ms: 1,
            uptime_seconds: 2.0,
            ready: true,
            cpu_percent: None,
            ram_used_percent: Some(30.0),
            idle_workers: 1,
            busy_workers: 3,
            starting_workers: 9,
            draining_workers: 8,
            queued_jobs: 1,
        };
        assert_eq!(stats.worker_used_percent(), Some(75.0));
        assert_eq!(
            ServerStats {
                idle_workers: 0,
                busy_workers: 0,
                ..stats
            }
            .worker_used_percent(),
            None
        );
    }
    #[test]
    fn intent_rejects_unbounded_or_ambiguous_image_metadata() {
        let mut value = ImageIntent {
            request_id: Uuid::new_v4(),
            sha256: "a".repeat(64),
            image_bytes: 256,
            media_type: "image/jpeg".into(),
            layout: Layout::Auto,
            image_version: 1,
            correct: false,
        };
        assert!(value.validate(1024).is_ok());
        // Verify optional `correct` defaults to false when omitted in JSON.
        let decoded: ImageIntent = serde_json::from_str(&format!(
            r#"{{"requestId":"{}","sha256":"{}","imageBytes":256,"mediaType":"image/jpeg","layout":"auto","imageVersion":1}}"#,
            value.request_id, value.sha256
        ))
        .unwrap();
        assert!(!decoded.correct);
        value.image_bytes = 1025;
        assert_eq!(value.validate(1024), Err("image_size"));
        value.image_bytes = 256;
        value.sha256 = "A".repeat(64);
        assert_eq!(value.validate(1024), Err("invalid_sha256"));
    }
}
