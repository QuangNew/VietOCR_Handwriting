using VietOcr.Server;
using Xunit;

namespace VietOcr.Server.Tests;

public class DispatchTests
{
    private static readonly DateTime Created = new(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc);
    private static WorkerSlot Slot(string id, bool available = true) => new(id, Created, available);

    [Fact] public void AutoPrefersDiscreteThenIntegratedThenCpu()
    {
        WorkerDevice[] devices=[new("cpu","CPU","cpu"),new("directml:0","Intel","integrated"),new("cuda:0","NVIDIA","discrete")];
        Assert.Equal(new[]{"cuda:0","directml:0","cpu"},WorkerDevicePolicy.Candidates(devices,"auto").Select(d=>d.Id));
        Assert.Equal("cpu",Assert.Single(WorkerDevicePolicy.Candidates(devices,"cpu")).Id);
    }

    [Fact] public void MissingGpuDoesNotExcludeCpuOrInventAvailableBackends()
    {
        WorkerDevice[] devices=[new("cpu","CPU","cpu"),new("directml:0","Intel","integrated",false,"missing model export")];
        Assert.Equal("cpu",Assert.Single(WorkerDevicePolicy.Candidates(devices,"auto")).Id);
        Assert.Empty(WorkerDevicePolicy.Candidates(devices,"cuda:0"));
        Assert.Empty(WorkerDevicePolicy.Candidates(devices,"integrated"));
        Assert.Empty(WorkerDevicePolicy.Candidates(devices,"unknown"));
    }

    [Fact] public void SuccessiveSingleRequestsRotateEvenWhenEveryWorkerIsIdle()
    {
        var rotation = new WorkerRotation();
        var workers = new[] { Slot("gpu-2"), Slot("cpu"), Slot("gpu-1") };
        var counts = workers.ToDictionary(w => w.Id, _ => 0);
        for (var i = 0; i < 300; i++) counts[rotation.Next(workers)!]++;
        Assert.All(counts.Values, count => Assert.Equal(100, count));
    }

    [Fact] public void BusyAndDrainingWorkersNeverReceiveAnotherJob()
    {
        var rotation = new WorkerRotation();
        Assert.Equal("a", rotation.Next([Slot("a"), Slot("b"), Slot("c")]));
        Assert.Equal("c", rotation.Next([Slot("a", false), Slot("b", false), Slot("c")]));
        Assert.Null(rotation.Next([Slot("a", false), Slot("b", false), Slot("c", false)]));
        Assert.Equal("a", rotation.Next([Slot("a"), Slot("b"), Slot("c")]));
    }

    [Fact] public void FastWorkersKeepWorkingWhileSlowWorkerIsBusy()
    {
        var rotation = new WorkerRotation();
        Assert.Equal("cpu", rotation.Next([Slot("cpu"), Slot("gpu")]));
        for (var i = 0; i < 20; i++)
            Assert.Equal("gpu", rotation.Next([Slot("cpu", false), Slot("gpu")]));
        Assert.Equal("cpu", rotation.Next([Slot("cpu"), Slot("gpu")]));
    }

    [Fact] public void RetiringLastSelectedWorkerDoesNotStarveTheRemainingWorkers()
    {
        var rotation = new WorkerRotation();
        Assert.Equal("b", rotation.Next([Slot("b"), Slot("c")]));
        Assert.Equal("c", rotation.Next([Slot("a"), Slot("c")]));
        Assert.Equal("a", rotation.Next([Slot("a"), Slot("c")]));
    }

    [Fact] public void PendingBatchUsesAllIdleWorkersAndKeepsClientsFair()
    {
        var queue = new FairQueue();
        Job Job(string id, string client) => new(id, client, client, null, "hash", "line", "queued", 100, Created);
        for (var i = 0; i < 20; i++) queue.Add(Job("batch-" + i, "batch"));
        queue.Add(Job("interactive", "person"));
        var rotation = new WorkerRotation();
        var idle = new HashSet<string> { "cpu", "gpu-1", "gpu-2" };
        var assignments = new Dictionary<string, Job>();
        while (rotation.Next(idle.Select(id => Slot(id))) is { } worker)
        {
            assignments.Add(worker, queue.Take()!); idle.Remove(worker);
        }
        Assert.Equal(3, assignments.Count);
        Assert.Contains(assignments.Values, job => job.Id == "interactive");
        Assert.Equal(18, queue.Count);
    }

    [Fact] public async Task CompletionWakesEveryWaiterWithoutKeepingResults()
    {
        var signals = new JobSignals(); signals.Register("job");
        var waiters = Enumerable.Range(0, 20).Select(_ => signals.Wait("job", TimeSpan.FromSeconds(3), default)).ToArray();
        Assert.All(waiters, task => Assert.False(task.IsCompleted));
        signals.Complete("job"); await Task.WhenAll(waiters);
        Assert.Equal(0, signals.Count);
        await signals.Wait("job", TimeSpan.FromSeconds(3), default);
    }

    [Fact] public async Task HttpTimeoutDoesNotCancelOrRemoveTheJob()
    {
        var signals = new JobSignals(); signals.Register("job");
        await signals.Wait("job", TimeSpan.Zero, default);
        Assert.Equal(1, signals.Count);
        var waiter = signals.Wait("job", TimeSpan.FromSeconds(3), default);
        signals.Register("job"); // A recovery/retry cannot replace existing waiters.
        signals.Complete("job"); await waiter;
        Assert.Equal(0, signals.Count);
    }

    [Fact] public async Task DisconnectedHttpClientDoesNotCancelAnotherClientsWaiter()
    {
        var signals = new JobSignals(); signals.Register("job");
        using var disconnected = new CancellationTokenSource();
        var first = signals.Wait("job", TimeSpan.FromSeconds(3), disconnected.Token);
        var second = signals.Wait("job", TimeSpan.FromSeconds(3), default);
        disconnected.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => first);
        Assert.False(second.IsCompleted); Assert.Equal(1, signals.Count);
        signals.Clear(); await second; Assert.Equal(0, signals.Count);
    }
}
