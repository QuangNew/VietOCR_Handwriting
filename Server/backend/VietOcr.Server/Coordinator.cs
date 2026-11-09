using System.Collections.Concurrent;
using System.Text.Json;

namespace VietOcr.Server;

public sealed class Coordinator(Store store, ServerOptions options, Hardware hardware,
    ILogger<Coordinator> logger,V2Spool spool) : BackgroundService
{
    private readonly FairQueue queue = new();
    private readonly WorkerRotation rotation=new();
    private readonly JobSignals signals=new();
    private readonly ConcurrentDictionary<string, ModelWorker> workers = new();
    private readonly ConcurrentDictionary<string, Task> work = new();
    private readonly SemaphoreSlim scaleLock = new(1, 1);
    private readonly SemaphoreSlim targetLock = new(1,1);
    public SemaphoreSlim Admission { get; } = new(1, 1);
    public SemaphoreSlim Uploads { get; } = new(options.ConcurrentUploads,options.ConcurrentUploads);
    private readonly CancellationTokenSource shutdown = new();
    private readonly object workerGate = new();
    private string[]? recoveryDevices;
    public DateTime StartedAt { get; } = DateTime.UtcNow;
    public bool Ready { get; private set; }
    public string? Error { get; private set; }
    public IReadOnlyList<WorkerView> Workers => workers.Values.Select(x => x.View).OrderBy(x => x.CreatedAt).ToArray();
    public int Queued => queue.Count;
    public void Enqueue(Job job) { signals.Register(job.Id);queue.Add(job); }
    public Task WaitForResult(string id,int seconds,CancellationToken ct)=>signals.Wait(id,TimeSpan.FromSeconds(Math.Clamp(seconds,0,10)),ct);
    public double RequiredMiB => Math.Max(Capacity.RequiredMiB(options.WorkerBudgetMiB, Workers),
        workers.Values.Select(w => Math.Max(w.FootprintMiB, w.Memory.PeakMiB + 256) * 1.2).DefaultIfEmpty(768).Max());
    public double RequiredRamMiB => Math.Max(800, Workers.Select(x => x.Memory.RamMiB * 1.2).DefaultIfEmpty(1000).Max());
    public async Task EnsureWorkers(int desired,CancellationToken ct)
    {
        await targetLock.WaitAsync(ct);
        try{if(Workers.Count(w=>!w.Draining)<desired)await AddWorker(ct,"auto");}
        finally{targetLock.Release();}
    }

    public async Task<WorkerView> AddWorker(CancellationToken ct = default,string? policy=null)
    {
        await scaleLock.WaitAsync(ct);
        try {
            if(!Ready)throw new InvalidOperationException("Supabase/coordinator not ready.");
            var available=await hardware.Devices(ct);
            var requested=policy??options.Device;
            var candidates=WorkerDevicePolicy.Candidates(available,requested);
            if(candidates.Length==0)throw new ArgumentException("Thiết bị không khả dụng. Chọn thiết bị có trong danh sách hoặc Tự động.");
            Exception? last=null;
            foreach(var device in candidates){
                ct.ThrowIfCancellationRequested();
                if(!Ready)throw new InvalidOperationException("Coordinator đang khôi phục kết nối; chưa thể thêm worker.");
                try{return await StartWorker(device.Id,ct);}
                catch(Exception e) when(requested=="auto" && e is not OperationCanceledException){
                    last=e;logger.LogWarning("Worker candidate {Device} unavailable ({Type}); trying next device",device.Id,e.GetType().Name);
                }
            }
            throw new InvalidOperationException("Không khởi tạo được worker trên GPU/CPU: "+last?.Message);
        }finally{scaleLock.Release();}
    }
    private async Task<WorkerView> StartWorker(string device,CancellationToken ct)
    {
        ModelWorker? worker=null;
        try{
            if(Hardware.Ram().AvailableMiB-RequiredRamMiB<options.ReserveRamMiB)
                throw new InvalidOperationException("Không đủ RAM dự phòng để thêm worker.");
            GpuSnapshot? before=null;
            if(device.StartsWith("cuda")){
                before=await hardware.Sample(ct);
                if(!Capacity.CanAdd(before,options.ReserveVramMiB,RequiredMiB))
                    throw new InvalidOperationException($"Không đủ VRAM: cần thêm ~{RequiredMiB:F0} MiB và chừa {options.ReserveVramMiB} MiB.");
            }
            worker=new(options,logger,device);workers[worker.Id]=worker;
            await worker.Start(ct);
            if(before!=null){
                var after=await hardware.Sample(ct);
                worker.FootprintMiB=Math.Max(worker.Memory.PeakMiB,(after?.UsedMiB??before.UsedMiB)-before.UsedMiB);
                if(after==null||after.FreeMiB<options.ReserveVramMiB)throw new InvalidOperationException("Worker vượt ngân sách VRAM sau warm-up; đã thu hồi.");
            }
            if(Hardware.Ram().AvailableMiB<options.ReserveRamMiB)throw new InvalidOperationException("Worker vượt ngân sách RAM sau warm-up; đã thu hồi.");
            lock(workerGate){
                if(!Ready)throw new InvalidOperationException("Coordinator đã dừng phiên nạp worker; hãy thử lại sau khi kết nối phục hồi.");
                if(worker.Draining)throw new InvalidOperationException("Worker đã được yêu cầu dừng trong khi nạp model.");
                worker.State="idle";
            }
            Error=null;
            logger.LogInformation("Worker {Worker} ready on {Device}; load {LoadMs:F0} ms",worker.Id,device,worker.View.LoadMs);
            return worker.View;
        }catch(Exception error){
            if(worker!=null){workers.TryRemove(worker.Id,out _);await worker.DisposeAsync();}
            if(error is IOException)throw new InvalidOperationException($"Không nạp được model trên {device}. Xem log server để biết lỗi runtime hoặc tài nguyên.",error);
            throw;
        }
    }
    public async Task RemoveWorker(string id)
    {
        if (!workers.TryGetValue(id, out var w)) throw new KeyNotFoundException("Worker not found.");
        var dispose = false;
        lock(workerGate) { w.Draining = true; if (w.State == "idle") dispose = workers.TryRemove(id, out _); }
        if(dispose) await w.DisposeAsync();
    }
    public async Task Cancel(Job job)
    {
        await store.Finish(job, "cancelled"); queue.Remove(job.Id);
        signals.Complete(job.Id);
        foreach (var w in workers.Values.Where(w => w.JobId == job.Id)) w.JobCancellation?.Cancel();
        DeleteImage(job.Id);
    }
    private void DeleteImage(string id)
    {
        try { File.Delete(options.ImagePath(id)); } catch (IOException) { }
    }
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(stoppingToken, shutdown.Token);
        while(!linked.IsCancellationRequested){
            await RunSession(linked.Token);
            if(linked.IsCancellationRequested)break;
            logger.LogWarning("Coordinator session ended; retrying Supabase recovery in 3 seconds");
            try{await Task.Delay(3000,linked.Token);}catch(OperationCanceledException){break;}
        }
    }
    private async Task RunSession(CancellationToken serverToken)
    {
        using var linked=CancellationTokenSource.CreateLinkedTokenSource(serverToken);
        var ct = linked.Token;
        Task? heartbeat=null;
        var initialized=false;var waitingForDatabase=false;
        using var heartStop=CancellationTokenSource.CreateLinkedTokenSource(ct);
        Directory.CreateDirectory(Path.Combine(options.Runtime, "images"));
        try
        {
            while (!ct.IsCancellationRequested)
            {
                try { await store.Initialize(ct); (await store.Settings(ct)).Apply(options); break; }
                catch (Exception e) when (e is not OperationCanceledException)
                { Error = "Supabase chưa sẵn sàng. Kiểm tra kết nối, migration và server.local.json."; logger.LogWarning("Database initialization failed ({Type})", e.GetType().Name); }
                await Task.Delay(3000, ct);
            }
            // Keep the lease alive during recovery and multiple sequential model warm-ups.
            heartbeat=Task.Run(async()=>{
                var confirmed=System.Diagnostics.Stopwatch.StartNew();
                try {while(!heartStop.IsCancellationRequested){
                    await Task.Delay(waitingForDatabase?1000:8000,heartStop.Token);
                    // The database lease lasts 45s. Retire this session by 30s
                    // without confirmation, leaving time to stop/requeue work.
                    var remaining=TimeSpan.FromSeconds(30)-confirmed.Elapsed;
                    if(remaining<=TimeSpan.Zero){linked.Cancel();break;}
                    using var attempt=CancellationTokenSource.CreateLinkedTokenSource(heartStop.Token);
                    attempt.CancelAfter(remaining);
                    try{
                        if(!await store.Ping(attempt.Token)){
                            Ready=false;Error="Supabase lease lost; recovering the coordinator.";
                            logger.LogError("Coordinator database lease lost");linked.Cancel();break;
                        }
                        confirmed.Restart();
                        if(waitingForDatabase){waitingForDatabase=false;Ready=initialized;Error=null;}
                    }catch(Exception e) when(e is DatabaseUnavailableException || e is OperationCanceledException && !heartStop.IsCancellationRequested){
                        Ready=false;waitingForDatabase=true;Error="Supabase tạm mất kết nối; đang tự kết nối lại.";
                        logger.LogWarning("Lease confirmation unavailable ({Type}); dispatch paused until confirmed",e.GetType().Name);
                        if(confirmed.Elapsed>=TimeSpan.FromSeconds(30)){linked.Cancel();break;}
                    }
                }}catch(OperationCanceledException) when(heartStop.IsCancellationRequested){}
            },heartStop.Token);
            await Admission.WaitAsync(ct);
            try{
            await spool.Recover(ct);
            var recovered = await store.Jobs(int.MaxValue, true);
            foreach (var job in recovered)
            {
                if (!File.Exists(options.ImagePath(job.Id))) await store.Finish(job, "failed", error: "Input missing after server restart.");
                else { if (job.State == "running") await store.Requeue(job.Id); Enqueue(job with { State = "queued" }); }
            }
            // Orphan uploads are never considered jobs. Remove leftovers from an interrupted submission.
            var ids = recovered.Select(j => j.Id + ".image").ToHashSet();
            foreach (var file in Directory.EnumerateFiles(Path.Combine(options.Runtime, "images")))
                if (!ids.Contains(Path.GetFileName(file))) File.Delete(file);
            }finally{Admission.Release();}
            initialized=true;Ready=!waitingForDatabase;if(Ready)Error=null;
            var targets=recoveryDevices??Enumerable.Repeat(options.Device,options.InitialWorkers).ToArray();
            foreach(var target in targets)
            {
                try { await AddWorker(ct,target); }
                catch (Exception e) when (e is not OperationCanceledException)
                { Error = e.Message; logger.LogWarning("Initial worker failed: {Reason}", e.Message); break; }
            }
            var nextSample = DateTime.MinValue; var nextCleanup = DateTime.UtcNow;
            var nextReceiptRecovery=DateTime.UtcNow.AddSeconds(5);
            while (!ct.IsCancellationRequested)
            {
                if (DateTime.UtcNow >= nextSample)
                {
                    await hardware.Sample(ct);
                    nextSample = DateTime.UtcNow.AddSeconds(3);
                }
                if (DateTime.UtcNow >= nextCleanup) { await store.Cleanup(); if(!string.IsNullOrEmpty(options.GatewayIngressKeySha256))await store.V2("ocr_v2_expire",new{}); nextCleanup = DateTime.UtcNow.AddMinutes(10); }
                if(DateTime.UtcNow>=nextReceiptRecovery&&await Admission.WaitAsync(0,ct)){
                    try{
                        // A committed receipt can outlive the request/response
                        // that created it. Recover without requiring that client
                        // to reconnect or restarting all warmed model workers.
                        await spool.Recover(ct,8);
                        // Also catches a successful DB commit followed by a
                        // failed Find/enqueue response, after its receipt was
                        // already removed. A DB job is the durable source of truth.
                        var pending=await store.Jobs(options.QueueCapacity,true);
                        lock(workerGate){
                            var active=workers.Values.Where(w=>w.JobId!=null).Select(w=>w.JobId!).ToHashSet();
                            foreach(var job in queue.Recover(pending.Where(j=>File.Exists(options.ImagePath(j.Id))),active))signals.Register(job.Id);
                        }
                    }catch(DatabaseUnavailableException){logger.LogWarning("Receipt recovery waiting for database; retrying without restarting model workers");}
                    finally{Admission.Release();nextReceiptRecovery=DateTime.UtcNow.AddSeconds(5);}
                }
                for(var dispatched=0;dispatched<workers.Count;dispatched++)
                {
                    Job? job;ModelWorker worker;
                    lock(workerGate) {
                        if(!Ready || options.DispatchPaused || queue.Count==0)break;
                        var next=rotation.Next(workers.Values.Select(w=>new WorkerSlot(w.Id,w.CreatedAt,w.State=="idle"&&!w.Draining)));
                        if(next==null || !workers.TryGetValue(next,out worker!))break;
                        job = queue.Take(); if(job == null) break;
                        worker.State = "busy"; worker.JobId = job.Id;
                    }
                    var task = Task.Run(()=>ExecuteJob(worker,job,ct), ct);
                    work[worker.Id] = task;
                    _=task.ContinueWith(_=>{
                        if(work.TryGetValue(worker.Id,out var current)&&ReferenceEquals(current,task))work.TryRemove(worker.Id,out var ignored);
                    },TaskContinuationOptions.ExecuteSynchronously);
                }
                await Task.Delay(100, ct);
            }
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested) { }
        catch (Exception e) { Error = "Coordinator stopped: " + e.Message; logger.LogError("Coordinator stopped ({Type})", e.GetType().Name); }
        finally
        {
            heartStop.Cancel();if(heartbeat!=null){try{await heartbeat;}catch(OperationCanceledException){}}
            Ready = false;
            signals.Clear();
            if(initialized)recoveryDevices=workers.Values.Where(w=>!w.Draining).OrderBy(w=>w.CreatedAt).Select(w=>w.Device).ToArray();
            foreach (var w in workers.Values) w.JobCancellation?.Cancel();
            await Task.WhenAll(work.Values.Select(async t => { try { await t; } catch { } }));
            foreach (var w in workers.Values) await w.DisposeAsync();
            workers.Clear();
            work.Clear();queue.Clear();
        }
    }
    private async Task ExecuteJob(ModelWorker worker, Job pending, CancellationToken serverToken)
    {
        var job = pending; var replace = false;var executing=false;var removeAfterExit=false;
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(serverToken);
        deadline.CancelAfter(TimeSpan.FromSeconds(options.JobTimeoutSeconds)); worker.JobCancellation = deadline;
        try
        {
            job = await store.Start(job, worker.Id);
            executing=true;
            var value = await worker.Recognize(job, deadline.Token);
            var ok = value.GetProperty("ok").GetBoolean();
            await store.Finish(job, ok ? "succeeded" : "failed", ok ? value.GetProperty("text").GetString() : null,
                ok ? null : value.GetProperty("error").GetString(), value.GetProperty("elapsedMs").GetDouble(),
                ok ? value.GetProperty("width").GetInt32() : 0, ok ? value.GetProperty("height").GetInt32() : 0);
            signals.Complete(job.Id);
            DeleteImage(job.Id);
        }
        catch (OperationCanceledException)
        {
            replace = executing;
            if (serverToken.IsCancellationRequested) { try { await store.Requeue(job.Id); } catch { } }
            else
            {
                try { await store.Finish(job, "failed", error: "Inference timeout or cancellation."); } catch { }
                signals.Complete(job.Id);
                removeAfterExit=true;
                DeleteImage(job.Id);
            }
        }
        catch (Exception e)
        {
            replace = true;
            logger.LogWarning("Job {Job} failed ({Type}); retiring {Worker}", job.Id, e.GetType().Name, worker.Id);
            if (job.Attempts < 2 && File.Exists(options.ImagePath(job.Id)))
            {
                try { await store.Requeue(job.Id); queue.Add(job with { State = "queued" }); } catch { }
            }
            else { try { await store.Finish(job, "failed", error: "Model worker failed twice; see server diagnostics.");signals.Complete(job.Id); removeAfterExit=true;DeleteImage(job.Id); } catch { } }
        }
        finally
        {
            var dispose = false;
            lock(workerGate) {
                worker.JobCancellation = null; worker.JobId = null;
                if(replace || worker.Draining) dispose=workers.TryRemove(worker.Id,out _);
                else worker.State="idle";
            }
            if(dispose) await worker.DisposeAsync();
            if(removeAfterExit)DeleteImage(job.Id); // Windows may have held the input open until the child exited.
            if (replace && !worker.Draining && !serverToken.IsCancellationRequested)
            {
                try { await AddWorker(serverToken,worker.Device); }
                catch (Exception e) { Error = "Worker recovery: " + e.Message; }
            }
        }
    }
}
