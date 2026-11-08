use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use serde::Deserialize;
use std::{collections::HashSet, net::SocketAddr, path::Path};

#[derive(Clone, Deserialize)]
#[serde(default, rename_all = "camelCase", deny_unknown_fields)]
pub struct Config {
    pub listen: SocketAddr,
    pub auth: AuthConfig,
    pub cameras: Vec<CameraConfig>,
    pub max_viewers: usize,
    pub max_viewers_per_account: usize,
    pub max_snapshots: usize,
    pub max_frame_bytes: usize,
    pub frame_fresh_ms: u64,
    pub viewer_session_seconds: u64,
    pub auth_recheck_seconds: u64,
    pub telemetry: Option<TelemetryConfig>,
    pub panel: PanelConfig,
}
impl Default for Config {
    fn default() -> Self {
        Self {
            listen: "127.0.0.1:5082".parse().unwrap(),
            auth: AuthConfig::default(),
            cameras: vec![],
            max_viewers: 8,
            max_viewers_per_account: 2,
            max_snapshots: 4,
            max_frame_bytes: 4 * 1024 * 1024,
            frame_fresh_ms: 1500,
            viewer_session_seconds: 600,
            auth_recheck_seconds: 15,
            telemetry: None,
            panel: PanelConfig::default(),
        }
    }
}
#[derive(Clone, Deserialize)]
#[serde(default, rename_all = "camelCase", deny_unknown_fields)]
pub struct AuthConfig {
    pub supabase_url: String,
    pub publishable_key: String,
    pub database_concurrency: usize,
}
impl Default for AuthConfig {
    fn default() -> Self {
        Self {
            supabase_url: "https://rrdxhztiikizgogxtlhu.supabase.co".into(),
            publishable_key: String::new(),
            database_concurrency: 8,
        }
    }
}
#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CameraConfig {
    pub id: String,
    pub name: String,
    pub upstream: String,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TelemetryConfig {
    pub url: String,
    pub token_file: String,
}

#[derive(Clone, Deserialize)]
#[serde(default, rename_all = "camelCase", deny_unknown_fields)]
pub struct PanelConfig {
    pub enabled: bool,
    pub dc_bcm: u8,
    pub reset_bcm: u8,
    pub buzzer_bcm: u8,
    pub spi_hz: u32,
}
impl Default for PanelConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            dc_bcm: 25,
            reset_bcm: 24,
            buzzer_bcm: 18,
            spi_hz: 16_000_000,
        }
    }
}

impl Config {
    pub fn load(path: &Path) -> Result<Self, String> {
        let text =
            std::fs::read_to_string(path).map_err(|_| "Cannot read gateway config".to_string())?;
        let mut value: Self = serde_json::from_str(&text)
            .map_err(|e| format!("Invalid gateway config at line {}", e.line()))?;
        // Publishable, never service-role or signing credentials.
        if let Ok(key) = std::env::var("VIETOCR_SUPABASE_PUBLISHABLE_KEY") {
            value.auth.publishable_key = key;
        }
        value.validate()?;
        Ok(value)
    }
    pub fn validate(&self) -> Result<(), String> {
        let auth =
            reqwest::Url::parse(&self.auth.supabase_url).map_err(|_| "Invalid Supabase URL")?;
        if auth.scheme() != "https"
            || !auth.host_str().is_some_and(|s| s.ends_with(".supabase.co"))
            || auth.path() != "/"
            || auth.query().is_some()
            || auth.fragment().is_some()
            || !auth.username().is_empty()
            || auth.password().is_some()
        {
            return Err("Supabase URL must be an HTTPS project origin".into());
        }
        let public_key = &self.auth.publishable_key;
        let legacy_anon = public_key
            .split('.')
            .nth(1)
            .and_then(|s| URL_SAFE_NO_PAD.decode(s).ok())
            .and_then(|s| serde_json::from_slice::<serde_json::Value>(&s).ok())
            .is_some_and(|v| v["role"] == "anon");
        if public_key.len() < 20
            || public_key.len() > 8192
            || !(public_key.starts_with("sb_publishable_") || legacy_anon)
        {
            return Err("Set a Supabase publishable/anon key, never a secret/service key".into());
        }
        if !(1..=64).contains(&self.max_viewers)
            || !(1..=self.max_viewers).contains(&self.max_viewers_per_account)
            || !(1..=16).contains(&self.max_snapshots)
            || !(1..=32).contains(&self.auth.database_concurrency)
            || !(64 * 1024..=8 * 1024 * 1024).contains(&self.max_frame_bytes)
            || !(100..=5000).contains(&self.frame_fresh_ms)
            || !(10..=600).contains(&self.viewer_session_seconds)
            || !(5..=30).contains(&self.auth_recheck_seconds)
        {
            return Err("Camera/auth resource limits out of range".into());
        }
        if self.cameras.len() > 8 {
            return Err("Configure at most eight capture producers on this Pi".into());
        }
        let mut ids = HashSet::new();
        for c in &self.cameras {
            if c.id.is_empty()
                || c.id.len() > 48
                || !c
                    .id
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
                || !ids.insert(&c.id)
                || c.name.is_empty()
                || c.name.len() > 120
            {
                return Err("Camera ids must be unique, short URL-safe names".into());
            }
            let url = reqwest::Url::parse(&c.upstream).map_err(|_| "Invalid camera upstream")?;
            if url.scheme() != "http"
                || !matches!(url.host_str(), Some("127.0.0.1" | "[::1]" | "localhost"))
                || url.path() != "/"
                || url.query().is_some()
                || url.fragment().is_some()
                || !url.username().is_empty()
                || url.password().is_some()
            {
                return Err(
                    "Camera upstream must be a loopback HTTP origin; do not expose raw uStreamer"
                        .into(),
                );
            }
        }
        if let Some(t) = &self.telemetry {
            let u = reqwest::Url::parse(&t.url).map_err(|_| "Invalid telemetry URL")?;
            if !(u.scheme() == "https"
                || u.scheme() == "http"
                    && matches!(u.host_str(), Some("127.0.0.1" | "localhost" | "[::1]")))
                || !u.username().is_empty()
                || u.password().is_some()
                || u.query().is_some()
                || u.fragment().is_some()
            {
                return Err(
                    "Telemetry needs HTTPS, or HTTP on loopback for local development".into(),
                );
            }
        }
        if self.panel.enabled {
            let pins = [
                self.panel.dc_bcm,
                self.panel.reset_bcm,
                self.panel.buzzer_bcm,
            ];
            if pins.iter().any(|p| {
                ![
                    4, 5, 6, 12, 13, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27,
                ]
                .contains(p)
            }) || pins[0] == pins[1]
                || pins[1] == pins[2]
                || pins[0] == pins[2]
                || !(1_000_000..=32_000_000).contains(&self.panel.spi_hz)
            {
                return Err(
                    "Panel GPIO must use distinct available BCM pins, excluding SPI0 pins".into(),
                );
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn valid() -> Config {
        Config {
            auth: AuthConfig {
                publishable_key: "sb_publishable_example_example".into(),
                ..Default::default()
            },
            ..Default::default()
        }
    }
    #[test]
    fn private_origin_and_resource_limits_are_explicit() {
        let mut c = valid();
        assert!(c.validate().is_ok());
        c.cameras.push(CameraConfig {
            id: "desk".into(),
            name: "Desk camera".into(),
            upstream: "http://192.168.1.2:8080".into(),
        });
        assert!(c.validate().is_err());
        c.cameras[0].upstream = "http://127.0.0.1:8080".into();
        assert!(c.validate().is_ok());
        c.max_viewers = 1000;
        assert!(c.validate().is_err());
    }
    #[test]
    fn panel_cannot_take_over_spi_or_duplicate_pins() {
        let mut c = valid();
        c.panel.enabled = true;
        assert!(c.validate().is_ok());
        c.panel.dc_bcm = 10;
        assert!(c.validate().is_err());
        c.panel.dc_bcm = 18;
        assert!(c.validate().is_err());
    }
    #[test]
    fn service_role_or_secret_credentials_cannot_be_misconfigured_as_public_keys() {
        let mut c = valid();
        c.auth.publishable_key = "sb_secret_never_put_this_on_the_gateway".into();
        assert!(c.validate().is_err());
        c.auth.publishable_key = format!(
            "e30.{}.fake",
            URL_SAFE_NO_PAD.encode(br#"{"role":"service_role"}"#)
        );
        assert!(c.validate().is_err());
    }
}
