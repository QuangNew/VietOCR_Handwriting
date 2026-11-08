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
- ARM64 CI bundle, ephemeral PostgreSQL race suite and Raspberry systemd templates. CI completion and real gateway-on-Pi measurements are recorded below when available.

## Verification completed locally

- Rust unit/integration tests: initial 23 passed, including signed ES256 claims, multipart chunk boundaries, exact JPEG snapshots, body-held permits, shared single upstream and recovery. Re-run after the padding/online checks is pending at this report's first checkpoint.
- C#: **34 passed**; includes caps, host CPU deltas, separate machine credential and existing queue/worker tests.
- SQL: **15 PostgreSQL/WASM tests passed** against a disposable local database, including migration preservation, provider/session/ban checks, restricted role permissions, 30 active leases, daily caps, midnight accounting, expiry/fencing, mixed v1/v2 quota and cancellation. This runtime serializes one connection; not a race or load claim.
- Next.js admin: TypeScript check passed with updated 500/30 limits.
- Native PostgreSQL race tests are configured for a disposable loopback `*_test` database and CI: 32 connections executing parallel 64/80-call admissions, receipts/idempotency and mixed v1/v2 cases. They refuse a production/Supabase URL.
- No production Supabase migration, domain/tunnel change or client cutover has been performed by this checkpoint.

## Raspberry observations

Authorized SSH, 09/11/2026:

- `rasp4gb`: Raspberry Pi OS / Debian 13.7, **aarch64**, 3,795 MiB reported RAM, initially about 550 MiB used / 3,245 MiB available.
- µStreamer **5.4** and `v4l2-ctl` already installed. Rust/Cargo absent. SPI devices not enabled; no physical TFT/buzzer verification yet.
- USB webcam `/dev/video0` advertises native MJPEG 1920×1080@30 and larger modes. Advertising a mode is not a quality/throughput measurement of that larger mode.
- Started our own loopback-only test µStreamer with `--format=MJPEG --encoder=HW --resolution=1920x1080 --desired-fps=30 --buffers=3 --workers=1 --slowdown` under `/home/admin/vietocr-refactor-test`.
- Python standard-library capture check on Pi: **302 frames / 10.031 s ≈30.01 FPS**, average ~261,133 bytes/frame. This is **local µStreamer**, not the Rust broker or an Internet client. Temperature around 45°C during initial checks.
- No compiler/SDK was installed on Pi for this check. CI is used to prepare the ARM64 binary before testing the actual Rust path.

## Cleanup completed

`tools/Clean-LegacyIoT.ps1 -RemoveFirmwareSources -Apply` removed **1,247 files / 2,717,683,920 logical bytes (~2.531 GiB)** across 182 whitelisted paths:

- `pbl4/`, including 127 tracked firmware-source files and local PlatformIO/build data;
- obsolete OV/ESP32 capture/build/test caches;
- old APK backups in `.toolchain` (not the current mobile dist).

Every recursive target was resolved and verified inside the workspace before deletion. Detailed local manifest: `.toolchain/refactor/legacy-iot-cleanup.json` (ignored). This is file-size accounting, not a claim about exact physical free-space change on the volume. Git history is retained; no force-push/history rewrite.

The server's Python/CUDA environment and original model/user photos/signing data were retained. Legacy IoT client modules are removed when the Tauri/Flutter replacements are ready; the large firmware/cache cleanup did not depend on that UI cutover.

## Downloads / installed locations

- Existing Rust 1.94 / Cargo on Windows reused. Small missing Rust crates go to `C:\Users\QuangNew\.cargo\registry`; initial delta was 6.53 MiB of crate archives. Final delta follows the ARM/TFT checks.
- Isolated test-only PGlite 0.5.15 (~25.1 MiB unpacked) and small `pg` driver/dependencies installed in `Contracts/tests/node_modules`; versions/integrity pinned in package-lock. No Node dependency was added to the production Pi gateway.
- No model, Android SDK, iOS SDK, CUDA wheel or Windows C++ toolchain downloaded.
- Build outputs/cache are ignored; development debug cache is removed after final checks to respect the cleanup request.

## Remaining phases

1. Pass native PostgreSQL concurrency tests and ARM64 compile/probe; deploy verified additive migrations to the target environment when v2 integration is ready.
2. C# internal OCR ingress/resumable spool/receipts, read-only result tickets, and shared hardware-capacity protocol.
3. Wire Rust admission/fair scheduler/streaming OCR relay to restricted DB roles and compute; capacity autoscaling with server admission authority.
4. New Windows Tauri client and Flutter gateway client: Google-only, Pi camera, private drafts, explicit Send, crop/optimization and direct result recovery.
5. Remove legacy IoT client code/dependencies/permissions and old Python client after parity; separate server Python environment before deleting its current parent folder.
6. Named Internet tunnels, cross-network Google session flow, real Pi memory/FD/network/1,000-client load/soak and client release builds.

Checkpoint 1 starts the approved phased implementation; it is not a completed migration of every client or a production-ready end-to-end OCR release.
