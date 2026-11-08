using System.Security.Cryptography;
using System.Text;

namespace VietOcr.Server;

public sealed class ServerOptions
{
    public string SupabaseUrl { get; set; } = "https://rrdxhztiikizgogxtlhu.supabase.co";
    public string SupabasePublishableKey { get; set; } = "";
    public string SupabaseServiceKey { get; set; } = "";
    // Only the hash is configured on the server; the Pi keeps the random machine credential.
    public string GatewayTelemetryKeySha256 { get; set; } = "";
    public string ServerId { get; set; } = "compute-1";
    public bool AcceptingRequests { get; set; } = true;
    public bool DispatchPaused { get; set; }
    public string Python { get; set; } = "../VietHandOCR_API_Release/.venv/Scripts/python.exe";
    public string Device { get; set; } = "auto";
    public int InitialWorkers { get; set; } = 1;
    public int ReserveVramMiB { get; set; } = 1024;
    public int WorkerBudgetMiB { get; set; } = 300;
    public int ReserveRamMiB { get; set; } = 1024;
    public int MaxUploadMiB { get; set; } = 16;
    public int ConcurrentUploads { get; set; } = 4;
    public long MaxPixels { get; set; } = 16_000_000;
    public int QueueCapacity { get; set; } = 1000;
    public long SpoolMiB { get; set; } = 1024;
    public int PerClientPending { get; set; } = 100;
    public int JobTimeoutSeconds { get; set; } = 120;
    public int RetentionHours { get; set; } = 24;
    public bool AllowInsecureLan { get; set; }
    public string Root { get; set; } = "";
    public string Runtime => Path.Combine(Root, "runtime");
    public string ImagePath(string id) => Path.Combine(Runtime, "images", id + ".image");
    public static string FindRoot()
    {
        for (var p = new DirectoryInfo(Directory.GetCurrentDirectory()); p != null; p = p.Parent)
        {
            if (File.Exists(Path.Combine(p.FullName, "worker", "main.py"))) return p.FullName;
            if (File.Exists(Path.Combine(p.FullName, "Server", "worker", "main.py"))) return Path.Combine(p.FullName, "Server");
        }
        throw new InvalidOperationException("Run from the repository or Server directory.");
    }
}

public sealed record AdminUser(string Id, string Username, string PasswordHash);
public sealed record ApiClient(string Id, string Name, string Prefix, int RatePerMinute, bool Enabled, DateTime CreatedAt,
    int DailyLimit=AccountPolicy.DailyImageCap,string? UserId=null,string? Email=null,string? OcrId=null,int UsedToday=0);
public sealed record NewClient(string Name, int RatePerMinute = AccountPolicy.MinuteRequestCap,int DailyLimit=AccountPolicy.DailyImageCap);
public sealed record UpdateClient(string Name,int RatePerMinute,int DailyLimit,bool Enabled);
public sealed record NewWorker(string Device="auto");
public sealed record WorkerDevice(string Id,string Name,string Kind,bool Available=true,string? Reason=null);
public sealed record LoginRequest(string Username, string Password);
public sealed record ChangePasswordRequest(string CurrentPassword,string NewPassword);
public sealed record Job(
    string Id, string ClientId, string ClientName, string? IdempotencyKey, string ImageHash,
    string Layout, string State, long ImageBytes, DateTime CreatedAt,
    DateTime? StartedAt = null, DateTime? FinishedAt = null, string? WorkerId = null,
    string? Text = null, string? Error = null, double? QueueMs = null, double? InferenceMs = null,
    double? TotalMs = null, int Attempts = 0, int Width = 0, int Height = 0);
public sealed record WorkerMetrics(double AllocatedMiB = 0, double ReservedMiB = 0,
    double PeakMiB = 0, double RamMiB = 0, double DeviceUsedMiB = 0);
public sealed record WorkerView(string Id, string State, int? Pid, string Device, string? JobId,
    long Completed, DateTime CreatedAt, double LoadMs, WorkerMetrics Memory, string? Error, bool Draining, double FootprintMiB = 0);
public sealed record GpuSnapshot(string Name, int TotalMiB, int UsedMiB, int FreeMiB, int Utilization,
    int Temperature, DateTime SampledAt);
public sealed record MetricPoint(DateTime Time, int Completed, int Failed, int Queued, int Running,
    double? P50Ms, double? P95Ms, int? VramMiB);

public static class Secrets
{
    public static string Token() => Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(32));
    public static string Hash(string value) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(value)));
    public static string PasswordHash(string password)
    {
        if (password.Length < 12) throw new ArgumentException("Password must contain at least 12 characters.");
        var salt = RandomNumberGenerator.GetBytes(16);
        var hash = Rfc2898DeriveBytes.Pbkdf2(password, salt, 600_000, HashAlgorithmName.SHA256, 32);
        return $"pbkdf2-sha256:600000:{Convert.ToBase64String(salt)}:{Convert.ToBase64String(hash)}";
    }
    public static bool VerifyPassword(string password, string encoded)
    {
        try
        {
            var parts = encoded.Split(':');
            if (parts.Length != 4 || parts[0] != "pbkdf2-sha256") return false;
            var actual = Rfc2898DeriveBytes.Pbkdf2(password, Convert.FromBase64String(parts[2]),
                int.Parse(parts[1]), HashAlgorithmName.SHA256, 32);
            return CryptographicOperations.FixedTimeEquals(actual, Convert.FromBase64String(parts[3]));
        }
        catch (Exception e) when(e is FormatException or ArgumentException or OverflowException) { return false; }
    }
}

// A round-robin per-client FIFO: a batch cannot monopolise the ready workers.
public sealed class FairQueue
{
    private readonly Dictionary<string, Queue<Job>> clients = [];
    private readonly Queue<string> rotation = [];
    private readonly HashSet<string> ids = [];
    private readonly object gate = new();
    public int Count { get { lock (gate) return ids.Count; } }
    public bool Add(Job job)
    {
        lock (gate)
        {
            if (!ids.Add(job.Id)) return false;
            if (!clients.TryGetValue(job.ClientId, out var queue))
            {
                queue = new Queue<Job>(); clients.Add(job.ClientId, queue); rotation.Enqueue(job.ClientId);
            }
            queue.Enqueue(job); return true;
        }
    }
    public Job? Take()
    {
        lock (gate)
        {
            while (rotation.TryDequeue(out var key))
            {
                var queue = clients[key]; var job = queue.Dequeue();
                if (queue.Count > 0) rotation.Enqueue(key); else clients.Remove(key);
                if (ids.Remove(job.Id)) return job;
            }
            return null;
        }
    }
    public void Remove(string id) { lock (gate) ids.Remove(id); }
    public void Clear() { lock (gate) { clients.Clear(); rotation.Clear(); ids.Clear(); } }
}

public static class Capacity
{
    public static double RequiredMiB(int budget, IEnumerable<WorkerView> workers) =>
        Math.Max(budget, workers.Select(w => Math.Max(w.Memory.ReservedMiB, w.Memory.PeakMiB) + 256)
            .DefaultIfEmpty(768).Max() * 1.2);
    public static bool CanAdd(GpuSnapshot? gpu, int reserve, double required) =>
        gpu != null && (DateTime.UtcNow - gpu.SampledAt).TotalSeconds < 10 && gpu.FreeMiB - required >= reserve;
    public static double? Percentile(IEnumerable<double> values, double percentile)
    {
        var sorted = values.Order().ToArray();
        if (sorted.Length == 0) return null;
        return sorted[Math.Clamp((int)Math.Ceiling(percentile * sorted.Length) - 1, 0, sorted.Length - 1)];
    }
}
