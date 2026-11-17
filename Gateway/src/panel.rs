//! Optional Pi monitor. Its blocking SPI/GPIO I/O never runs on the HTTP/camera executor.
use crate::{config::PanelConfig, telemetry::PanelUpdate};
use std::{
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    thread::{self, JoinHandle},
};
use tokio::sync::watch;

pub struct PanelHandle {
    stop: Arc<AtomicBool>,
    join: Option<JoinHandle<()>>,
}
impl Drop for PanelHandle {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(join) = self.join.take() {
            let _ = join.join();
        }
    }
}
pub fn spawn(config: PanelConfig, rx: watch::Receiver<PanelUpdate>) -> Option<PanelHandle> {
    if !config.enabled {
        return None;
    }
    let stop = Arc::new(AtomicBool::new(false));
    let signal = stop.clone();
    let join = thread::Builder::new()
        .name("vietocr-panel".into())
        .spawn(move || {
            #[cfg(target_os = "linux")]
            if let Err(e) = pi::run(config, rx, signal) {
                tracing::error!(error = %e, "TFT/GPIO monitor stopped; API remains available");
            }
            #[cfg(not(target_os = "linux"))]
            {
                let _ = (config, rx, signal);
                tracing::warn!("TFT/GPIO disabled: this host is not a Raspberry Pi Linux system");
            }
        })
        .ok()?;
    Some(PanelHandle {
        stop,
        join: Some(join),
    })
}

#[cfg(target_os = "linux")]
mod pi {
    use super::*;
    use crate::panel_canvas::PanelCanvas;
    use crate::{camera::unix_ms, telemetry::STALE_MS};
    use rppal::{
        gpio::{Gpio, OutputPin},
        spi::{Bus, Mode, SlaveSelect, Spi},
    };
    use std::time::{Duration, Instant};

    struct Tft {
        spi: Spi,
        dc: OutputPin,
        _reset: OutputPin,
        canvas: PanelCanvas,
    }
    impl Tft {
        fn new(c: &PanelConfig) -> Result<Self, Box<dyn std::error::Error>> {
            let gpio = Gpio::new()?;
            let mut reset = gpio.get(c.reset_bcm)?.into_output_high();
            reset.set_low();
            thread::sleep(Duration::from_millis(20));
            reset.set_high();
            thread::sleep(Duration::from_millis(120));
            let mut t = Self {
                spi: Spi::new(Bus::Spi0, SlaveSelect::Ss0, c.spi_hz, Mode::Mode0)?,
                dc: gpio.get(c.dc_bcm)?.into_output_low(),
                _reset: reset,
                canvas: PanelCanvas::default(),
            };
            t.command(0x01, &[])?;
            thread::sleep(Duration::from_millis(120));
            // ILI9341 power, VCOM, RGB565, landscape memory access and sleep-out.
            for (cmd, args) in [
                (0xcf, &[0x00, 0xc1, 0x30][..]),
                (0xed, &[0x64, 0x03, 0x12, 0x81]),
                (0xe8, &[0x85, 0x00, 0x78]),
                (0xcb, &[0x39, 0x2c, 0x00, 0x34, 0x02]),
                (0xf7, &[0x20]),
                (0xea, &[0x00, 0x00]),
                (0xc0, &[0x23]),
                (0xc1, &[0x10]),
                (0xc5, &[0x3e, 0x28]),
                (0xc7, &[0x86]),
                (0x36, &[0x28]),
                (0x3a, &[0x55]),
                (0xb1, &[0x00, 0x18]),
                (0xb6, &[0x08, 0x82, 0x27]),
                (0x11, &[]),
            ] {
                t.command(cmd, args)?;
            }
            thread::sleep(Duration::from_millis(120));
            t.command(0x29, &[])?;
            Ok(t)
        }
        fn command(&mut self, code: u8, args: &[u8]) -> Result<(), rppal::spi::Error> {
            self.dc.set_low();
            self.spi.write(&[code])?;
            if !args.is_empty() {
                self.dc.set_high();
                self.spi.write(args)?;
            }
            Ok(())
        }
        fn flush(&mut self) -> Result<(), rppal::spi::Error> {
            self.command(0x2a, &[0, 0, 1, 63])?;
            self.command(0x2b, &[0, 0, 0, 239])?;
            self.command(0x2c, &[])?;
            self.dc.set_high();
            // SPI per-transfer cap on Pi OS commonly defaults to 4096 bytes.
            for data in self.canvas.pixels.chunks(4096) {
                self.spi.write(data)?;
            }
            Ok(())
        }
        fn render(&mut self, update: &PanelUpdate) -> Result<(), rppal::spi::Error> {
            self.canvas.render(update);
            self.flush()
        }
    }
    pub fn run(
        c: PanelConfig,
        rx: watch::Receiver<PanelUpdate>,
        stop: Arc<AtomicBool>,
    ) -> Result<(), Box<dyn std::error::Error>> {
        // Active buzzer through a transistor: GPIO low is silent; never drive the 5 V buzzer directly.
        let mut buzzer = Gpio::new()?.get(c.buzzer_bcm)?.into_output_low();
        let mut tft = Tft::new(&c)?;
        let mut pulse_seen = rx.borrow().buzzer_sequence;
        let mut off_at: Option<Instant> = None;
        let mut last_draw = Instant::now() - Duration::from_secs(2);
        while !stop.load(Ordering::Relaxed) {
            let update = rx.borrow().clone();
            let fresh = update
                .server
                .as_ref()
                .is_some_and(|s| unix_ms().saturating_sub(s.sampled_at_unix_ms) <= STALE_MS);
            if update.buzzer_sequence != pulse_seen {
                pulse_seen = update.buzzer_sequence;
                if fresh && update.alarm_active {
                    buzzer.set_high();
                    off_at = Some(Instant::now() + Duration::from_millis(180));
                }
            }
            if !fresh || off_at.is_some_and(|at| Instant::now() >= at) {
                buzzer.set_low();
                off_at = None;
            }
            if last_draw.elapsed() >= Duration::from_secs(1) {
                tft.render(&update)?;
                last_draw = Instant::now();
            }
            thread::sleep(Duration::from_millis(25));
        }
        buzzer.set_low();
        Ok(())
    }
}
