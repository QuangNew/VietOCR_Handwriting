# VietOCR

Refactor branch: **`refactor`**. Architecture: **Tauri 2 / Flutter client → Raspberry Pi Rust gateway → Windows C#/Python inference**, with the Next.js admin and Supabase retained.

The [approved plan](docs/REFACTOR_PLAN_2026-11-08.md) and [progress/validation report](docs/REFACTOR_PROGRESS.md) distinguish completed checkpoints from later work. Do not switch a production client merely because the new gateway health check responds.

| Component | Location | Current checkpoint |
| --- | --- | --- |
| Pi gateway, shared webcam, server-status TFT/buzzer | [Gateway](Gateway/README.md) | Rust foundation; Google-session RPC, native MJPEG/snapshot, telemetry/alarm |
| API/state/quota contracts and isolated DB tests | [Contracts](Contracts/openapi-v2.json) | v2 contract and additive 500/day, 30/min reservation migrations |
| C# API, Python workers, Next.js admin | [Server](Server/README.md) | Existing inference kept; new host-load telemetry and 500/30 admin bounds |
| Windows Tauri client | `Desktop/` (later phase) | Replacement has not been implemented in this checkpoint |
| Android Flutter | [Mobile](Mobile/README.md) | Existing client retained until v2 gateway/result flow is ready |
| Pi deployment templates | [infra/raspberry](infra/raspberry/README.md) | ARM64 runtime/service setup; no production install implied |

The USB webcam is on **Raspberry**, shared by authenticated users. Clients see the Pi stream and save captured JPEGs as private drafts; OCR starts only after **Send**. Local-file import/edit/crop/black-and-white/export/history remain required in the replacement clients. No local AI runtime is planned for clients.

Old ESP32 firmware (`pbl4/`) and obsolete build/APK caches have been removed on this branch. Firmware source can be recovered from base commit `e26faae` / its original branch. Python client code is temporarily retained for parity and because the inference server still uses its Python environment. See the progress report before removing that environment.

Development checks:

```sh
cargo test --workspace --locked
dotnet test Server/backend/VietOcr.Server.Tests/VietOcr.Server.Tests.csproj
cd Contracts/tests
npm ci --ignore-scripts --no-audit --no-fund
npm test
```

Runtime secrets stay outside Git. The repository's Google OAuth callbacks and model provenance must be preserved during the remaining stages.
