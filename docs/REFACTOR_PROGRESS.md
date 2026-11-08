# Refactor progress — 09/11/2026

Branch: [`refactor`](https://github.com/QuangNew/VietOCR_Handwriting/tree/refactor). Base: `e26faae`; approved-plan checkpoint: `06f5f3d`. The user approved implementation and subsequently authorized SSH to `admin@rasp4gb`. Credentials are not recorded in this report.

## Implemented in checkpoint 1

- Updated the [approved plan](REFACTOR_PLAN_2026-11-08.md): webcam on Pi, multiple accounts viewing/capturing, ILI9341 server-status display and TMB12A05 load alarm. Windows Tauri 2, Flutter Android, C#/Python/Next.js, Supabase and 500/day + 30/minute-or-lower policy remain.
- Rust workspace, transport-neutral state/policy/image/stat contracts, [OpenAPI v2](../Contracts/openapi-v2.json). Planned operations are explicitly marked, not presented as working endpoints.
- Runnable Rust gateway foundation: ES256/JWKS validation, Google/current-session/ban RPC using the user's JWT and only a public project key. Video/session/status routes fail closed without authentication; no URL tokens or permanent client API keys.
- One native MJPEG producer per active webcam, shared latest-frame buffers, bounded viewers/snapshots, fresh-frame capture, exact compressed JPEG bytes and dimensions/hash. Idle broker drops upstream demand; client capture does not create OCR. µStreamer `/state` prevents offline placeholders becoming photos.
- UVC compatibility fix discovered on real hardware: the webcam appends approximately 3.5 KB of padding after JPEG EOI. The parser accepts legitimate zero/FF padding without re-encoding or rejecting every frame.
- C# host statistics every two seconds, with a separate machine credential for `/api/internal/v2/status`. Host CPU uses system time deltas, RAM is physical host RAM, worker utilization excludes loading/draining/error slots.
- Pi framebuffer plus optional isolated SPI/GPIO thread. Alarm policy: CPU OR RAM OR busy-worker percentage >=85% for five seconds; one 180 ms pulse, cooldown 60s, rearm below 80%; no boot/network/camera/stale alarm. Physical GPIO/SPI output is disabled until wiring is verified.
- Additive SQL migrations for capped policy, current Google session verification and v2 intent/reservation/commit/release. Existing identities/history/usage retained, lower limits retained, idempotent credits and fenced generations; transitional v1 admissions also count v2 holds.
- Restricted database procedures/roles: gateway cannot commit; compute cannot reserve; anon/ordinary authenticated users cannot mutate v2 jobs/limits.
- ARM64 CI bundle, ephemeral PostgreSQL race suite and Raspberry systemd templates. [CI run 42511537290](https://github.com/QuangNew/VietOCR_Handwriting/actions/runs/42511537290) passed build, tests, format and Clippy on Linux ARM64.
- New C# coordinator readiness checks the migrated 500/30 database policy once on initialization; it cannot silently accept the old 1000/60 database policy while reporting new caps. Database rollout/recovery is documented in [REFACTOR_DB_ROLLOUT.md](REFACTOR_DB_ROLLOUT.md).

## Verification completed locally

- Rust unit/integration tests: **24 passed** on Windows and Linux ARM64, including signed ES256 claims, multipart chunk boundaries/UVC padding, exact JPEG snapshots, body-held permits, shared single upstream and recovery. Rustfmt and Clippy with warnings denied passed.
- C#: **36 passed**; includes caps/policy readiness, host CPU deltas, separate machine credential and existing queue/worker tests.
- SQL: **15 PostgreSQL/WASM tests passed** against a disposable local database, including migration preservation, provider/session/ban checks, restricted role permissions, 30 active leases, daily caps, midnight accounting, expiry/fencing, mixed v1/v2 quota and cancellation. This runtime serializes one connection; not a race or load claim.
- Next.js admin: TypeScript check passed with updated 500/30 limits.
- Native PostgreSQL race tests: **4 passed** on ephemeral PostgreSQL17.11/ARM64 in CI, using 32 connections for parallel 64/80-call admissions, concurrent receipts/idempotency and mixed v1/v2 cases. They refuse a production/Supabase URL. No test was skipped on CI; the native suite intentionally skips locally when no disposable PostgreSQL URL is configured.
- No production Supabase migration, domain/tunnel change or client cutover has been performed by this checkpoint.

## Raspberry observations

Authorized SSH, 09/11/2026:

- `rasp4gb`: Raspberry Pi OS / Debian 13.7, **aarch64**, 3,795 MiB reported RAM, initially about 550 MiB used / 3,245 MiB available.
- µStreamer **5.4** and `v4l2-ctl` already installed. Rust/Cargo absent. SPI devices not enabled; no physical TFT/buzzer verification yet.
- USB webcam `/dev/video0` advertises native MJPEG 1920×1080@30 and larger modes. Advertising a mode is not a quality/throughput measurement of that larger mode.
- Started our own loopback-only test µStreamer with `--format=MJPEG --encoder=HW --resolution=1920x1080 --desired-fps=30 --buffers=3 --workers=1 --slowdown` under `/home/admin/vietocr-refactor-test`.
- Python standard-library capture check on Pi: **302 frames / 10.031 s ≈30.01 FPS**, average ~261,133 bytes/frame. This is **local µStreamer**, not the Rust broker or an Internet client. Temperature around 45°C during initial checks.
- ARM64 runtime bundle from CI verified against the GitHub artifact digest and tar SHA-256, transferred to `/home/admin/vietocr-refactor-checkpoint1`. Tar: **3,742,926 bytes**, SHA-256 `f81586d894d287d4dd64ccb8d404269c18366a6c6a011324b88d89adf5f8d893`.
- Actual Rust broker on Pi: **301 frames / 10.01197 s =29.964 FPS**, **1920×1080**, original compressed JPEG (~265KB), first frame ~20.8ms with the source already warm. Repeat: 300 /10.02983s =29.881FPS; peak RSS **11,164KiB**, about **5.57% of one CPU core** for the broker probe. This measures capture/broker locally, not HTTP fan-out to multiple users or Internet delivery.
- Gateway itself started on loopback `127.0.0.1:5082`; `/health/live` returned200, unauthenticated `/api/v2/cameras` returned401. Idle RSS about4,732KiB. No Google-login or OCR end-to-end claim from that smoke test.
- No Rust compiler/SDK installed on Pi; only small binaries/config/test logs in the user-owned test directory. No systemd unit enabled, SPI/boot setting changed, or existing SSH/RDP/Tailscale service altered. Our own gateway/capture test processes were stopped with verified PID/command and SIGTERM after the checks; temperature stayed around45–48°C in these short tests.

## Cleanup completed

`tools/Clean-LegacyIoT.ps1 -RemoveFirmwareSources -Apply` removed **1,247 files / 2,717,683,920 logical bytes (~2.531 GiB)** across 182 whitelisted paths:

- `pbl4/`, including 127 tracked firmware-source files and local PlatformIO/build data;
- obsolete OV/ESP32 capture/build/test caches;
- old APK backups in `.toolchain` (not the current mobile dist).

Every recursive target was resolved and verified inside the workspace before deletion. Detailed local manifest: `.toolchain/refactor/legacy-iot-cleanup.json` (ignored). This is file-size accounting, not a claim about exact physical free-space change on the volume. Git history is retained; no force-push/history rewrite.

The server's Python/CUDA environment and original model/user photos/signing data were retained. Legacy IoT client modules are removed when the Tauri/Flutter replacements are ready; the large firmware/cache cleanup did not depend on that UI cutover.

Also removed generated old Android intermediates (`Mobile/build`, ~405.5MiB) and the **new** Rust debug/test build cache (~1,583.9MiB) after verification. The latter was created during this turn, so it is not counted as pre-existing project space reclaimed. Pre-existing files removed total roughly **2.93GiB**; total logical deletion including temporary Rust build products is about4.47GiB. Current Android dist, AI environments/models, SDK/JDK, Cargo source cache and small ARM64 test bundle remain. Generated-build manifest: `.toolchain/refactor/generated-build-cleanup.json`.

## Downloads / installed locations

- Existing Rust 1.94 / Cargo on Windows reused. Missing Rust crates go to `C:\Users\QuangNew\.cargo\registry`; final delta **93 archives /15.16MiB** including Linux/TFT/platform crates. This is archive-size accounting, not a measurement of all HTTP index/registry traffic.
- Isolated test-only PGlite 0.5.15 (~25.1 MiB unpacked) and small `pg` driver/dependencies installed in `Contracts/tests/node_modules`; versions/integrity pinned in package-lock. No Node dependency was added to the production Pi gateway.
- ARM64 CI zip downloaded: **3,739,341 bytes**; extracted tar copied to Pi over SSH. No model, Android SDK, iOS SDK, CUDA wheel or Windows C++ toolchain downloaded. Compiler/large CI dependencies were installed on the GitHub runner, not on this laptop/Pi Internet connection.
- Build outputs/cache are ignored; development debug cache is removed after final checks to respect the cleanup request.

## Remaining phases

1. Native PostgreSQL concurrency and ARM64 compile/probe have passed; deploy verified additive migrations to the target environment when v2 integration is ready, following the rollout/recovery runbook.
2. C# internal OCR ingress/resumable spool/receipts, read-only result tickets, and shared hardware-capacity protocol.
3. Wire Rust admission/fair scheduler/streaming OCR relay to restricted DB roles and compute; capacity autoscaling with server admission authority.
4. New Windows Tauri client and Flutter gateway client: Google-only, Pi camera, private drafts, explicit Send, crop/optimization and direct result recovery.
5. Remove legacy IoT client code/dependencies/permissions and old Python client after parity; separate server Python environment before deleting its current parent folder.
6. Named Internet tunnels, cross-network Google session flow, real Pi memory/FD/network/1,000-client load/soak and client release builds.

Checkpoint 1 starts the approved phased implementation; it is not a completed migration of every client or a production-ready end-to-end OCR release.
