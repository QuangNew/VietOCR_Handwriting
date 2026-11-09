# Client API v2 — Raspberry gateway

Current clients connect to `https://api.quangnew.tech`. The Pi validates the
Google access token, current session, ban and shared account quota before
forwarding any OCR image to compute. [OpenAPI v2](../../Contracts/openapi-v2.json)
is the current transport contract; the public tunnels must be deployed first.

1. `GET /api/v2/session` verifies the account and advertises the pinned compute
   results origin. Camera list/stream/snapshot also require a Google session.
2. Capture/import/edit create private client drafts. Explicit Send creates
   `POST /api/v2/intents` with stable request UUID, SHA-256, byte count and layout.
3. `POST /api/v2/intents/{id}/grant` gets a fenced upload generation/offset.
   `PUT .../content` streams at most1MiB per chunk with `Upload-Offset` and
   `X-OCR-Generation`; retry the same intent, not a fresh request ID.
4. `POST .../complete` validates the durable compute receipt and commits quota
   once. An incomplete upload does not consume an image credit.
5. `POST .../result-ticket` issues a short-lived, job/user/session-bound read
   ticket. The client reads `/api/v2/results/{id}` directly on compute; image
   upload and OCR creation remain restricted to the Pi's machine ingress.

Limits: at most **500 accepted images/day** and **30 accepted images/rolling60s**
per Google account, shared across devices; administrators can lower them.
Daily reset is Asia/Ho_Chi_Minh00:00. Idempotent retries do not charge twice.
Clients retain unsent originals and recover accepted jobs without reuploading.
Transient429/503 requires bounded backoff, not unlimited upload concurrency.
Expired retained results return410; the client's local image remains available.

Only public Supabase project configuration is compiled into clients. The user
does not enter a service-role key, Google client secret or Pi machine token.
Desktop connection settings contain only the Raspberry URL. Session credentials
use Windows DPAPI / Android Keystore. Hiding a public key is not the authorization
boundary: the database grants/RLS, session checks and compute ingress enforce it.

## Retired v1 compatibility reference

The endpoints below are disabled by default (`LegacyClientApiEnabled=false`)
and return410. They are not used by the refactor desktop/Android clients and
must not be exposed by the compute tunnel. This section describes legacy SDKs
only. Admin cookie/CSRF and worker administration remain supported.

Base URL is the **C# API** on port 5080, e.g. `https://ocr.example.com` or a trusted LAN address. Next.js port 3000 is the admin interface. Apps authenticate with a Supabase Google access token. A stable public OCR identity identifies the account; it is not an authentication secret. Admin-issued revocable voc_ keys remain available for service integrations. HTTPS is the default requirement outside loopback; `Start-Server -Lan` explicitly allows development HTTP.

```http
POST /api/v1/jobs
Authorization: Bearer <SUPABASE_ACCESS_TOKEN>
Idempotency-Key: <unique printable ASCII key, 1–128 chars>
Content-Type: multipart/form-data; boundary=...

image: <one JPEG, PNG or WEBP file>
layout: auto | line
```

`202 Accepted`, `Location: /api/v1/jobs/{id}`, `Retry-After: 1`:

```json
{"id":"0123456789abcdef0123456789abcdef","state":"queued","layout":"line","text":null,"error":null}
```

The complete response also includes client identity, byte count, timestamps, worker ID, attempts and timings. Use the `id` to associate the result with the original local document. Timings are milliseconds. `queueMs` starts after upload/validation/durable acceptance; `inferenceMs` includes the worker's image decode/preprocessing/model pipeline; `totalMs` includes queue + processing/persistence, **not network upload time**.

- `GET /api/v1/me`: fixed OCR ID, account limits, usedToday, rolling-minute use, reset time and timezone.
- `GET /api/v1/jobs`: owning account cloud history; fetch individual jobs for text.
- `GET /api/v1/status`: authenticated model/queue availability; does not return admin metrics.
- `GET /api/v1/jobs/{id}?wait=2`: the owning client's job. Optional `wait` holds a pending response for at most 10 seconds, waking on completion/cancellation. Ownership is checked before waiting and results are read from Postgres; there is no per-waiter DB polling. States: `queued`, `running`, `succeeded`, `failed`, `cancelled`.
- `DELETE /api/v1/jobs/{id}`: cancel a queued/running job. Killing running native inference replaces the affected worker.
- `GET /api/health/live`: process liveness.
- `GET /api/health/ready`: 200 only when a model worker is ready, otherwise 503.

`succeeded` has `text`, `width`, `height`; `failed` has a safe diagnostic string. Treat failed/cancelled as terminal. Do not retry failed images indefinitely.

| Response | Client action |
|---|---|
| 200 on duplicate upload | Same image/layout/idempotency key: keep the original job ID. |
| 400 / 413 | Invalid fields/file/signature or oversized body: correct the request. Invalid decoded images can also fail asynchronously in the worker. |
| 401 | Session missing or expired; sign in with Google again. Service integrations should check their key. |
| 404 | Job absent or owned by another client; ownership is not disclosed. |
| 409 | Idempotency key reused with a different image/layout. |
| 429 | Queue/per-client/rate limit reached. Honour `Retry-After`. |
| 503 | Database/coordinator unavailable; back off, reuse idempotency key. |
| 426 | HTTPS required; configure TLS or explicitly select trusted LAN dev mode. |

Default: 60 new images/minute/key; separately 600 poll/cancel/status calls/minute/key. Use bounded long polling (`wait=2` in the Python SDK); older clients can poll every 1–3 seconds. SDKs retry ambiguous uploads with the same idempotency key and never follow redirects carrying credentials. Idempotency lasts as long as the retained job record (24 hours default); do not replay old image IDs after retention.

For a single image from Windows:

```powershell
curl.exe -H "Authorization: Bearer $env:VIETOCR_API_KEY" `
  -H "Idempotency-Key: my-image-001" -F "layout=line" `
  -F "image=@VietHandOCR_API_Release/test.jpg" http://127.0.0.1:5080/api/v1/jobs
```

Admin endpoints use an HttpOnly cookie and `X-CSRF-TOKEN`, **not client API keys**. Get `/api/admin/auth/csrf` before login and again after authentication. There is no public admin signup/bootstrap endpoint. Password changes invalidate existing admin sessions. APIs never return database passwords, full client keys or key hashes in list responses.


## Account quotas and administration

Accepted unique submissions consume one daily and one rolling-minute credit in an atomic Supabase PostgreSQL transaction. Maximum 1,000/day and 60/60s per account, shared across devices. Daily reset: Asia/Ho_Chi_Minh 00:00. Failed/cancelled admitted jobs still count; validation/queue rejection and idempotent retries do not. GET polling does not consume OCR credits. `429` includes `Retry-After` and `daily_quota`, `minute_quota` or `queue_full`. `403 account_disabled` means an admin locked the account.

Admin cookie + CSRF endpoints: `GET/PUT /api/admin/settings`, `GET /api/admin/audit`, `PUT /api/admin/clients/{id}`, `POST /api/admin/clients/{id}/rotate`, `POST /api/admin/queue/cancel-pending`. Client edits accept name, ratePerMinute, dailyLimit and enabled; identity remains fixed. Google users never receive admin role automatically. See [SUPABASE.md](SUPABASE.md).

`GET /api/admin/devices` lists detected runtime device IDs, kind, availability and optional reason. `POST /api/admin/workers` accepts `{"device":"auto"}`, `{"device":"cpu"}`, or an available exact ID such as `cuda:0` / `directml:0`. An empty body preserves the automatic default. Explicit device choices never silently switch to another device; automatic creation tries discrete GPU, integrated GPU, then CPU within RAM/VRAM limits. Only supported, detected adapters are advertised. `DELETE /api/admin/workers/{id}` drains a worker without cancelling its current job.
