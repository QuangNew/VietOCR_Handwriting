# VietHandOCR Desktop v4 — Tauri 2

Windows native Rust client with a bundled HTML/CSS/JavaScript workspace. Camera,
authentication, private files, upload hashing/resume and HTTP are in Rust. There
is no Python/model/BLE dependency. Frontend has no remote scripts or network access.
Before sending a batch, users can optionally enable **Nội suy sửa lỗi (BARTpho)**
(saved locally, default off) to run server-side post-OCR correction after `ML_s44`.

See the root [DevTodo.md](../../DevTodo.md) for deployment, OAuth callbacks and pairing.

- Build: `cd apps/desktop/src-tauri; cargo build --release` on Windows with Rust MSVC,
  Visual C++ Desktop tools, Windows SDK and WebView2. Run the generated EXE.
- No Node/npm install is needed for the frontend. `node --test apps/desktop/tests/*.test.mjs`
  tests crop geometry and the explicit-send rule.
- First start: configure the Pi HTTPS origin, sign in with Google in your browser,
  and let Pi validate the session. Supabase public project configuration is bundled;
  no service/signing credentials are present in the app.
- Session tokens: current Windows user DPAPI in app-data. Account directories are
  UUID-separated. Logout locks the previous account's workspace. Never migrate
  Python model files/environments into this client.
- Import/capture/crop/rotate/black-white create local drafts. Send uploads in <=1MiB
  chunks through Pi; results are read from compute with a job-bound five-minute
  ticket. Accepted jobs survive client/Pi disconnection.
- Camera binary IPC has one outstanding frame. Frontend ACK permits the next;
  slow renderers skip frames instead of accumulating native/JS queues.
- JPEG/PNG originals are copied unchanged. Crops and threshold images are lossless
  PNG derivatives. Mirror applies to both preview and the saved capture. Edited
  originals are unchecked while the new derivative is selected; nothing uploads
  before explicit Send. Send automatically caches a smaller same-resolution PNG /
  JPEG95 upload derivative, preserving original exports and stable retry bytes.
- The transfer panel supports per-image Stop and Stop all, including capacity
  waits. Unconfirmed remote cancellation persists across restart and blocks
  resubmission until confirmed. Collapse keeps a reopen arrow visible.
  16MiB upload cap matches server default.
- Connection settings expose only the Raspberry URL. The public Supabase file
  is compiled into Rust, not supplied by the end user. It is a publishable key,
  not a server credential. DPAPI, Google/current-session checks and DB grants/RLS
  protect access; hiding UI text is not the security boundary.
- `tools/check_client_secrets.py` checks current host-secret values against tracked
  files / EXE / unpacked APK without printing them. `tools/check_public_access.py`
  makes read-only anonymous table probes. These are scoped checks, not a full
  security assessment. CI also rejects non-publishable client configuration.

This is the new client source; successful builds, device checks and remaining
deployment dependencies are recorded in `docs/REFACTOR_PROGRESS.md`.
