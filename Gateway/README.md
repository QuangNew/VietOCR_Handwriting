# Raspberry gateway — API v2

Rust/Tokio/Axum service for the Pi 4B 4 GB. See the [approved plan](../docs/REFACTOR_PLAN_2026-11-08.md) and [implementation progress](../docs/REFACTOR_PROGRESS.md).

Implements Google session verification, shared native MJPEG/snapshots, bounded OCR relay, fair upload admission through compute, result tickets, telemetry and optional ILI9341/active-buzzer output. `/api/v2/session` reports `ocrAvailable` only when compute pairing is configured. Functional deployment evidence and remaining Internet/hardware checks are recorded in the progress report.

## Build and configure

```sh
# From the repository, using Rust >=1.94 and a C compiler:
cargo test --workspace --locked
cargo build --release --locked -p vietocr-gateway
cp Gateway/config.example.json Gateway/config.local.json
# Set the project publishable/anon key in the file or VIETOCR_SUPABASE_PUBLISHABLE_KEY.
# Never use the Supabase service-role key on the Pi.
./target/release/vietocr-gateway Gateway/config.local.json --check-config
./target/release/vietocr-gateway Gateway/config.local.json
```

GitHub workflow `Refactor foundation` builds a Linux ARM64 runtime bundle without installing a compiler on the Pi. The bundle has the gateway, SSH-only `camera_probe` diagnostic and example service files. Build dependencies stay on CI. The Windows build is for development; it does not operate Pi GPIO.

Supabase migrations `202611090001`–`004` are applied to the current project; a new deployment must apply and validate them in order before using the login/admission RPCs. They preserve identities, history and used quota, clamp limits to 500/day and 30/rolling minute and retain any lower admin limits. This checkpoint does not run `db push` automatically. Pi holds only the public Supabase key and separate ingress/telemetry machine credentials. Compute holds the database credential and exposes only a fixed adapter to Pi; no arbitrary RPC name or SQL is accepted.

## Native USB camera

The camera is plugged into the **Pi**. Client apps get MJPEG and JPEG snapshots from this service; they do not use their own cameras. Photo import from the client remains part of the client phase.

Run one capture producer per webcam, initially on loopback:

```sh
v4l2-ctl --device=/dev/video0 --list-formats-ext
ustreamer --device=/dev/video0 --host=127.0.0.1 --port=8080 \
  --format=MJPEG --encoder=HW --resolution=1920x1080 --desired-fps=30 \
  --buffers=3 --workers=1 --slowdown
```

Use an actually advertised MJPEG mode, not YUYV followed by a software encoder. Some cameras do not support setting JPEG quality; µStreamer reports that and keeps the hardware encoder default. No JPEG re-encode happens here. µStreamer is a separately installed GPL-3.0 program, not MIT source copied into this repository.

There is one upstream connection per active camera, regardless of viewer count. Each viewer shares the original frame allocation, keeps at most the latest frame and is subject to account/global limits. Current defaults: eight viewers total, two/account, four concurrent snapshots, six snapshots/ten seconds/account. These are safety bounds, **not a promise of eight Full HD streams over Wi-Fi**. The measured camera uses about 260 KB/frame, so 30 FPS already costs roughly 63 Mb/s for each recipient.

The broker supports native UVC zero/FF padding after the JPEG EOI marker. It preserves the exact frame bytes. It also checks µStreamer `/state`; an offline placeholder must not become a new photo. A snapshot waits for a fresh frame after the request and returns original dimensions/SHA-256 in headers. No intent, upload to compute or OCR credit is created by a capture.

Camera URLs are configured loopback origins, not user-supplied fetch targets. Never expose raw port 8080 on the Internet. Gateway routes require a Google bearer header, including the video route; URL tokens are not accepted. The Tauri/Flutter viewers read authenticated binary HTTP streams. A bare HTML `<img src>` cannot add this Authorization header.

```sh
# On the Pi over SSH: diagnostic uses the exact capture broker without opening a public bypass.
./camera_probe http://127.0.0.1:8080 10
```

## Server stats and Pi panel

On the C# server, set `Server:ServerId` and `Server:GatewayTelemetryKeySha256`. The latter is SHA-256 of a random 32-byte-or-longer URL-safe ASCII token. Keep the token itself in a mode-600 file on the Pi. The server exposes `/api/internal/v2/status` only to that credential. Admin cookies, Google JWTs and legacy `voc_` keys do not authorize it. No database queries, OCR data, GPU discovery or model startup happen in this endpoint.

Gateway config example:

```json
{
  "telemetry": {
    "url": "https://ocr.quangnew.tech/api/internal/v2/status",
    "tokenFile": "/etc/vietocr/secrets/telemetry.key"
  },
  "panel": { "enabled": false, "dcBcm": 25, "resetBcm": 24, "buzzerBcm": 18, "spiHz": 16000000 }
}
```

Keep `panel.enabled=false` until wiring/SPI are verified. Example BCM wiring, **not the old ESP32 GPIO map**:

| ILI9341 signal | Pi BCM / physical header |
| --- | --- |
| VCC, LED | 3V3 / pin 1 or 17 |
| GND | GND / pin 6 |
| CS | BCM8 / pin 24 (SPI0 CE0) |
| SDI/MOSI | BCM10 / pin 19 |
| SCK | BCM11 / pin 23 |
| SDO/MISO (optional for this write-only driver) | BCM9 / pin 21 |
| DC | BCM25 / pin 22 |
| RESET | BCM24 / pin 18 |
| Touch T_* | Unused |

The TMB12A05 active buzzer uses an appropriate transistor driver from BCM18 / pin 12, a shared GND and its rated supply. Do not power a 5 V buzzer directly from GPIO. Add a base/gate resistor and default-off pull-down; use flyback protection if required by the buzzer/driver. Do not connect 5 V to a Pi GPIO.

The TFT only shows server online/not-ready/stale, CPU, RAM, busy/idle workers and queue. Polling is every two seconds. Host CPU is sampled via Windows `GetSystemTimes` deltas; RAM is host physical RAM. Worker utilization is busy/(idle+busy), excluding starting/draining/error workers; no workers means unknown, not zero. The buzzer triggers only if **any CPU/RAM/worker metric stays at least 85% for five seconds**: one 180 ms pulse, minimum 60-second cooldown, rearm after all valid metrics are below 80%. Boot, camera, disconnection and stale telemetry do not sound it.

SPI/GPIO run on their own thread. Hardware failure disables that output without terminating the HTTP service. Stale stats clear the live values instead of leaving apparently current numbers on screen.

## Validation

```sh
cargo fmt --all --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
cd Contracts/tests
npm ci --ignore-scripts --no-audit --no-fund
npm test
# Dedicated disposable PostgreSQL *_test DB only:
VIETOCR_TEST_PG_URL=postgresql://postgres:postgres@127.0.0.1:5432/vietocr_refactor_test npm run test:native
```

WASM database tests are isolated and single-connection. Native PostgreSQL tests exercise 32 connections and parallel quota/idempotency races; they run in an ephemeral CI database. Neither substitutes for the phase-7 Internet/1,000-client/soak measurements. Credentials, photo contents and recognized text must not be printed in logs.
