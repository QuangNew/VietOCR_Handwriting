using System.Diagnostics;
using System.Collections.Concurrent;

namespace VietOcr.Server;

public sealed class Metrics(Coordinator coordinator, Hardware hardware, Store store, ServerOptions options)
{
    private readonly object gate = new();
    private readonly Queue<(DateTime Time, double Ms, int Status)> responses = new();
    private readonly Queue<MetricPoint> points = new();
    private long requests, errors;
    private DateTime lastSnapshot = DateTime.MinValue;
    private object? cached;
    private readonly SemaphoreSlim sampling = new(1, 1);
    public void Response(double ms, int status)
    {
        Interlocked.Increment(ref requests); if (status >= 400) Interlocked.Increment(ref errors);
        lock (gate)
        {
            responses.Enqueue((DateTime.UtcNow, ms, status));
            while (responses.Count > 10000 || responses.TryPeek(out var r) && r.Time < DateTime.UtcNow.AddMinutes(-15)) responses.Dequeue();
        }
    }
    public async Task<object> Snapshot()
    {
        await sampling.WaitAsync();
        try
        {
            if (cached != null && (DateTime.UtcNow-lastSnapshot).TotalSeconds < 2) return cached;
            var now = DateTime.UtcNow;
            var jobs = await store.Window(now.AddMinutes(-15));
            var totals=await store.Totals(now.AddMinutes(-15));
            var done = jobs.Where(j => j.State == "succeeded").ToArray();
            var failed = totals.Failed;
            var durations = done.Where(j => j.TotalMs != null).Select(j => j.TotalMs!.Value).ToArray();
            var views = coordinator.Workers;
            var gpu = hardware.Gpu;
            var ram = Hardware.Ram();
            var required = coordinator.RequiredMiB;
            var recentDone = totals.PerMinute;
            var running = views.Count(w => w.State == "busy");
            double? p50 = Capacity.Percentile(durations, .5), p95 = Capacity.Percentile(durations, .95);
            (DateTime Time, double Ms, int Status)[] http;
            lock (gate) http = responses.Where(r => r.Time >= now.AddMinutes(-15)).ToArray();
            points.Enqueue(new(now, totals.Completed, failed, coordinator.Queued, running, p50, p95, gpu?.UsedMiB));
            while (points.Count > 120) points.Dequeue();
            cached = new {
                timestamp = now, uptimeSeconds = (now-coordinator.StartedAt).TotalSeconds,
                status = !coordinator.Ready ? "unavailable" : views.Any(w => w.State is "idle" or "busy") ? "healthy" : "degraded",
                database = store.Ready && store.Error == null ? "connected" : "unavailable",
                coordinator.Error, model = "ML_s44 · FP32 · V2c 64px", device = options.Device,
                acceptingRequests=options.AcceptingRequests,dispatchPaused=options.DispatchPaused,
                windowMinutes = 15, completed = totals.Completed, failed, cancelled = totals.Cancelled,
                latencySamples=durations.Length,latencySampled=totals.Matched>jobs.Count,
                successRate = totals.Completed + failed > 0 ? (double?)totals.Completed/(totals.Completed+failed)*100 : null,
                queued = coordinator.Queued, running, throughputPerMinute = recentDone,
                p50Ms = p50, p95Ms = p95,
                meanInferenceMs = totals.InferenceMs,
                meanQueueMs = totals.QueueMs,
                http = new { requests = Interlocked.Read(ref requests), errors = Interlocked.Read(ref errors),
                    p95Ms = Capacity.Percentile(http.Select(r => r.Ms), .95), samples = http.Length },
                gpu, gpuError = hardware.Error,
                memory = new { totalMiB = ram.TotalMiB, availableMiB = ram.AvailableMiB,
                    apiMiB = Process.GetCurrentProcess().WorkingSet64/1048576d,
                    workersMiB = views.Sum(w => w.Memory.RamMiB) },
                capacity = new { reserveMiB = options.ReserveVramMiB, planningWorkerMiB = options.WorkerBudgetMiB,
                    theoreticalWorkers = gpu == null ? (int?)null : Math.Max(0,(gpu.TotalMiB-options.ReserveVramMiB)/options.WorkerBudgetMiB),
                    measuredNextWorkerMiB = required,
                    additionalWorkers = gpu == null ? (int?)null : Math.Max(0,Math.Min(
                        (int)((gpu.FreeMiB-options.ReserveVramMiB)/required),
                        (int)((ram.AvailableMiB-options.ReserveRamMiB)/coordinator.RequiredRamMiB))),
                    requiredRamMiB = coordinator.RequiredRamMiB, reserveRamMiB = options.ReserveRamMiB,
                    canAdd = coordinator.Ready && ram.AvailableMiB-coordinator.RequiredRamMiB>=options.ReserveRamMiB,
                    queueCapacity = options.QueueCapacity, inputLimitMiB = options.MaxUploadMiB, maxPixels = options.MaxPixels },
                workers = views, history = points.ToArray()
            };
            lastSnapshot = now; return cached;
        }
        finally { sampling.Release(); }
    }
}
