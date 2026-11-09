using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using Microsoft.AspNetCore.DataProtection;

namespace VietOcr.Server;

public sealed class V2Exception(int status,string code) : Exception(code)
{ public int Status { get; }=status; public string Code { get; }=code; }
public sealed record FlowIdentity(Guid UserId,Guid SessionId);
public sealed record FlowIntent(Guid Id,Guid UserId,Guid SessionId,string ClientId,string State,
    string Sha256,long ImageBytes,string MediaType,string Layout,int ImageVersion,long Generation);
public sealed record CreateIntent(Guid UserId,Guid SessionId,Guid RequestId,string Sha256,long ImageBytes,
    string MediaType,string Layout,int ImageVersion);
public sealed record FlowCommand(Guid UserId,Guid SessionId,long Generation=0,bool Cancel=false);
public sealed record ImageInfo(int Width,int Height,string MediaType);
public interface IFlowDatabase
{
    Task<JsonElement> Gateway(string action,object p,CancellationToken ct=default);
    Task<JsonElement> Commit(FlowIntent intent,CancellationToken ct=default);
}
public sealed class FlowDatabase(Store store,ServerOptions options) : IFlowDatabase
{
    public Task<JsonElement> Gateway(string action,object p,CancellationToken ct=default)=>
        store.V2("ocr_v2_gateway",new{action,p},ct);
    public Task<JsonElement> Commit(FlowIntent i,CancellationToken ct=default)=>store.V2("ocr_v2_commit",new{
        p_job_id=i.Id,p_generation=i.Generation,p_server_id=options.ServerId,p_hash=i.Sha256,p_bytes=i.ImageBytes},ct);
}
public static class FlowJson
{
    public static readonly JsonSerializerOptions Options=new(JsonSerializerDefaults.Web);
    public static JsonElement Check(JsonElement v)
    {
        if(v.ValueKind==JsonValueKind.Object&&v.TryGetProperty("error",out var e)) throw new V2Exception(v.GetProperty("status").GetInt32(),e.GetString()??"flow_error");
        return v;
    }
    public static FlowIntent Intent(JsonElement v,FlowIdentity identity)
    {
        Check(v);if(v.TryGetProperty("intent",out var wrapped))v=wrapped;
        return new(v.GetProperty("id").GetGuid(),identity.UserId,identity.SessionId,v.GetProperty("client_id").GetString()!,
            v.GetProperty("state").GetString()!,v.GetProperty("image_hash").GetString()!,v.GetProperty("image_bytes").GetInt64(),
            v.GetProperty("media_type").GetString()!,v.GetProperty("layout").GetString()!,v.GetProperty("image_version").GetInt32(),
            v.GetProperty("lease_generation").GetInt64());
    }
}

public interface IImageVerifier { Task<ImageInfo> Verify(string path,CancellationToken ct); }
public sealed class PillowImageVerifier(ServerOptions options) : IImageVerifier
{
    public async Task<ImageInfo> Verify(string path,CancellationToken ct)
    {
        using var deadline=CancellationTokenSource.CreateLinkedTokenSource(ct);deadline.CancelAfter(TimeSpan.FromSeconds(15));
        var start=new ProcessStartInfo(Path.GetFullPath(Path.Combine(options.Root,options.Python))) {
            UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true};
        start.ArgumentList.Add(Path.Combine(options.Root,"worker","validate_image.py"));start.ArgumentList.Add(path);
        start.ArgumentList.Add(options.MaxPixels.ToString(System.Globalization.CultureInfo.InvariantCulture));
        using var process=Process.Start(start)??throw new V2Exception(503,"image_verifier_unavailable");
        try {
            var output=process.StandardOutput.ReadToEndAsync(deadline.Token);
            var errors=process.StandardError.ReadToEndAsync(deadline.Token);
            await process.WaitForExitAsync(deadline.Token);var json=await output;await errors;
            if(process.ExitCode!=0 || json.Length>4096)throw new V2Exception(422,"invalid_image");
            return JsonSerializer.Deserialize<ImageInfo>(json,FlowJson.Options)??throw new V2Exception(422,"invalid_image");
        }finally{if(!process.HasExited)process.Kill(entireProcessTree:true);}
    }
}

// Partial images live only on compute disk. A receipt is fsynced before the
// image is published and before Postgres quota commit. Restart reconciles it.
public sealed class V2Spool(ServerOptions options,IFlowDatabase db,IImageVerifier verifier)
{
    public const int ChunkBytes=1024*1024;
    private readonly SemaphoreSlim[] gates=Enumerable.Range(0,64).Select(_=>new SemaphoreSlim(1,1)).ToArray();
    private readonly SemaphoreSlim uploads=new(options.ConcurrentUploads,options.ConcurrentUploads);
    private string Root=>Path.Combine(options.Runtime,"v2-spool");
    private string Partial(FlowIntent i)=>Path.Combine(Root,$"{i.Id:D}.{i.Generation}.part");
    private string Receipt(FlowIntent i)=>Path.Combine(Root,$"{i.Id:D}.receipt.json");
    private SemaphoreSlim Gate(Guid id)=>gates[(int)((uint)id.GetHashCode()%gates.Length)];
    public async Task<long> Offset(FlowIntent i,CancellationToken ct)
    {
        await Gate(i.Id).WaitAsync(ct);
        try{return File.Exists(Partial(i))?new FileInfo(Partial(i)).Length:0;}finally{Gate(i.Id).Release();}
    }
    public async Task<long> Append(FlowIntent i,long offset,Stream body,long length,CancellationToken ct)
    {
        if(i.State is not ("upload_granted" or "uploading")||i.Generation<1)throw new V2Exception(409,"upload_not_granted");
        if(offset<0||length<1||length>ChunkBytes||offset+length>i.ImageBytes)throw new V2Exception(400,"invalid_chunk");
        if(!await uploads.WaitAsync(0,ct))throw new V2Exception(429,"uploads_busy");
        try {
            await Gate(i.Id).WaitAsync(ct);
            try {
                Directory.CreateDirectory(Root);
                var path=Partial(i);var current=File.Exists(path)?new FileInfo(path).Length:0;
                if(current!=offset)throw new V2Exception(409,"offset_mismatch");
                var used=Directory.EnumerateFiles(Root).Sum(p=>new FileInfo(p).Length)+
                    (Directory.Exists(Path.Combine(options.Runtime,"images"))?Directory.EnumerateFiles(Path.Combine(options.Runtime,"images")).Sum(p=>new FileInfo(p).Length):0);
                if(used+length>options.SpoolMiB*1048576L)throw new V2Exception(507,"spool_capacity");
                await using var file=new FileStream(path,FileMode.OpenOrCreate,FileAccess.Write,FileShare.None,65536,FileOptions.Asynchronous);
                file.Position=current;var buffer=new byte[65536];long received=0;
                try{
                    while(received<length){var n=await body.ReadAsync(buffer.AsMemory(0,(int)Math.Min(buffer.Length,length-received)),ct);
                        if(n==0)throw new V2Exception(400,"incomplete_chunk");
                        await file.WriteAsync(buffer.AsMemory(0,n),ct);received+=n;}
                    if(await body.ReadAsync(buffer.AsMemory(0,1),ct)!=0)throw new V2Exception(400,"chunk_length_mismatch");
                    await file.FlushAsync(ct);file.Flush(flushToDisk:true);
                }catch{file.SetLength(current);file.Flush(flushToDisk:true);throw;}
                return current+received;
            }finally{Gate(i.Id).Release();}
        }finally{uploads.Release();}
    }
    public async Task<JsonElement> Complete(FlowIntent i,CancellationToken ct)
    {
        if(!await uploads.WaitAsync(0,ct))throw new V2Exception(429,"uploads_busy");
        try{
            await Gate(i.Id).WaitAsync(ct);
            try{
                if(i.State is "queued" or "running" or "succeeded" or "failed" or "cancelled")
                    return JsonSerializer.SerializeToElement(new{accepted=true,duplicate=true,jobId=i.Id});
                var part=Partial(i);var published=options.ImagePath(i.Id.ToString("D"));
                // A response/DB outage after publication can be retried without reuploading.
                var path=File.Exists(published)&&File.Exists(Receipt(i))?published:part;
                if(!File.Exists(path)||new FileInfo(path).Length!=i.ImageBytes)throw new V2Exception(409,"image_incomplete");
                await using(var image=File.OpenRead(path)) {
                    var hash=Convert.ToHexStringLower(await SHA256.HashDataAsync(image,ct));
                    if(hash!=i.Sha256)throw new V2Exception(422,"image_integrity");
                }
                var info=await verifier.Verify(path,ct);
                if(info.MediaType!=i.MediaType||info.Width<2||info.Height<2||(long)info.Width*info.Height>options.MaxPixels)
                    throw new V2Exception(422,"image_dimensions_or_type");
                Directory.CreateDirectory(Path.GetDirectoryName(published)!);
                var receipt=Receipt(i);var temp=receipt+".tmp";
                await using(var output=new FileStream(temp,FileMode.Create,FileAccess.Write,FileShare.None,4096,FileOptions.Asynchronous)){
                    await JsonSerializer.SerializeAsync(output,i,FlowJson.Options,ct);await output.FlushAsync(ct);output.Flush(true);}
                File.Move(temp,receipt,true);
                if(path==part)File.Move(part,published,true);
                // Commit continues even if the client disconnects just after the last byte.
                using var commitDeadline=new CancellationTokenSource(TimeSpan.FromSeconds(20));
                var result=FlowJson.Check(await db.Commit(i,commitDeadline.Token));
                File.Delete(receipt);return result;
            }finally{Gate(i.Id).Release();}
        }finally{uploads.Release();}
    }
    public async Task Recover(CancellationToken ct)
    {
        Directory.CreateDirectory(Root);
        foreach(var receipt in Directory.EnumerateFiles(Root,"*.receipt.json")){
            var i=JsonSerializer.Deserialize<FlowIntent>(await File.ReadAllTextAsync(receipt,ct),FlowJson.Options)
                ??throw new InvalidDataException("Invalid private spool receipt.");
            if(!Path.GetFileName(receipt).Equals($"{i.Id:D}.receipt.json",StringComparison.Ordinal))throw new InvalidDataException("Receipt id mismatch.");
            try{await Complete(i,ct);}
            catch(V2Exception e)when(e.Status is 403 or 409 or 422){
                // A rejected/unaccepted receipt is not a quota refund. Existing jobs
                // are checked before deleting a potentially accepted image.
                // Coordinator recovery keeps files for committed DB jobs and
                // removes unaccepted orphans. Revoked sessions cannot stop startup.
                File.Delete(receipt);
            }
        }
        foreach(var path in Directory.EnumerateFiles(Root,"*.part"))
            if(File.GetLastWriteTimeUtc(path)<DateTime.UtcNow.AddHours(-24))File.Delete(path);
    }
}

public sealed record ResultAccess(Guid JobId,Guid UserId,Guid SessionId,string ClientId,DateTimeOffset ExpiresAt);
public sealed class ResultTickets(IDataProtectionProvider provider)
{
    private readonly IDataProtector protector=provider.CreateProtector("VietOCR.v2.result-only.v1");
    public string Issue(FlowIntent i)=>protector.Protect(JsonSerializer.Serialize(new ResultAccess(i.Id,i.UserId,i.SessionId,i.ClientId,DateTimeOffset.UtcNow.AddMinutes(5)),FlowJson.Options));
    public ResultAccess Read(string token,Guid job)
    {
        try{
            if(token.Length is <20 or >4096)throw new CryptographicException();
            var value=JsonSerializer.Deserialize<ResultAccess>(protector.Unprotect(token),FlowJson.Options)!;
            if(value.JobId!=job||value.ExpiresAt<=DateTimeOffset.UtcNow)throw new CryptographicException();
            return value;
        }catch(Exception e)when(e is CryptographicException or JsonException or NullReferenceException){throw new V2Exception(401,"result_ticket_invalid");}
    }
}

public static class V2Endpoints
{
    private static readonly SemaphoreSlim resultReaders=new(64,64);
    public static void MapV2(this WebApplication app,ServerOptions options)
    {
        var routes=app.MapGroup("/api/internal/v2");
        routes.AddEndpointFilter(async(context,next)=>{
            var ctx=context.HttpContext;
            if(!ctx.Request.IsHttps&&ctx.Connection.RemoteIpAddress is {} ip&&!System.Net.IPAddress.IsLoopback(ip))
                return Results.Json(new{error="https_required"},statusCode:426);
            if(string.IsNullOrWhiteSpace(options.GatewayIngressKeySha256))return Results.Json(new{error="gateway_not_configured"},statusCode:503);
            if(!GatewayTelemetryCredential.Validate(ctx.Request.Headers.Authorization.ToString(),options.GatewayIngressKeySha256))return Results.Unauthorized();
            return await next(context);
        });
        routes.MapPost("/intents",async(CreateIntent request,IFlowDatabase db,CancellationToken ct)=>{
            if(request.UserId==Guid.Empty||request.SessionId==Guid.Empty||request.RequestId==Guid.Empty||request.ImageVersion<1||request.ImageBytes<16||request.ImageBytes>options.MaxUploadMiB*1048576L||
                request.Sha256.Length!=64||request.Sha256.Any(c=>!char.IsAsciiHexDigitLower(c))||request.MediaType is not ("image/jpeg" or "image/png" or "image/webp")||request.Layout is not ("auto" or "line"))
                throw new V2Exception(400,"invalid_intent");
            var value=FlowJson.Check(await db.Gateway("create",new{request.UserId,request.SessionId,request.RequestId,jobId=Guid.NewGuid(),request.Sha256,request.ImageBytes,request.MediaType,request.Layout,request.ImageVersion},ct));
            return Results.Ok(FlowJson.Intent(value,new(request.UserId,request.SessionId)));
        });
        routes.MapPost("/history",async(FlowIdentity identity,IFlowDatabase db,CancellationToken ct)=>{
            var value=FlowJson.Check(await db.Gateway("history",identity,ct));
            return Results.Ok(value.EnumerateArray().Select(v=>FlowJson.Intent(v,identity)));
        });
        routes.MapPost("/intents/{id:guid}/state",async(Guid id,FlowCommand cmd,IFlowDatabase db,CancellationToken ct)=>
            Results.Ok(await Find(db,id,cmd,ct)));
        routes.MapPost("/intents/{id:guid}/grant",async(Guid id,FlowCommand cmd,IFlowDatabase db,V2Spool spool,Coordinator coordinator,CancellationToken ct)=>{
            var i=await Find(db,id,cmd,ct);
            if(i.State is "queued" or "running" or "succeeded" or "failed")return Results.Ok(new{accepted=true,id});
            if(!coordinator.Ready||!options.AcceptingRequests||options.DispatchPaused)throw new V2Exception(503,"server_not_ready");
            var ready=coordinator.Workers.Count(w=>!w.Draining&&w.State is "idle" or "busy");
            if(ready==0||coordinator.Queued>=Math.Max(2,ready*2))throw new V2Exception(429,"compute_queue_busy");
            var lease=FlowJson.Check(await db.Gateway("reserve",new{cmd.UserId,cmd.SessionId,jobId=id,serverId=options.ServerId},ct));
            if(lease.TryGetProperty("accepted",out var accepted)&&accepted.GetBoolean())return Results.Ok(new{accepted=true,id});
            var generation=lease.GetProperty("generation").GetInt64();i=i with{Generation=generation,State="upload_granted"};
            return Results.Ok(new{generation,expiresAt=lease.GetProperty("expiresAt"),offset=await spool.Offset(i,ct),chunkBytes=V2Spool.ChunkBytes});
        });
        routes.MapPut("/intents/{id:guid}/content",async(Guid id,HttpContext ctx,IFlowDatabase db,V2Spool spool,CancellationToken ct)=>{
            var cmd=HeaderCommand(ctx);var i=await Find(db,id,cmd,ct);
            if(i.Generation!=cmd.Generation)throw new V2Exception(409,"stale_lease");
            if(!long.TryParse(ctx.Request.Headers["Upload-Offset"],out var offset)||ctx.Request.ContentLength is not {} length)throw new V2Exception(400,"chunk_headers_required");
            return Results.Ok(new{offset=await spool.Append(i,offset,ctx.Request.Body,length,ct)});
        }).DisableAntiforgery();
        routes.MapPost("/intents/{id:guid}/complete",async(Guid id,FlowCommand cmd,IFlowDatabase db,V2Spool spool,Coordinator c,Store store,HttpContext ctx,CancellationToken ct)=>{
            var i=await Find(db,id,cmd,ct);if(i.Generation!=cmd.Generation)throw new V2Exception(409,"stale_lease");
            await c.Admission.WaitAsync(ct);
            try{
                await spool.Complete(i,ct);
                using var acceptedDeadline=new CancellationTokenSource(TimeSpan.FromSeconds(20));
                var job=await store.Find(id.ToString("D"),i.ClientId);
                if(job is {State:"queued"})c.Enqueue(job);
                return Results.Ok(new{accepted=true,jobId=id});
            }finally{c.Admission.Release();}
        });
        routes.MapPost("/intents/{id:guid}/cancel",async(Guid id,FlowCommand cmd,IFlowDatabase db,CancellationToken ct)=>
            Results.Ok(FlowJson.Check(await db.Gateway("release",new{cmd.UserId,cmd.SessionId,jobId=id,cmd.Generation,cancel=true},ct))));
        routes.MapPost("/intents/{id:guid}/result-ticket",async(Guid id,FlowCommand cmd,IFlowDatabase db,ResultTickets tickets,CancellationToken ct)=>{
            var i=await Find(db,id,cmd,ct);
            return Results.Ok(new{jobId=id,resultUrl=options.PublicResultsOrigin.TrimEnd('/')+"/api/v2/results/"+id.ToString("D"),ticket=tickets.Issue(i),expiresIn=300});
        });
        routes.MapPost("/scale",async(ScaleRequest cmd,Coordinator c,Store store,CancellationToken ct)=>{
            if(!options.GatewayAutoScale)return Results.Ok(new{enabled=false});
            var count=c.Workers.Count(w=>!w.Draining);
            if(cmd.DesiredWorkers<0||cmd.DesiredWorkers>256)throw new V2Exception(400,"invalid_worker_target");
            // Desired target is idempotent, hardware admission remains in AddWorker.
            if(cmd.DesiredWorkers>count&&c.Ready){
                try{await c.EnsureWorkers(cmd.DesiredWorkers,ct);}catch(InvalidOperationException){return Results.Ok(new{capacityLimited=true,workers=c.Workers.Count});}
                await store.RecordAudit("raspberry","workers.ensure",cmd.DesiredWorkers.ToString());
            }
            return Results.Ok(new{workers=c.Workers.Count});
        });
        routes.MapPost("/capacity",(Coordinator c)=>Results.Ok(new{workers=c.Workers.Count(w=>!w.Draining),queued=c.Queued,ready=c.Ready}));
        // The only v2 client route on compute is read-only. A Google/API key
        // cannot create work here, and no ticket travels in the URL.
        app.MapGet("/api/v2/results/{id:guid}",async(Guid id,int? wait,HttpContext ctx,ResultTickets tickets,IFlowDatabase db,Store store,Coordinator c,CancellationToken ct)=>{
            if(!await resultReaders.WaitAsync(0,ct))throw new V2Exception(429,"result_capacity");
            try{
            if(!ctx.Request.IsHttps&&ctx.Connection.RemoteIpAddress is {} ip&&!System.Net.IPAddress.IsLoopback(ip))throw new V2Exception(426,"https_required");
            var header=ctx.Request.Headers.Authorization.ToString();
            if(!header.StartsWith("Bearer ",StringComparison.Ordinal))throw new V2Exception(401,"result_ticket_required");
            var access=tickets.Read(header[7..],id);
            // Revalidate owner, current session and ban, including after a long-poll.
            await Find(db,id,new(access.UserId,access.SessionId),ct);
            var job=await store.Find(id.ToString("D"),access.ClientId);
            if(job is {State:"queued" or "running"}&&wait>0){
                await c.WaitForResult(job.Id,Math.Min(wait.Value,10),ct);
                tickets.Read(header[7..],id);await Find(db,id,new(access.UserId,access.SessionId),ct);
                job=await store.Find(job.Id,access.ClientId);
            }
            return job==null?Results.Json(new{id,state="awaiting_upload"}):Results.Ok(new{job.Id,job.State,job.Text,job.Error,job.Width,job.Height,job.QueueMs,job.InferenceMs,job.TotalMs});
            }finally{resultReaders.Release();}
        });
    }
    private static FlowCommand HeaderCommand(HttpContext ctx)
    {
        if(!Guid.TryParse(ctx.Request.Headers["X-OCR-User"],out var user)||!Guid.TryParse(ctx.Request.Headers["X-OCR-Session"],out var session)||!long.TryParse(ctx.Request.Headers["X-OCR-Generation"],out var generation))throw new V2Exception(400,"upload_identity_required");
        return new(user,session,generation);
    }
    private static async Task<FlowIntent> Find(IFlowDatabase db,Guid id,FlowCommand cmd,CancellationToken ct)=>
        FlowJson.Intent(FlowJson.Check(await db.Gateway("get",new{cmd.UserId,cmd.SessionId,jobId=id},ct)),new(cmd.UserId,cmd.SessionId));
}
public sealed record ScaleRequest(int DesiredWorkers);
