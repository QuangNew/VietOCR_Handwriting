using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace VietOcr.Server;

// A CUDA worker may create compiler/helper children. All belong to the same job:
// killing the C# host closes its handles and Windows reaps the entire model tree.
public sealed class WindowsJob : IDisposable
{
    private readonly SafeFileHandle handle;
    [StructLayout(LayoutKind.Sequential)] private struct BasicLimits
    {
        public long ProcessTime,JobTime;public uint Flags;public UIntPtr MinWorking,MaxWorking;
        public uint ActiveLimit;public UIntPtr Affinity;public uint Priority,Scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] private struct IoCounters
    {public ulong Reads,Writes,Other,ReadBytes,WriteBytes,OtherBytes;}
    [StructLayout(LayoutKind.Sequential)] private struct Limits
    {public BasicLimits Basic;public IoCounters Io;public UIntPtr ProcessMemory,JobMemory,PeakProcessMemory,PeakJobMemory;}
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]
    private static extern SafeFileHandle CreateJobObject(IntPtr attributes,string? name);
    [DllImport("kernel32.dll",SetLastError=true)]
    [return:MarshalAs(UnmanagedType.Bool)] private static extern bool SetInformationJobObject(SafeFileHandle job,int kind,IntPtr info,uint length);
    [DllImport("kernel32.dll",SetLastError=true)]
    [return:MarshalAs(UnmanagedType.Bool)] private static extern bool AssignProcessToJobObject(SafeFileHandle job,IntPtr process);
    [DllImport("kernel32.dll",SetLastError=true)]
    [return:MarshalAs(UnmanagedType.Bool)] private static extern bool IsProcessInJob(IntPtr process,SafeFileHandle job,[MarshalAs(UnmanagedType.Bool)]out bool present);
    [DllImport("kernel32.dll",SetLastError=true)]
    [return:MarshalAs(UnmanagedType.Bool)] private static extern bool QueryInformationJobObject(SafeFileHandle job,int kind,IntPtr info,uint length,out uint returned);
    public WindowsJob(Process process)
    {
        handle=CreateJobObject(IntPtr.Zero,null);
        if(handle.IsInvalid)throw new Win32Exception(Marshal.GetLastWin32Error());
        var info=new Limits {Basic=new BasicLimits {Flags=0x2000}};
        var buffer=Marshal.AllocHGlobal(Marshal.SizeOf<Limits>());
        try {
            Marshal.StructureToPtr(info,buffer,false);
            if(!SetInformationJobObject(handle,9,buffer,(uint)Marshal.SizeOf<Limits>()) || !AssignProcessToJobObject(handle,process.Handle))
                throw new Win32Exception(Marshal.GetLastWin32Error());
        }catch{handle.Dispose();throw;}finally{Marshal.FreeHGlobal(buffer);}
    }
    public double WorkingSetMiB()
    {
        for(var size=512;size<=1048576;size*=2){
            var buffer=Marshal.AllocHGlobal(size);
            try{
                if(!QueryInformationJobObject(handle,3,buffer,(uint)size,out _)){
                    if(Marshal.GetLastWin32Error()==234)continue;return 0;
                }
                var count=Marshal.ReadInt32(buffer,4);double total=0;
                for(var i=0;i<count;i++){
                    var pid=Marshal.ReadIntPtr(buffer,8+i*IntPtr.Size).ToInt32();
                    try{using var p=Process.GetProcessById(pid);total+=p.WorkingSet64/1048576d;}catch(ArgumentException){}catch(InvalidOperationException){}
                }
                return total;
            }finally{Marshal.FreeHGlobal(buffer);}
        }
        return 0;
    }
    public void Include(int pid)
    {
        using var p=Process.GetProcessById(pid);
        if(!IsProcessInJob(p.Handle,handle,out var present))throw new Win32Exception(Marshal.GetLastWin32Error());
        if(!present && !AssignProcessToJobObject(handle,p.Handle))throw new Win32Exception(Marshal.GetLastWin32Error());
    }
    public void Dispose()=>handle.Dispose();
}
