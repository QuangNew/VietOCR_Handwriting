using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;

namespace VietOcr.Server;

// A small status payload with no OCR text, account information, keys or database round trips.
public sealed record ServerLoadSnapshot(string ServerId,long SampledAtUnixMs,double UptimeSeconds,bool Ready,
    double? CpuPercent,double? RamUsedPercent,int IdleWorkers,int BusyWorkers,int StartingWorkers,int DrainingWorkers,int QueuedJobs);

public static class GatewayTelemetryCredential
{
    public static bool Validate(string header,string configuredHash)
    {
        if(configuredHash.Length!=64 || !header.StartsWith("Bearer ",StringComparison.Ordinal))return false;
        var token=header[7..];
        if(token.Length is <32 or >256 || token.Any(c=>!char.IsAsciiLetterOrDigit(c)&&c is not ('-' or '_')))return false;
        try { return CryptographicOperations.FixedTimeEquals(SHA256.HashData(Encoding.UTF8.GetBytes(token)),Convert.FromHexString(configuredHash)); }
        catch(FormatException){return false;}
    }
}

// Host CPU utilisation, including every process: never substitute API-process CPU for server load.
public sealed class CpuLoadSampler
{
    private (ulong Idle,ulong Total)? previous;
    [DllImport("kernel32.dll",SetLastError=true)]
    [return:MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetSystemTimes(out ulong idle,out ulong kernel,out ulong user);
    public double? Sample()
    {
        if(!OperatingSystem.IsWindows() || !GetSystemTimes(out var idle,out var kernel,out var user))return null;
        return Observe(idle,kernel+user);
    }
    public double? Observe(ulong idle,ulong total)
    {
        var last=previous;previous=(idle,total);
        if(last==null || total<=last.Value.Total || idle<last.Value.Idle)return null;
        var elapsed=total-last.Value.Total;var idleElapsed=idle-last.Value.Idle;
        return idleElapsed>elapsed?null:100d*(elapsed-idleElapsed)/elapsed;
    }
}

public sealed class ServerLoadMonitor(Coordinator coordinator,ServerOptions options,ILogger<ServerLoadMonitor> logger):BackgroundService
{
    private readonly CpuLoadSampler cpu=new();
    private ServerLoadSnapshot current=new(options.ServerId,DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),0,false,null,null,0,0,0,0,0);
    public ServerLoadSnapshot Current=>Volatile.Read(ref current);
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        using var timer=new PeriodicTimer(TimeSpan.FromSeconds(2));
        try {
            do {
                var views=coordinator.Workers;var ram=Hardware.Ram();
                var memory=ram.TotalMiB>0?Math.Clamp(100d*(ram.TotalMiB-ram.AvailableMiB)/ram.TotalMiB,0,100):(double?)null;
                var sample=new ServerLoadSnapshot(options.ServerId,DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                    Math.Max(0,(DateTime.UtcNow-coordinator.StartedAt).TotalSeconds),coordinator.Ready,cpu.Sample(),memory,
                    views.Count(w=>w.State=="idle"&&!w.Draining),views.Count(w=>w.State=="busy"&&!w.Draining),
                    views.Count(w=>w.State=="starting"&&!w.Draining),views.Count(w=>w.Draining),coordinator.Queued);
                Volatile.Write(ref current,sample);
            }while(await timer.WaitForNextTickAsync(stoppingToken));
        }catch(OperationCanceledException)when(stoppingToken.IsCancellationRequested){}
        catch(Exception e){logger.LogError("Host telemetry stopped ({Type}); Pi must mark its last sample stale",e.GetType().Name);}
    }
}
