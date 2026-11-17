using System.Diagnostics;
using System.Text.Json;

namespace VietOcr.Server;

public sealed class ModelWorker(ServerOptions options, ILogger logger,string? device=null) : IAsyncDisposable
{
    public string Device {get;}=device??options.Device;
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private Process? process;
    private WindowsJob? containment;
    private int? actualPid;
    private Task? stderrTask;
    private readonly CancellationTokenSource lifetime = new();
    private readonly System.Collections.Concurrent.ConcurrentQueue<string> diagnostics=new();
    public string Id { get; } = "w-" + Guid.NewGuid().ToString("N")[..8];
    public string State { get; set; } = "starting";
    public string? JobId { get; set; }
    public bool Draining { get; set; }
    public string? Error { get; set; }
    public double LoadMs { get; private set; }
    public double FootprintMiB { get; set; }
    public WorkerMetrics Memory { get; private set; } = new();
    public long Completed { get; private set; }
    public DateTime CreatedAt { get; } = DateTime.UtcNow;
    public CancellationTokenSource? JobCancellation { get; set; }
    public WorkerView View {
        get {
            var memory=Memory;int? pid=null;
            try { if(process is { HasExited:false }){process.Refresh();pid=actualPid??process.Id;memory=memory with{RamMiB=containment?.WorkingSetMiB() ?? process.WorkingSet64/1048576d};} }
            catch(InvalidOperationException) { }
            return new(Id,State,pid,Device,JobId,Completed,CreatedAt,LoadMs,memory,Error,Draining,FootprintMiB);
        }
    }

    public async Task Start(CancellationToken ct)
    {
        var python = Path.GetFullPath(options.Python, options.Root);
        if (!File.Exists(python)) throw new IOException("Python environment missing; run Server/tools/Setup-Server.ps1.");
        process = new Process { StartInfo = new(python) { UseShellExecute = false,
            CreateNoWindow = true, RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
            StandardInputEncoding=new System.Text.UTF8Encoding(false),StandardOutputEncoding=new System.Text.UTF8Encoding(false),
            StandardErrorEncoding=new System.Text.UTF8Encoding(false),
            WorkingDirectory = options.Root } };
        foreach (var arg in new[] { "-X", "utf8", "-u", Path.Combine(options.Root, "worker/main.py"),
            "--model", Path.Combine(options.Root, "models/ML_s44"), "--device", Device,
            "--spool", Path.Combine(options.Runtime, "images"), "--max-pixels", options.MaxPixels.ToString(),
            "--parent-pid",Environment.ProcessId.ToString() })
            process.StartInfo.ArgumentList.Add(arg);
        process.StartInfo.Environment["PYTHONUTF8"] = "1";
        process.StartInfo.Environment["OMP_NUM_THREADS"] = "2";
        process.StartInfo.Environment["MKL_NUM_THREADS"] = "2";
        process.Start();
        if(OperatingSystem.IsWindows())containment=new WindowsJob(process);
        var child=process;
        stderrTask = Task.Run(async () => {
            while (await child.StandardError.ReadLineAsync(lifetime.Token) is { } line) {
                diagnostics.Enqueue(line.Length>500?line[..500]:line);
                while(diagnostics.Count>24)diagnostics.TryDequeue(out _);
                logger.LogDebug("Worker {Worker}: {Diagnostic}", Id, line);
            }
        }, lifetime.Token);
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(ct);
        deadline.CancelAfter(TimeSpan.FromSeconds(90));
        var ready = await Read(deadline.Token);
        if (ready.GetProperty("type").GetString() != "ready") {
            var error=ready.TryGetProperty("error",out var detail)?detail.GetString():"Invalid ready message";
            logger.LogWarning("Worker {Worker} init failed: {Error}. {Diagnostic}",Id,error,string.Join("\n",diagnostics));
            throw new IOException("Model initialization failed; see runtime/logs.");
        }
        actualPid=ready.GetProperty("pid").GetInt32();
        containment?.Include(actualPid.Value); // The Windows venv launcher may have spawned the real interpreter before assignment.
        LoadMs = ready.GetProperty("loadMs").GetDouble(); UpdateMemory(ready);
    }
    private void UpdateMemory(JsonElement value)
    {
        if (value.TryGetProperty("memory", out var m)) Memory = m.Deserialize<WorkerMetrics>(Json) ?? Memory;
    }
    private async Task<JsonElement> Read(CancellationToken ct)
    {
        var line = await process!.StandardOutput.ReadLineAsync(ct);
        if (line == null) {
            logger.LogWarning("Worker {Worker} pipe closed. {Diagnostic}",Id,string.Join("\n",diagnostics));
            throw new IOException("Model process exited unexpectedly.");
        }
        if (line.Length > 2_000_000) throw new IOException("Invalid worker response size.");
        using var document = JsonDocument.Parse(line); return document.RootElement.Clone();
    }
    public async Task<JsonElement> Recognize(Job job, CancellationToken ct)
    {
        await process!.StandardInput.WriteLineAsync(JsonSerializer.Serialize(new {
            action = "recognize", id = job.Id, path = options.ImagePath(job.Id), layout = job.Layout }));
        await process.StandardInput.FlushAsync(ct);
        while (true)
        {
            var response = await Read(ct);
            if (response.TryGetProperty("id", out var id) && id.GetString() != job.Id) throw new IOException("Worker job mismatch.");
            var type = response.GetProperty("type").GetString();
            if (type == "progress") continue;
            UpdateMemory(response);
            if (type == "fatal") {
                logger.LogWarning("Worker {Worker} execution failed. {Diagnostic}",Id,string.Join("\n",diagnostics));
                throw new IOException("Worker execution failed; process will be replaced.");
            }
            if (type != "result") throw new IOException("Invalid worker protocol.");
            Completed++; return response;
        }
    }
    public async ValueTask DisposeAsync()
    {
        State = "stopped";
        JobCancellation?.Cancel();
        lifetime.Cancel();
        if (process != null)
        {
            try { if (!process.HasExited) process.Kill(true); await process.WaitForExitAsync(); }
            catch (InvalidOperationException) { }
        }
        containment?.Dispose();containment=null;
        if (stderrTask != null) { try { await stderrTask; } catch (OperationCanceledException) { } }
        process?.Dispose();process=null;
    }
}
