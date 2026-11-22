namespace VietOcr.Server;

public sealed record RuntimeSettings(bool AcceptingRequests=true,bool DispatchPaused=false,int QueueCapacity=1000,
    int PerClientPending=100,int JobTimeoutSeconds=120,int RetentionHours=24,int ReserveRamMiB=1024,
    int ReserveVramMiB=1024,int WorkerBudgetMiB=300,int InitialWorkers=1,int MaxUploadMiB=16,
    long MaxPixels=16_000_000,long SpoolMiB=1024,int DefaultDailyLimit=AccountPolicy.DailyImageCap,int DefaultRatePerMinute=AccountPolicy.MinuteRequestCap)
{
    public void Validate()
    {
        if(QueueCapacity is <1 or >100000||PerClientPending<1||PerClientPending>QueueCapacity||JobTimeoutSeconds is <5 or >600||
           RetentionHours is <1 or >720||ReserveRamMiB is <512 or >65536||ReserveVramMiB is <512 or >65536||
           WorkerBudgetMiB is <100 or >16384||InitialWorkers is <0 or >256||MaxUploadMiB is <1 or >64||
           MaxPixels is <10000 or >40000000||SpoolMiB<MaxUploadMiB||SpoolMiB>1048576||
           DefaultDailyLimit is <1 or >AccountPolicy.DailyImageCap||DefaultRatePerMinute is <1 or >AccountPolicy.MinuteRequestCap)
            throw new ArgumentException("Cấu hình vượt khoảng cho phép. Hạn mức tài khoản tối đa 500/ngày, 30/phút; RAM/VRAM dự phòng ít nhất 512 MiB.");
    }
    public void Apply(ServerOptions o)
    {
        Validate();o.AcceptingRequests=AcceptingRequests;o.DispatchPaused=DispatchPaused;o.QueueCapacity=QueueCapacity;
        o.PerClientPending=PerClientPending;o.JobTimeoutSeconds=JobTimeoutSeconds;o.RetentionHours=RetentionHours;
        o.ReserveRamMiB=ReserveRamMiB;o.ReserveVramMiB=ReserveVramMiB;o.WorkerBudgetMiB=WorkerBudgetMiB;
        o.InitialWorkers=InitialWorkers;o.MaxUploadMiB=MaxUploadMiB;o.MaxPixels=MaxPixels;o.SpoolMiB=SpoolMiB;
    }
}
