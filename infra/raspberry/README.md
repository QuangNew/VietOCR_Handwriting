# Raspberry deployment notes

Verified over authorized SSH on 2026-11-09: `rasp4gb`, Pi 4B 4 GB, **aarch64**, Raspberry Pi OS / Debian 13.7, µStreamer **5.4**, V4L2 webcam `/dev/video0`. Native MJPEG advertises 1920×1080@30 (also larger modes; those have not been quality/throughput-tested). Initial total used RAM ~550 MiB; temperature ~45°C. SPI nodes were not enabled at inspection. No Rust compiler was installed on the Pi during that inspection.

The committed units are **templates**, not an assertion that they were installed/enabled. Obtain the ARM64 runtime bundle from the `refactor` workflow; check SHA-256. Use `/opt/vietocr` for binaries and `/etc/vietocr` for config; create a dedicated `vietocr` service user with the listed groups. `Gateway/README.md` explains public key and telemetry pairing. Keep private files readable only by the service user. Enable SPI only when the TFT wiring is ready; GPIO examples use BCM numbering.

`vietocr-camera@desk.service` reads `camera-desk.env`. Bind capture to loopback; only the authenticated gateway is exposed by a named HTTPS tunnel. Do not change existing remote desktop/SSH/Tailscale services. Verify `systemd-analyze verify` against the target OS before enabling units. Set memory limits after measuring actual gateway + camera + tunnel RSS, not solely the framebuffer size.

Before production: deploy/test additive Supabase migrations, provision restricted gateway/compute DB credentials for the OCR phase, finish machine upload/result-ticket endpoints, then switch clients. A successful `/health/live` or camera probe is not an end-to-end OCR readiness check.
