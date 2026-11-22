use crate::{auth::bounded_bytes, camera::unix_ms, config::TelemetryConfig};
use serde::Serialize;
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::sync::watch;
use vietocr_contracts::ServerStats;

pub const ENTER_PERCENT: f64 = 85.0;
pub const CLEAR_PERCENT: f64 = 80.0;
pub const STALE_MS: u64 = 10_000;
const HOLD: Duration = Duration::from_secs(5);
const COOLDOWN: Duration = Duration::from_secs(60);

#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PanelUpdate {
    pub server: Option<ServerStats>,
    pub received_unix_ms: Option<u64>,
    pub alarm_active: bool,
    pub buzzer_sequence: u64,
    pub error: Option<&'static str>,
}

#[derive(Default)]
pub struct Alarm {
    high_since: Option<Instant>,
    latched: bool,
    last_pulse: Option<Instant>,
}
impl Alarm {
    /// Exactly one short pulse per high-load episode. Rearm requires all three valid inputs <80%.
    pub fn evaluate(&mut self, stats: Option<&ServerStats>, now: Instant) -> bool {
        let Some(stats) = stats else {
            self.high_since = None;
            return false;
        };
        let inputs = stats.alarm_inputs();
        if inputs.into_iter().flatten().any(|n| n >= ENTER_PERCENT) {
            let since = *self.high_since.get_or_insert(now);
            if !self.latched
                && now.saturating_duration_since(since) >= HOLD
                && self
                    .last_pulse
                    .is_none_or(|p| now.saturating_duration_since(p) >= COOLDOWN)
            {
                self.latched = true;
                self.last_pulse = Some(now);
                return true;
            }
        } else {
            self.high_since = None;
            if inputs
                .into_iter()
                .all(|n| n.is_some_and(|n| n < CLEAR_PERCENT))
            {
                self.latched = false;
            }
        }
        false
    }
    pub fn active(&self, stats: Option<&ServerStats>) -> bool {
        stats.is_some_and(|s| {
            self.latched
                && s.alarm_inputs()
                    .into_iter()
                    .flatten()
                    .any(|n| n >= CLEAR_PERCENT)
        })
    }
}

pub async fn monitor(config: Option<TelemetryConfig>, tx: watch::Sender<PanelUpdate>) {
    let Some(config) = config else {
        tx.send_replace(PanelUpdate {
            error: Some("server_telemetry_not_configured"),
            ..Default::default()
        });
        return;
    };
    let token = match tokio::fs::read_to_string(&config.token_file).await {
        Ok(s)
            if (32..=256).contains(&s.trim().len())
                && s.trim()
                    .bytes()
                    .all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_') =>
        {
            Arc::<str>::from(s.trim())
        }
        _ => {
            tx.send_replace(PanelUpdate {
                error: Some("server_telemetry_key_missing"),
                ..Default::default()
            });
            return;
        }
    };
    let http = match reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .connect_timeout(Duration::from_secs(1))
        .redirect(reqwest::redirect::Policy::none())
        .build()
    {
        Ok(h) => h,
        Err(_) => return,
    };
    let mut timer = tokio::time::interval(Duration::from_secs(2));
    timer.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let mut alarm = Alarm::default();
    let mut pulse_sequence = 0;
    loop {
        timer.tick().await;
        let result = fetch(&http, &config.url, &token).await;
        let stats = result.as_ref().ok();
        if alarm.evaluate(stats, Instant::now()) {
            pulse_sequence += 1;
            tracing::warn!("Server CPU, RAM or busy workers sustained >=85%; one buzzer pulse");
        }
        let update = PanelUpdate {
            server: stats.cloned(),
            received_unix_ms: stats.map(|_| unix_ms()),
            alarm_active: alarm.active(stats),
            buzzer_sequence: pulse_sequence,
            error: result.err(),
        };
        tx.send_replace(update);
    }
}
async fn fetch(
    http: &reqwest::Client,
    url: &str,
    token: &str,
) -> Result<ServerStats, &'static str> {
    let response = http
        .get(url)
        .bearer_auth(token)
        .send()
        .await
        .map_err(|_| "server_offline")?;
    if !response.status().is_success() {
        return Err("server_telemetry_rejected");
    }
    let bytes = bounded_bytes(response, 64 * 1024)
        .await
        .map_err(|_| "server_telemetry_invalid")?;
    let stats: ServerStats =
        serde_json::from_slice(&bytes).map_err(|_| "server_telemetry_invalid")?;
    stats.validate()?;
    let now = unix_ms();
    if stats.sampled_at_unix_ms > now + 5000
        || now.saturating_sub(stats.sampled_at_unix_ms) > STALE_MS
    {
        return Err("server_telemetry_stale");
    }
    Ok(stats)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn stats(cpu: f64, ram: f64, busy: u32, idle: u32) -> ServerStats {
        ServerStats {
            server_id: "compute".into(),
            sampled_at_unix_ms: unix_ms(),
            uptime_seconds: 1.,
            ready: true,
            cpu_percent: Some(cpu),
            ram_used_percent: Some(ram),
            busy_workers: busy,
            idle_workers: idle,
            starting_workers: 9,
            draining_workers: 2,
            queued_jobs: 1,
        }
    }
    #[test]
    fn each_requested_server_metric_can_trigger_with_hold_and_no_repeat() {
        for input in [
            stats(85., 10., 0, 1),
            stats(10., 85., 0, 1),
            stats(10., 10., 17, 3),
        ] {
            let mut a = Alarm::default();
            let t = Instant::now();
            assert!(!a.evaluate(Some(&input), t));
            assert!(!a.evaluate(Some(&input), t + Duration::from_secs(4)));
            assert!(a.evaluate(Some(&input), t + Duration::from_secs(5)));
            assert!(!a.evaluate(Some(&input), t + Duration::from_secs(500)));
        }
    }
    #[test]
    fn offline_and_boot_never_sound_and_reset_pending_hold() {
        let mut a = Alarm::default();
        let t = Instant::now();
        let high = stats(90., 10., 0, 1);
        assert!(!a.evaluate(None, t));
        assert!(!a.evaluate(Some(&high), t));
        assert!(!a.evaluate(None, t + Duration::from_secs(4)));
        assert!(!a.evaluate(Some(&high), t + Duration::from_secs(5)));
        assert!(a.evaluate(Some(&high), t + Duration::from_secs(10)));
        assert!(!a.evaluate(None, t + Duration::from_secs(100)));
        assert!(!a.active(None));
    }
    #[test]
    fn rearm_needs_all_below_80_and_cooldown_not_just_one_metric() {
        let mut a = Alarm::default();
        let t = Instant::now();
        let high = stats(90., 10., 0, 1);
        a.evaluate(Some(&high), t);
        assert!(a.evaluate(Some(&high), t + HOLD));
        a.evaluate(Some(&stats(20., 81., 0, 1)), t + Duration::from_secs(10));
        assert!(!a.evaluate(Some(&high), t + Duration::from_secs(70)));
        a.evaluate(Some(&stats(20., 20., 0, 1)), t + Duration::from_secs(71));
        assert!(!a.evaluate(Some(&high), t + Duration::from_secs(72)));
        assert!(a.evaluate(Some(&high), t + Duration::from_secs(77)));
    }
    #[test]
    fn missing_worker_capacity_does_not_rearm_or_divide_by_zero() {
        let s = stats(10., 10., 0, 0);
        assert_eq!(s.worker_used_percent(), None);
        let mut a = Alarm::default();
        let t = Instant::now();
        let high = stats(90., 10., 0, 1);
        a.evaluate(Some(&high), t);
        a.evaluate(Some(&high), t + HOLD);
        a.evaluate(Some(&s), t + Duration::from_secs(100));
        assert!(!a.evaluate(Some(&high), t + Duration::from_secs(101)));
    }
}
