//! Hardware-independent ILI9341 framebuffer, compiled/tested on the host as well as the Pi.
use crate::{
    camera::unix_ms,
    telemetry::{PanelUpdate, STALE_MS},
};
use embedded_graphics::{
    draw_target::DrawTarget,
    geometry::{OriginDimensions, Size},
    mono_font::{MonoTextStyle, ascii::FONT_9X18_BOLD},
    pixelcolor::{Rgb565, RgbColor},
    prelude::*,
    text::Text,
};
use std::convert::Infallible;

pub struct PanelCanvas {
    pub pixels: Vec<u8>,
}
impl Default for PanelCanvas {
    fn default() -> Self {
        Self {
            pixels: vec![0; 320 * 240 * 2],
        }
    }
}
impl PanelCanvas {
    fn line(&mut self, label: &str, y: i32, color: Rgb565) {
        let _ = Text::new(
            label,
            Point::new(10, y),
            MonoTextStyle::new(&FONT_9X18_BOLD, color),
        )
        .draw(self);
    }
    pub fn render(&mut self, update: &PanelUpdate) {
        self.pixels.fill(0);
        self.line("VietHandOCR / SERVER", 25, Rgb565::CYAN);
        let fresh = update
            .server
            .as_ref()
            .filter(|s| unix_ms().saturating_sub(s.sampled_at_unix_ms) <= STALE_MS);
        if let Some(s) = fresh {
            self.line(
                if s.ready { "ONLINE" } else { "NOT READY" },
                52,
                if s.ready {
                    Rgb565::GREEN
                } else {
                    Rgb565::YELLOW
                },
            );
            let percent = |n: Option<f64>| n.map_or("--".into(), |n| format!("{n:.0}%"));
            self.line(
                &format!("CPU  {}", percent(s.cpu_percent)),
                83,
                Rgb565::WHITE,
            );
            self.line(
                &format!("RAM  {}", percent(s.ram_used_percent)),
                111,
                Rgb565::WHITE,
            );
            self.line(
                &format!(
                    "WORK {}  {}/{} busy",
                    percent(s.worker_used_percent()),
                    s.busy_workers,
                    u64::from(s.idle_workers) + u64::from(s.busy_workers)
                ),
                139,
                Rgb565::WHITE,
            );
            self.line(&format!("QUEUE {}", s.queued_jobs), 167, Rgb565::WHITE);
            self.line(
                if update.alarm_active {
                    "LOAD ALERT (85%)"
                } else {
                    "Status updated / 2s"
                },
                203,
                if update.alarm_active {
                    Rgb565::RED
                } else {
                    Rgb565::GREEN
                },
            );
        } else {
            self.line("SERVER OFFLINE / STALE", 85, Rgb565::YELLOW);
            self.line("No current server stats", 120, Rgb565::WHITE);
        }
    }
}
impl OriginDimensions for PanelCanvas {
    fn size(&self) -> Size {
        Size::new(320, 240)
    }
}
impl DrawTarget for PanelCanvas {
    type Color = Rgb565;
    type Error = Infallible;
    fn draw_iter<I: IntoIterator<Item = Pixel<Self::Color>>>(
        &mut self,
        pixels: I,
    ) -> Result<(), Self::Error> {
        for Pixel(p, color) in pixels {
            if (0..320).contains(&p.x) && (0..240).contains(&p.y) {
                let offset = (p.y as usize * 320 + p.x as usize) * 2;
                self.pixels[offset..offset + 2]
                    .copy_from_slice(&color.into_storage().to_be_bytes());
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use vietocr_contracts::ServerStats;
    #[test]
    fn stale_server_cannot_leave_old_live_values_on_tft() {
        let mut canvas = PanelCanvas::default();
        canvas.render(&PanelUpdate::default());
        let offline = canvas.pixels.clone();
        let mut update = PanelUpdate {
            server: Some(ServerStats {
                server_id: "compute-1".into(),
                sampled_at_unix_ms: unix_ms(),
                uptime_seconds: 9.,
                ready: true,
                cpu_percent: Some(85.),
                ram_used_percent: Some(30.),
                idle_workers: 1,
                busy_workers: 1,
                starting_workers: 0,
                draining_workers: 0,
                queued_jobs: 4,
            }),
            ..Default::default()
        };
        canvas.render(&update);
        assert_ne!(canvas.pixels, offline);
        update.server.as_mut().unwrap().sampled_at_unix_ms = unix_ms() - STALE_MS - 1;
        canvas.render(&update);
        assert_eq!(canvas.pixels, offline);
        assert_eq!(canvas.pixels.len(), 153600);
    }
}
