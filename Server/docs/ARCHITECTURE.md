# Current architecture — Supabase / server-only clients

- Desktop Python/Tk and Android Flutter clients: Google OAuth PKCE, camera/import/edit/queue UX; HTTPS or explicitly trusted LAN requests to C#; no local inference engine.
- C# ASP.NET host: admin cookies + CSRF, verified Supabase Google sessions or hashed service keys, bounded multipart, atomic Postgres admission, durable jobs and per-account fair queue.
- Supabase PostgreSQL: account identity, quota, jobs/results, settings, audit and single-host coordinator lease. Auth supplies verified Google identities; all app-readable tables have per-account RLS. Privileged RPC is service-role only.
- Persistent Python workers: model/preprocessing only, private NDJSON; serial inference per replica; .NET resource admission, cancellation, watchdog, bounded retry and Windows process containment.
- Dispatch has two fair rotations: per-account FIFO queues, and eligible idle workers. Busy/draining workers are skipped. This avoids a first-dictionary-entry worker taking every isolated request; faster workers can still accept more jobs when slower replicas remain busy. Worker device is per replica (CUDA / optional DirectML / CPU), not a single global runtime for the whole pool.
- Next.js: same-origin admin UI/proxy; live measured data and settings/identity/key/workers/queue controls. Agentation dev-only, no privileged Supabase key in frontend.

The fixed OCR ID is not a forever bearer credential. Account access uses refreshable Supabase sessions. One account's daily and rolling-minute quota is shared across all devices and survives process restarts, key rotation and job retention. Source image temp files remain on the host and are removed after completion. User drafts/photos remain in account-scoped client caches; original images are not uploaded into Supabase Storage.

Completion notifications retain only pending job IDs and signals, not image/result payloads. Bounded long-poll HTTP requests read the durable result after a signal. Admission/idempotency/quotas remain atomic in Postgres; removing the redundant pre-admission lookup does not weaken them. Desktop runs a bounded set of requests, with independent transports, a shared refresh-safe login session and aggregate progress for out-of-order completion. See [PERFORMANCE.md](PERFORMANCE.md).

See [SUPABASE.md](SUPABASE.md), [API.md](API.md), [configuration.md](configuration.md) and [validation](VALIDATION_SUPABASE.md) for current contracts. Older validation reports refer to the prior MySQL/optional-local milestone and do not prove this implementation.

## Historical design notes

# VietOCR Server: implementation contract

This is a self-hosted, single-machine service. ASP.NET Core 10 owns the public API, admin cookie authentication, API-key verification, MySQL persistence, admission control and scheduling. Next.js owns the admin interface. Isolated, persistent Python processes own ML_s44 inference. No model downloads or external AI services are involved.

## Request lifecycle

Client -> authenticated multipart upload -> size/signature validation -> durable image + MySQL job -> fair queue -> ready worker -> result persisted -> client polls by job ID. Only the owning API key or an administrator may read/cancel a job. An idempotency key prevents duplicate submissions after connection loss. Cancellation of running inference terminates that worker, then replaces it. Queue overload returns 429 with Retry-After; database unavailability returns 503. There is no unbounded image queue in RAM.

The scheduler rotates clients, FIFO within each client. Adding workers does not disturb queued jobs. Removing a busy worker drains its current job. Queued/running jobs are recovered on restart; input files remain until completion or cancellation. Terminal images are removed promptly; results expire after a configured retention period. One MySQL advisory lock prevents two coordinators from consuming the same spool.

## Capacity, not checkpoint arithmetic

The user's planning formula is floor((6144 - 1024) / (200 + 100)) = 17. This is an estimate, not an admission limit or throughput claim. FP16 checkpoint storage is not FP32 runtime memory; CUDA contexts, allocator caches, activations, workspace, input width and other applications contribute. Start with one worker. Sample nvidia-smi globally and torch allocator/peak metrics per worker after warm-up at width 2048. Admit a new worker only if fresh GPU free memory exceeds the larger of the planning budget and observed worker requirement plus safety margin, leaving 1024 MiB spare. Serialize starts. Also enforce host-RAM headroom. No fixed application worker count; stop adding when actual hardware cannot fit another. More replicas on one GPU can reduce throughput: benchmark before scaling.

## Live visualization contract

Analytical job: operational monitoring of time series, queue state and resource saturation. Primary family: directly labelled SVG time-series charts plus resource bars and worker/job tables. React owns layout, query state and SVG geometry; no Canvas/WebGL or chart runtime is needed for <= 120 points per series and two simultaneous charts. Snapshot polling every 3 seconds; pause when hidden, retain last-good data with stale/offline labels, no zero-filled invented observations. Tab and time range live in the URL. Essential p50/p95, units, time window, queue counts and VRAM remain visible without hovering. Mobile portrait starts with health and queue metrics; controls follow in tabs, tables scroll without shrinking text. Alerts use text plus colour, focus is visible, reduced motion is supported. Empty metrics are shown as unavailable, not synthetic traffic. JSON metrics can be exported.

## Security and durability boundaries

No public registration. Local CLI creates the administrator with a PBKDF2-SHA256 password hash. HttpOnly SameSite cookies and antiforgery tokens protect admin mutations. API keys are random, hashed in MySQL, revealed once, individually revocable and per-key rate limited. No shared hardcoded mobile secret. TLS is required before using this outside a trusted development LAN; the launcher binds loopback by default. Next.js proxies /api to C# for a single browser origin. MySQL (including XAMPP's MariaDB) is metadata storage; model bytes and temporary images are not database BLOBs. SQL is parameterized. Credentials and images are ignored by Git. Logs exclude API keys, image contents and recognised text.

Scope: one coordinator host, one selected CUDA GPU or CPU. Multi-host/distributed scheduling and exactly-once inference are not claimed. Jobs are at-least-once across a crash; idempotency makes client resubmission safe. GPU workload admission is a safety estimate, not a proof against OOM; failed processes are reaped and jobs have bounded retries/timeouts.
