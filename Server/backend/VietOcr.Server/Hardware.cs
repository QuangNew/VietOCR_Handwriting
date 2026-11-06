using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Globalization;

namespace VietOcr.Server;

public sealed class Hardware(ServerOptions options)
{
    private readonly SemaphoreSlim deviceLock=new(1,1);
    private List<WorkerDevice>? deviceCache;
    private DateTime devicesAt;
    public async Task<IReadOnlyList<WorkerDevice>> Devices(CancellationToken ct=default)
    {
        await deviceLock.WaitAsync(ct);
        try{
            if(deviceCache!=null && DateTime.UtcNow-devicesAt<TimeSpan.FromSeconds(30))return deviceCache;
            var rows=new List<WorkerDevice>();
            var gpu=await Sample(ct);
            if(gpu!=null)rows.Add(new("cuda:0",gpu.Name+" · CUDA","discrete"));
            try{
                using var deadline=CancellationTokenSource.CreateLinkedTokenSource(ct);deadline.CancelAfter(TimeSpan.FromSeconds(15));
                using var process=new Process{StartInfo=new(Path.GetFullPath(options.Python,options.Root)){
                    UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true,
                    StandardOutputEncoding=System.Text.Encoding.UTF8,WorkingDirectory=options.Root}};
                foreach(var arg in new[]{"-X","utf8",Path.Combine(options.Root,"worker/devices.py")})process.StartInfo.ArgumentList.Add(arg);
                process.Start();
                try{
                    var output=process.StandardOutput.ReadToEndAsync(deadline.Token);var error=process.StandardError.ReadToEndAsync(deadline.Token);
                    await process.WaitForExitAsync(deadline.Token);
                    if(process.ExitCode==0)rows.AddRange(System.Text.Json.JsonSerializer.Deserialize<List<WorkerDevice>>(await output,new System.Text.Json.JsonSerializerOptions(System.Text.Json.JsonSerializerDefaults.Web))??[]);
                    await error;
                }finally{if(!process.HasExited)process.Kill(true);}
            }catch(Exception e) when(e is not OperationCanceledException || !ct.IsCancellationRequested){}
            rows.Add(new("cpu","CPU · PyTorch","cpu"));
            deviceCache=rows;devicesAt=DateTime.UtcNow;return rows;
        }finally{deviceLock.Release();}
    }
    private readonly SemaphoreSlim sampleLock = new(1, 1);
    public GpuSnapshot? Gpu { get; private set; }
    public string? Error { get; private set; }
    public async Task<GpuSnapshot?> Sample(CancellationToken ct = default)
    {
        await sampleLock.WaitAsync(ct);
        try
        {
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
            timeout.CancelAfter(TimeSpan.FromSeconds(4));
            using var process = new Process { StartInfo = new("nvidia-smi") {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true } };
            process.StartInfo.ArgumentList.Add("--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu");
            process.StartInfo.ArgumentList.Add("--format=csv,noheader,nounits");
            process.Start();
            try
            {
                var stdout = process.StandardOutput.ReadToEndAsync(timeout.Token);
                var stderr = process.StandardError.ReadToEndAsync(timeout.Token);
                await process.WaitForExitAsync(timeout.Token);
                var selected = options.Device.StartsWith("cuda:") ? options.Device[5..] : "0";
                var row = (await stdout).Split('\n').Select(x => x.Split(',').Select(p => p.Trim()).ToArray())
                    .FirstOrDefault(x => x.Length == 7 && x[0] == selected);
                if (row == null || process.ExitCode != 0) throw new IOException("GPU metrics not available");
                int I(int i) => int.Parse(row[i], CultureInfo.InvariantCulture);
                Gpu = new(row[1], I(2), I(3), I(4), I(5), I(6), DateTime.UtcNow); Error = null;
                return Gpu;
            }
            finally { if (!process.HasExited) process.Kill(true); }
        }
        catch (Exception e) when (e is not OperationCanceledException || !ct.IsCancellationRequested)
        { Error = "Không đọc được GPU; không cho thêm CUDA worker khi thiếu số liệu."; return null; }
        finally { sampleLock.Release(); }
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct MemoryStatus
    {
        public uint Length, Load;
        public ulong TotalPhysical, AvailablePhysical, TotalPageFile, AvailablePageFile, TotalVirtual, AvailableVirtual, AvailableExtended;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Auto)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GlobalMemoryStatusEx(ref MemoryStatus status);
    public static (double TotalMiB, double AvailableMiB) Ram()
    {
        if (OperatingSystem.IsWindows())
        {
            var s = new MemoryStatus { Length = (uint)Marshal.SizeOf<MemoryStatus>() };
            if (GlobalMemoryStatusEx(ref s)) return (s.TotalPhysical / 1048576d, s.AvailablePhysical / 1048576d);
        }
        var info = GC.GetGCMemoryInfo(); return (info.TotalAvailableMemoryBytes / 1048576d,
            Math.Max(0, info.TotalAvailableMemoryBytes - info.MemoryLoadBytes) / 1048576d);
    }
}
