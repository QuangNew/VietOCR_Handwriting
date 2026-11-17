# Configuration

Primary database/auth: **Supabase PostgreSQL + Google OAuth**. XAMPP/MySqlConnector are no longer runtime dependencies. Schema/RLS/quotas: [SUPABASE.md](SUPABASE.md).

`Server/server.local.json` is ignored by Git, restricted to the Windows account and read only by the C# API. Environment `Server__Property` overrides local config. Use `tools/configure_supabase.py` with the already-linked CLI to populate credentials without printing them.

```json
{
  "Server": {
    "SupabaseUrl": "https://rrdxhztiikizgogxtlhu.supabase.co",
    "SupabasePublishableKey": "sb_publishable_...",
    "SupabaseServiceKey": "PRIVATE_SERVICE_ROLE_KEY",
    "Python": ".venv/Scripts/python.exe",
    "Device": "auto",
    "ConcurrentUploads": 4,
    "AllowInsecureLan": false
  }
}
```

Do not put service-role or Google Client Secret in `Mobile/assets/config/supabase.json`, desktop public config, Next.js public variables or version control. Apps need only the publishable key and their own OAuth session.

The **Cấu hình server** web page is now authoritative for runtime limits: receiving/dispatch flags, queue capacity, pending/account, hard job timeout, retention, RAM/VRAM reserve, worker budget, initial replicas, max upload/pixels/spool and default account quotas. They persist in `ocr_settings` and override bootstrap values when the coordinator starts. Changes apply immediately except initialWorkers (next boot), and maxPixels (newly started model workers). Environment/config remain for executable/device, transport bind, private secrets and upload concurrency. Kestrel has a hard 65 MiB body ceiling; accepted files are configurable up to64 MiB.

There is one durable coordinator lease with heartbeat independent of warm-up. PostgreSQL admission serialises account quota and queue/spool caps. Fair distribution and workers stay in the C# host, with input files in runtime/images. Stats use Supabase aggregates, recent latency samples, measured GPU and host RAM. No Redis/Docker/Postgres server install is required on the PC.

Windows Job Objects terminate Python descendants when the host exits. GPU sampling uses the existing nvidia-smi; process-tree RAM gates worker creation. Initial defaults leave 1GiB RAM and VRAM. Web can reduce reserve only as far as512MiB; this does not bypass live resource checks.

The bootstrap `Device` is the startup worker policy; the admin WorkerSpace picker selects each additional worker independently. CPU needs RAM headroom and does not require NVIDIA/VRAM. Windows integrated GPU uses the optional `onnxruntime-directml` runtime and a matching verified **FP32 ML_s44** encoder/decoder under `models/ML_s44/onnx`; a different checkpoint hash or missing export makes it unavailable. These model files stay server-side. This machine reuses its existing export/runtime; no model/runtime downloads were needed. CPU/iGPU may be slower than CUDA for one image; adding workers primarily increases batch/concurrent capacity and remains RAM-limited.

Transient Supabase heartbeat failures pause admission/dispatch and retry within the confirmed lease window. A session retires by 30 seconds without confirmation, before the 45-second database lease expires. The host then reinitializes, recovers queued inputs, and restores the prior worker devices. It never continues dispatching indefinitely without a confirmed coordinator lease.

`VIETOCR_WEB_BUILD_DIR` optionally selects a dedicated `.next-...` build directory for side-by-side validation. The normal launch remains `.next` and API port5080. Build-time `VIETOCR_API_ORIGIN` must be a loopback C# endpoint.
