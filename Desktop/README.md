# VietOCR Desktop v4 — Tauri 2

Windows native Rust client with a bundled HTML/CSS/JavaScript workspace. Camera,
authentication, private files, upload hashing/resume and HTTP are in Rust. There
is no Python/model/BLE dependency. Frontend has no remote scripts or network access.

See the root [DevTodo.md](../DevTodo.md) for deployment, OAuth callbacks and pairing.

- Build: `cd Desktop/src-tauri; cargo build --release` on Windows with Rust MSVC,
  Visual C++ Desktop tools, Windows SDK and WebView2. Run the generated EXE.
- No Node/npm install is needed for the frontend. `node --test Desktop/tests/*.test.mjs`
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
  PNG derivatives. The original is retained. 16MiB upload cap matches server default.

This is the new client source; successful builds, device checks and remaining
deployment dependencies are recorded in `docs/REFACTOR_PROGRESS.md`.
