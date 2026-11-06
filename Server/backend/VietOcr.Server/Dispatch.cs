using System.Collections.Concurrent;
namespace VietOcr.Server;

public sealed record WorkerSlot(string Id,DateTime CreatedAt,bool Available);

public static class WorkerDevicePolicy
{
    public static WorkerDevice[] Candidates(IEnumerable<WorkerDevice> devices,string requested)=>devices
        .Where(d=>d.Available && (requested=="auto" || requested=="integrated"&&d.Kind=="integrated" ||
            d.Id==requested || requested=="cuda"&&d.Id.StartsWith("cuda:")))
        .OrderBy(d=>d.Kind=="discrete"?0:d.Kind=="integrated"?1:2).ToArray();
}

// Rotate across every eligible worker. Busy/draining workers are skipped, so
// heterogeneous CPU/GPU workers naturally take new work as each becomes free.
public sealed class WorkerRotation
{
    private (DateTime Time,string Id)? last;
    public string? Next(IEnumerable<WorkerSlot> slots)
    {
        var eligible=slots.Where(s=>s.Available).OrderBy(s=>s.CreatedAt).ThenBy(s=>s.Id,StringComparer.Ordinal).ToArray();
        if(eligible.Length==0)return null;
        var chosen=last is {} prior?eligible.FirstOrDefault(s=>s.CreatedAt>prior.Time || s.CreatedAt==prior.Time&&string.CompareOrdinal(s.Id,prior.Id)>0)??eligible[0]:eligible[0];
        last=(chosen.CreatedAt,chosen.Id);return chosen.Id;
    }
}

// Completion notifications contain no image/result text. Only pending jobs have
// entries; HTTP waiters do not poll Postgres while a worker is still running.
public sealed class JobSignals
{
    private readonly ConcurrentDictionary<string,TaskCompletionSource> pending=new();
    public int Count=>pending.Count;
    public void Register(string id)=>pending.TryAdd(id,new(TaskCreationOptions.RunContinuationsAsynchronously));
    public void Complete(string id){if(pending.TryRemove(id,out var signal))signal.TrySetResult();}
    public async Task Wait(string id,TimeSpan timeout,CancellationToken ct)
    {
        if(!pending.TryGetValue(id,out var signal))return;
        try{await signal.Task.WaitAsync(timeout,ct);}catch(TimeoutException){}
    }
    public void Clear(){foreach(var id in pending.Keys)Complete(id);}
}
