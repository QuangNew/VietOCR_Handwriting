# Refactor progress

## Tunnel setup repair — 10/11/2026

- Reproduced the user's step7.1 failure on the live Pi: the generated Windows
  YAML used CRLF, so the documented `sed` expression returned a37-byte UUID
  with a hidden trailing CR. The old installer rejected it before creating
  the tunnel service. This was a script/runbook issue, not an invalid tunnel ID.
- Installer now accepts that trailing line-ending CR while validating canonical
  UUID shape, and writes the installed YAML with LF. The generator emits
  UTF-8 without BOM/LF regardless of template checkout endings; Git now pins
  tunnel templates to LF. Runbook strips CR explicitly for existing files.
- Tested the updated installer with the actual old37-byte input on Pi. It
  completed, enabled/started `vietocr-tunnel.service` and registered four edge
  connections. Installed YAML is LF/mode0640, connector credential mode0600.
  Gateway/camera remain active and GPIO stays disabled. No credential rotation.
- The Windows compute connector was not running; restarted the project helper.
  Both public hosts now pass all six routing/TLS/anonymous-denial checks:
  gateway200, protected APIs401, admin/legacy404. No Google/model request or
  quota charge was made in these checks. No model/toolchain downloads.
- Step7.2 remains: Pi still points compute/telemetry at the loopback test
  origin15080; switch to the public compute origin before real Internet OCR.
  Cross-network Google-to-result and physical Android acceptance remain pending.

Branch: [`refactor`](https://github.com/QuangNew/VietOCR_Handwriting/tree/refactor).
The network update above records10/11/2026. The client/release checkpoints below
retain their09/11/2026 evidence; their then-pending DNS state is historical.
Full Google-to-OCR Internet, device and extended-load acceptance remain pending.

## Latest verified artifacts and deployment handbook

- Client checkpoint `f21acdc` passed [Windows/ARM64 release CI42635830142](https://github.com/QuangNew/VietOCR_Handwriting/actions/runs/42635830142).
  Explicit Send now waits through worker warmup and rolling-minute quota without
  changing the intent or uploading twice; daily quota does not auto-retry.
  The earlier native camera baseline `86525e1` passed [CI42628804508](https://github.com/QuangNew/VietOCR_Handwriting/actions/runs/42628804508).
  Backend receipt recovery and deployment-helper checkpoint `21560b7` also passed
  [CI42632605384](https://github.com/QuangNew/VietOCR_Handwriting/actions/runs/42632605384).
- Actual Windows Tauri EXE at `86525e1`, legitimate DPAPI Google session and live Pi webcam
  through encrypted SSH forwarding: new4.0.1 EXE rendered127 frames in5.016s
  (~25.32FPS),1920×1080,no JS errors. Snapshot remained a local draft, did not
  consume OCR quota and camera stayed open after3-second review. Saved mirror
  retained full size, original remained unchecked, optimization577,558→193,610bytes
  took191ms at full2048×230. No public DNS test claimed. Diagnostic CDP9226 and
  test SSH forwarding were closed, test drafts removed, saved gateway restored
  to the production HTTPS origin awaiting DNS.
- Optional image transfer optimization preserves full dimensions and originals.
  Six already compact JPEGs (including the four provided OV photos) were kept
  unchanged. A public sample PNG shrank1,413,860→193,610bytes with JPEG95,
  PSNR56.76dB and identical text through the real CUDA worker. One sample is
  not a CER/WER evaluation; lossy optimization is opt-in, original is default.
- Verified artifacts: EXE13,354,496bytes/SHA256`6c73e7847ee137922e39a2666eafed0e550f58287ee8f038b706848cb46159d5`;
  APK20,637,449bytes/SHA256`47163045301a59c664dc20331111f1b6f2c909edaa106fd9f7f6f4d4223b72a8`.
  Native client/Android binaries correspond to `f21acdc`. Local C#49, Flutter54,
  Rust32, JS4 tests passed; Flutter analyzer clean. SQL17+4 race suites passed in CI.
  Updated Playwright fixture verified three intent attempts through warmup and
  minute-quota responses, with one upload and a stable intent. Automatic approval
  review rejected the final diagnostic EXE launch; no fresh native-camera run on
  this last artifact is claimed. The earlier real-Pi baseline is retained above.
- Windows settings now contain only the Raspberry URL. Supabase public config
  remains compiled in native auth; it is not an application secret. Google
  access/refresh tokens stay in DPAPI/Keystore, not the WebView. Logs redact
  credential-like text before persisting/exporting. Current host secrets were
  absent from tracked files and supplied EXE/APK scans; this is an exact-value
  packaging check, not a historical Git/full security audit. A publishable-key
  only request returned401 on all9 tested live OCR/admin tables.
- Account refresh/network operations are pinned to the creating account;
  Android closes camera/editor on account changes. Explicit image checkboxes
  prevent original+edited duplicates. Mirror applies to the saved capture.
  Desktop uses an OS file lock to prevent simultaneous writers to one workspace.
- Removed80 tracked retired Tk/BLE/ESP32 camera files/tests/tools and the old
  launcher EXE. Git history remains. AI adapter references a model-only module;
  model architecture/weights/V2c preprocessing are retained. Python/CUDA now
  lives at `Server/.venv` and `Server/.python`, no reinstall/download.
- Pi's gateway and native MJPEG capture services remain active. Latest idle
  reading42.3°C,384MiB used,3411MiB available,swap0. GPIO disabled as requested.
  Cloudflare login certificate / active DNS are still pending; no production
  cutover to public HTTPS has been claimed. DevTodo was finalised after the native
  build checks, including the user's requested Cloudflare/DNS/Authorize runbook.
- Added continuous receipt/DB-queued reconciliation: an accepted job with a lost
  acknowledgement is replayed without waiting for a restart or reconnecting the
  client. Recovery skips active workers, preserves idempotent quota and prunes
  expired unaccepted partials without racing a writer. Added two backend tests.
- Client frontend implementation uses static HTML/CSS/JS within Tauri, rather
  than the plan's proposed React/TypeScript bundler. Rust owns credentials,
  networking/files/encoding; no Node server is shipped. Upload authority uses
  TLS plus a separate machine credential and DB-fenced leases, rather than a
  separately signed asymmetric per-job upload token. Result tickets remain
  authenticated/job/session-scoped. These are explicit implementation choices.
- Removed14 old Android maps178,390,646bytes and final generated test/build cache
  4,333,726,745bytes (~4.036GiB), preserving dist artifacts/model/env/signing and
  private user data. The latter cache was generated during verification; do not
  count it as pre-existing IoT weight. Mobile/build was regenerated for the final
  APK and remains. Four private inert ACL-test files also remain in ignored
  `.toolchain/refactor/pairing-smoke`; automatic review blocked their deletion.
  They are not configured credentials and created no database clients.
  Current sanitized validation is linked above.

## Current checkpoint: v2 integration and recovery

- Implemented Rust OCR relay and fixed compute adapter, bounded/resumable 1MiB uploads, durable receipt recovery, exactly-once quota commit, direct job-scoped result tickets, fair active-account admission and hardware-authoritative worker scale requests.
- Implemented Windows Tauri client and Flutter Android v4: Google-only, Pi webcam, private drafts, explicit Send, edits/BW/crop, native exports, history and local diagnostics. JPEG originals are preserved. Source and build-artifact versions must be distinguished below.
- Follow-up fixes: job-result tickets are reused within their short lifetime, so an already issued ticket can read compute during a Pi outage; the ticket is not reused across account changes. Android restores accepted results read-only, including lost acceptance acknowledgements. Rotated upload files persist in the account directory for stable resume. Native results are limited to four reads per client and reconnect after transient failures. Cancelled intents are not falsely acknowledged as accepted; expired results return410 rather than pretending upload is pending.
- Account isolation now also covers queued writes/imports and late network completions. Native image headers are checked before handing input to the webview decoder; actual image dimensions are stored. The old Run-VietOCR.cmd opens the new desktop launcher instead of the retired Python IoT UI.

### Checks recorded

- Rust workspace:28 tests passed before the last header guard; ClientCore then passed5 tests (adds one header-bound test). Final CI reruns the combined workspace and all-target Clippy on ARM64.
- C# backend:47 tests passed. Flutter:45 tests passed; analyzer reported no issues after the recovery changes. Three JS geometry/explicit-send tests and a Playwright UI fixture passed (import by clicking original image, no autosend, stable theme geometry, editor fit and980px layout).
- SQL baseline remains17 isolated PGlite tests and4 native PostgreSQL race tests,32 connections; the new CI run reruns them. No load fixtures are inserted into the production database.
- Windows loopback load fixture:3 rounds ×1000 distinct, locally signed ES256 identities. All1000 metadata intents admitted per round with controlled429/503 retry; p95 approximately3.56–3.74s, a single JWKS fetch, upstream-offline503, ban403 with zero forwarding, and health200 after load. This is **real gateway code with fake local Supabase/compute**, not1000 Google logins, real image ingestion or an Internet benchmark.

### Live database and Pi deployment

- The user explicitly approved the Supabase live migration. Migrations202611090001–004 applied, CLI migration history repaired. Existing1admin/24clients/35jobs and used counters were unchanged at migration time. When compute was subsequently started, its existing24-hour retention policy pruned the expired Nov3 jobs; migration and fake-client cleanup did not delete those jobs.
- Requested fake-client cleanup deleted23 disabled, unlinked test clients with known test prefixes and no jobs/intents. The real Google account and administrator remain. The cleanup SQL is `tools/Clean-FakeClients.sql`.
- Pi runtime installed: `/opt/vietocr/vietocr-gateway`, private `/etc/vietocr/gateway.json` and two separate machine token files. Dedicated `vietocr` service user; `vietocr-gateway.service` and `vietocr-camera@desk.service` enabled/active. Capture stays on loopback8080. Existing SSH/RDP/Tailscale were not changed.
- cloudflared2026.10.7 installed at `/usr/local/bin/cloudflared` on Pi; the Windows binary is `.toolchain/cloudflared/cloudflared-windows-amd64.exe`. Both release SHA-256 values were checked. Downloads were about88.8MiB combined; no additional model/CUDA/C++/Android SDK downloaded for this checkpoint. Existing JDK21, Flutter and Android SDK reused.
- GPIO remains **disabled by the user's explicit instruction**: TFT/buzzer are not wired yet. Logic/renderer tests passed; no physical TFT/buzzer test is claimed. Pi measured about45°C at idle during this checkpoint.
- Compute connection used for the live check was an encrypted temporary SSH reverse-forward on Pi localhost15080. Production must use the named compute HTTPS tunnel, not depend on that test SSH process. The forward is not currently a persistent service.

### Actual Google → Pi → model → direct-result check

A stored legitimate Google session was refreshed and verified against live Supabase; it was not a synthetic identity. Pi returned a hash-checked103680-byte camera JPEG. A public Vietnamese sample then exercised idempotent intent creation, partial upload/offset conflict/resume, no quota before completion, one charge after repeated completion and direct compute result retrieval. The expected Vietnamese title matched exactly; measured GPU inference707.51ms. Total11536.81ms included deliberate extra round-trips for idempotency/quota assertions and is not a normal-user latency baseline. The result URL was validated as `ocr.quangnew.tech`, but DNS was bypassed via local compute for this check; **public Internet end-to-end is still pending**.

### Historical artifacts at checkpoint b840ba5

The first integration CI failed (missing Windows icon and an ARM64 warning); both were fixed. [Run42578375251](https://github.com/QuangNew/VietOCR_Handwriting/actions/runs/42578375251) at `b840ba5` passed both jobs.

| Artifact | Local path | Size | Source |
|---|---|---:|---|
| Windows portable EXE | `Desktop/dist/vietocr-desktop.exe` |12,317,184bytes| CI at `b840ba5` |
| Android ARM64 APK | `Mobile/dist/VietOCR-4.0.0-refactor-arm64.apk` |20,506,501bytes| Local JDK21 build, baseline v4 before recovery follow-up |
| ARM64 tar | `.toolchain/refactor/checkpoint2-arm/vietocr-gateway-linux-arm64.tar.gz` |3,823,734bytes| CI at `b840ba5`, deployed on Pi |

This table records the earlier integration build and is superseded by the latest
artifacts above. The then-current browser check used a test-only native bridge;
the later native Google/Pi-camera check is recorded separately above. APK remains
sideload/debug-signed, with physical Android QA pending.

### Remaining acceptance work

1. Finish named Cloudflare tunnels for `api.quangnew.tech` and `ocr.quangnew.tech`, after domain/Authorize is ready. The latest CLI login expired without a certificate; no DNS record or public endpoint is claimed ready.
2. The1000-identity fixture passed on Pi (see below); longer resource plateau tests, separate upload/slow-client relay and Internet/real-compute measurements remain. A loopback fixture is not production throughput.
3. Windows portable/Android release builds and native desktop interaction checks passed. Physical Android QA remains pending. No installer/Play-distribution signing is claimed; model hashes/preprocessing are unchanged.
4. Retired Python IoT client removal has now completed for80 tracked files (see follow-up below). Finish cleaning generated build artifacts after the new release is verified; user images/signing/sessions/models are retained.
5. DevTodo now documents the verified build/runtime state and remaining manual Cloudflare setup/run/rollback. Hardware GPIO remains off until the user wires it and authorises that later test.

---

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
- Follow-up policy/Google-AMR checkpoint `3ea162c` also passed [CI run 42514420436](https://github.com/QuangNew/VietOCR_Handwriting/actions/runs/42514420436), including all database tests and a fresh ARM64 release build. The capture broker code measured on Pi is unchanged in that follow-up.
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
5. Legacy client source removal and safe server Python-environment relocation completed in the follow-up; generated-cache cleanup follows verified release artifacts.
6. Named Internet tunnels, cross-network Google session flow, real Pi memory/FD/network/1,000-client load/soak and client release builds.

Checkpoint 1 starts the approved phased implementation; it is not a completed migration of every client or a production-ready end-to-end OCR release.


## Follow-up: Pi measurements and client image parity

- [CI42616584875](https://github.com/QuangNew/VietOCR_Handwriting/actions/runs/42616584875) at `187f007` passed both ARM64 and Windows. It fixes the earlier Tauri command macro error (async logging command required a Result return). Source changes below are newer and still require their own release build.
- On real Pi,30 consecutive rounds ×1000 distinct local signed-identity clients completed in90.53s. Every round admitted all1000 metadata intents; round p95 was2.688–2.798s. Combined probe process peakRSS64,932KiB (~63.4MiB), finalRSS54,636KiB, final76FDs. This includes the load generator and fake DB/compute in one process; it does **not** measure image ingestion or real Supabase/Google traffic. Upstream-offline503, ban403/no forwarding and health200 checks passed. Temperature after the short probe53.5°C. First attempt under the SSH shell's1024FD limit failed; reruns used4096, matching the deployed gateway unit's explicit limit. No production clients were created.
- New ARM64 gateway binary from the verified bundle installed atomically and systemd restarted; loopback health200 reports the v2 gateway. Camera capture service and private config/tokens retained.
- Python/CUDA environment relocated within this workspace to `Server/.venv` and interpreter to `Server/.python`. `pyvenv.cfg`/activation scripts updated; the relocated interpreter successfully imported torch2.14.1+cu126, Pillow10.2.0 and OpenCV and detected CUDA. No wheel/model/runtime was downloaded. Server defaults/setup now use `.venv/Scripts/python.exe`. Use `python -m pip`, not old absolute launcher shortcuts.
- Added image inclusion checkboxes in both clients: only checked drafts are sent. Creating crop/BW/optimized versions deselects the source without deleting it. Mirroring now affects saved captures as well as preview; a lossless PNG derivative retains the JPEG original. Tests verify pixel orientation, source retention and selected-image submission.
- Flutter's actual remote engine now uses two bounded request slots, while freezing the explicit-Send batch; newly captured images remain drafts. Test fixtures without the concurrency interface keep one slot.
- Added optional OCR transfer optimization on a background worker/isolate. It never resizes and only uses a candidate smaller by at least1024bytes; compares PNG and high-quality JPEG95, retains the original, and skips ICC-managed images rather than silently changing their colour. Default remains original. All six existing JPEG fixtures (two public samples plus the four user-supplied camera photos) were already smaller than candidates, so their original bytes were kept. This is not a claim of unchanged OCR quality for arbitrary lossy candidates; labelled regression/encode-cost measurements remain before changing the default.
- Removed unused Flutter permission_handler and its platform packages. No BLE/local-camera permission is required for the new client.
- Added reviewed named-tunnel preparation/start scripts and a Pi connector systemd template. They require an actual Cloudflare certificate and do not overwrite conflicting DNS. Tunnel ingress rules and PowerShell syntax validate locally; no named tunnel has been provisioned without the user's Authorize step.


## 2026-11-10 — Stop, collapsible transfers, automatic Send optimization, Pi startup

- Desktop 4.0.2 source: Stop per image / Stop all, including local capacity waits
  and queued batch members. Native watch cancellation drops active upload/result
  futures; per-draft gates prevent late responses overwriting cancellation. A failed
  remote confirmation persists as `cancel_pending`, blocks resubmission, and offers
  retry. Explicit resend after confirmed cancellation creates a new intent. Local
  originals remain. Accepted cancellations do not refund quota; already-finished
  jobs retain their actual result. No Supabase schema change is needed.
- C# v2 cancel now validates current owner/session, serializes against acceptance,
  cancels accepted queued/running jobs, and releases pre-acceptance reservations
  using the current generation, rather than an omitted/default generation0.
- Transfer panel is bounded to viewport and lifted64CSSpx, scrolls internally,
  collapses to a persistent reopen arrow, and stays collapsed through live updates.
  Completed batches auto-collapse after5s.
- Desktop and Flutter source automatically optimize only on explicit Send:
  smaller PNG / JPEG95 derivative, no resize, no overwriting original exports,
  no extra draft in the list, one background encoder at a time, cached immutable
  upload bytes across retry/restart. Existing intents retain their original bytes.
  The editor retains deliberate crop/black-white controls; manual Optimize removed.
- Local validation passed: Rust client11 tests plus Clippy with warnings denied;
  backend56 tests; Flutter analyzer clean and56 tests; JS4 tests and two browser
  fixture flows (workspace and cancellation/layout). Fixtures use local fake
  transports only, create no live Supabase users/keys/jobs, and leave no fake clients.
- Real `rasp4gb`: camera/gateway/tunnel enabled+active, StartLimitIntervalUSec=0,
  Restart=on-failure/5s; active Wi-Fi profile autoconnect=yes; NetworkManager and
  wait-online enabled. Unit syntax verified with systemd-analyze. Updated unit files
  in `/etc/systemd/system/`; small helper staged `/home/admin/vietocr-autostart/`.
  No reboot, Wi-Fi interruption, package installation or GPIO enablement performed.
- Pi now has HTTPS compute/results origin, confirmed without printing tokens.
  Windows compute connector was stopped (Cloudflare1033); restarted via the project
  helper. Subsequent502 identified the Windows backend as stopped, not a Pi
  autostart failure. Do not claim live OCR/Google end-to-end validation here.
- DevTodo now has click-by-click admin launch/login, daily startup after laptop/Pi
  poweroff, exact self-start checks/recovery, shutdown, and transfer-panel behavior.
  Android release was subsequently rebuilt offline as4.0.2+20, see handoff below.
- Verified handoff: [CI42775756851](https://github.com/QuangNew/VietOCR_Handwriting/actions/runs/42775756851)
  at `a20bb66ff89fb37212ca7a22a760fc86010914c7` passed both Windows and ARM64.
  `Desktop/dist/vietocr-desktop.exe` now4.0.2,13,474,816bytes, SHA256
  `ca94d6ab8f749f2025a1c3393699fd3a6b5abb6a9bbaeeb4e35133c1df22a1a2`.
  GitHub zip4,752,802bytes verified against its API digest.
- Android4.0.2+20: `Mobile/dist/VietOCR-4.0.2-refactor-arm64.apk`,20,637,449bytes,
  SHA256 `5e8208070ed55170e0a248b9594c89eac16dfdc36e8cd19a1a1c648702bf3a01`.
  Gradle assembleRelease passed in5m29s using --offline / one worker /768MiB heap,
  existing JDK21/SDK36/build-tools35.0.0/NDK28.2.13676358; no SDK/Maven download.
  aapt confirmed version20, name4.0.2, min26/target36, ARM64 only; apksigner verify
  passed. libapp.so hash differs from4.0.1 (not just a manifest version bump).
  Neither APK contains model weights. Current host-secret scan:770entries,0matches.
  No ADB installation, phone test, new Google session or live OCR job was run.
- Cleanup: generic shell recursive-delete was rejected by automatic review.
  Safer tool-managed cleanup succeeded: Cargo removed3295 generated files (~1.1GiB),
  Rustup removed this turn's interrupted MSVC toolchain (~180MB logical installed
  fragments). Existing stable GNU/MSVC installations retained. Flutter-generated
  outputs are cleaned after copying/verifying APK; dist/model/user caches retained.
  No new compiler/runtime/package installation remains on Pi or Windows.
