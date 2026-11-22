export type Memory = {
  allocatedMiB: number; reservedMiB: number; peakMiB: number; ramMiB: number;
  bartphoLoaded?: boolean; bartphoRamMiB?: number; bartphoRamPercent?: number;
  bartphoVramMiB?: number; bartphoDevice?: string | null;
};
export type Worker = { id: string; state: string; pid: number | null; device: string; jobId: string | null;
  completed: number; createdAt: string; loadMs: number; memory: Memory; error: string | null; draining: boolean; footprintMiB: number };
export type Job = { id: string; clientId: string; clientName: string; layout: string; state: string; imageBytes: number;
  createdAt: string; startedAt: string | null; finishedAt: string | null; workerId: string | null;
  text: string | null; error: string | null; queueMs: number | null; inferenceMs: number | null; totalMs: number | null;
  attempts: number; width: number; height: number };
export type Client = { id: string; name: string; prefix: string; ratePerMinute: number; dailyLimit: number; enabled: boolean; createdAt: string;
  userId: string | null; email: string | null; ocrId: string | null; usedToday: number };
export type Point = { time: string; completed: number; failed: number; queued: number; running: number;
  p50Ms: number | null; p95Ms: number | null; vramMiB: number | null };
export type Snapshot = {
  timestamp: string; uptimeSeconds: number; status: string; database: string; error: string | null;
  acceptingRequests: boolean; dispatchPaused: boolean;
  model: string; device: string; windowMinutes: number; completed: number; failed: number; cancelled: number;
  latencySamples: number; latencySampled: boolean;
  successRate: number | null; queued: number; running: number; throughputPerMinute: number;
  p50Ms: number | null; p95Ms: number | null; meanInferenceMs: number | null; meanQueueMs: number | null;
  http: { requests: number; errors: number; p95Ms: number | null; samples: number };
  gpu: { name: string; totalMiB: number; usedMiB: number; freeMiB: number; utilization: number; temperature: number; sampledAt: string } | null;
  gpuError: string | null;
  memory: { totalMiB: number; availableMiB: number; apiMiB: number; workersMiB: number; bartphoRamMiB?: number; bartphoRamPercent?: number };
  capacity: { reserveMiB: number; planningWorkerMiB: number; theoreticalWorkers: number | null;
    measuredNextWorkerMiB: number; additionalWorkers: number | null; canAdd: boolean; queueCapacity: number;
    inputLimitMiB: number; maxPixels: number; requiredRamMiB: number; reserveRamMiB: number };
  workers: Worker[]; history: Point[];
};

export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}
let csrf: string | null = null;
export async function api<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  if (method !== "GET" && !csrf) {
    const response = await fetch("/api/admin/auth/csrf", { credentials: "same-origin", cache: "no-store" });
    if (!response.ok) throw new ApiError("Không lấy được phiên xác thực.", response.status);
    csrf = (await response.json()).token;
  }
  const response = await fetch(`/api/admin${path}`, {
    method, credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(method === "GET" ? 12000 : 100000),
    headers: { ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(method !== "GET" ? { "X-CSRF-TOKEN": csrf || "" } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    if (response.status === 400 && error.error === "csrf") csrf = null;
    throw new ApiError(error.message || (response.status === 401 ? "Phiên đăng nhập đã hết hạn." :
      response.status === 503 ? "Supabase chưa sẵn sàng. Kiểm tra kết nối server." : `Yêu cầu thất bại (${response.status}).`), response.status);
  }
  if (response.status === 204 || response.headers.get("content-length") === "0") return undefined as T;
  return response.json().catch(() => undefined) as Promise<T>;
}
export function resetSession() { csrf = null; }
export function duration(ms: number | null | undefined): string {
  return ms == null ? "—" : ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${Math.round(ms)} ms`;
}
export function bytes(mib: number | null | undefined): string { return mib == null ? "—" : `${(mib / 1024).toFixed(2)} GB`; }
export function time(value: string) { return new Date(value).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }); }
