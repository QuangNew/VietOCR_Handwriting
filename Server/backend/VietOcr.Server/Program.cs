using System.Diagnostics;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text.Json;
using System.Threading.RateLimiting;
using Microsoft.AspNetCore.Antiforgery;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.Http.Features;
using VietOcr.Server;

var root = ServerOptions.FindRoot();
var builder = WebApplication.CreateBuilder(args);
builder.Configuration.AddJsonFile(Path.Combine(root,"backend/VietOcr.Server/appsettings.json"),optional:false)
    .AddJsonFile(Path.Combine(root,"server.local.json"), optional:true, reloadOnChange:false).AddEnvironmentVariables();
var options = builder.Configuration.GetSection("Server").Get<ServerOptions>() ?? new(); options.Root = root;
if (options.WorkerBudgetMiB < 100 || options.ReserveVramMiB < 512 || options.QueueCapacity < 1 || options.InitialWorkers < 0 ||
    options.RetentionHours is < 1 or > 720 || options.JobTimeoutSeconds is < 5 or > 600 || options.MaxUploadMiB is < 1 or > 64 ||
    options.ReserveRamMiB<512 || options.MaxPixels is < 1 or > 40000000 || options.SpoolMiB<options.MaxUploadMiB ||
    options.PerClientPending<1 || options.ConcurrentUploads is < 1 or > 32 || !System.Text.RegularExpressions.Regex.IsMatch(options.Device,"^(auto|cpu|integrated|cuda(:[0-9]+)?|directml:[0-9]+)$"))
    throw new InvalidOperationException("Invalid resource limits in Server configuration.");
Directory.CreateDirectory(options.Runtime);
if (args.Contains("--create-admin"))
{
    await using var store = new Store(options); await store.Initialize(coordinator:false);
    Console.Write("Admin username: "); var username = Console.ReadLine() ?? "";
    Console.Write("Admin password (12+ characters, hidden): ");
    var password = new System.Text.StringBuilder();
    if (Console.IsInputRedirected) password.Append(Console.ReadLine());
    else while (true) { var key = Console.ReadKey(true); if (key.Key == ConsoleKey.Enter) break;
        if (key.Key == ConsoleKey.Backspace) { if (password.Length > 0) password.Length--; }
        else if (!char.IsControl(key.KeyChar)) password.Append(key.KeyChar); }
    Console.WriteLine(); await store.CreateAdmin(username.Trim(), password.ToString());
    Console.WriteLine("Administrator created. No public registration endpoint is enabled."); return;
}
builder.WebHost.ConfigureKestrel(k => { k.Limits.MaxRequestBodySize = 65L*1048576;
    k.Limits.MaxConcurrentConnections=128;k.AddServerHeader = false; });
builder.Services.Configure<FormOptions>(f => { f.MultipartBodyLengthLimit = 64*1048576L;
    f.MemoryBufferThreshold = 64*1024; });
builder.Services.AddSingleton(options); builder.Services.AddSingleton<Store>(); builder.Services.AddSingleton<Hardware>();
builder.Services.AddSingleton<Coordinator>(); builder.Services.AddHostedService(p => p.GetRequiredService<Coordinator>());
builder.Services.AddSingleton<Metrics>();
builder.Services.AddSingleton<GoogleAccounts>();
var protection=builder.Services.AddDataProtection().PersistKeysToFileSystem(new DirectoryInfo(Path.Combine(options.Runtime,"keys")))
    .SetApplicationName("VietOCR.Control");
if(OperatingSystem.IsWindows()) protection.ProtectKeysWithDpapi();
builder.Services.AddAuthentication(CookieAuthenticationDefaults.AuthenticationScheme).AddCookie(c => {
    c.Cookie.Name = "vietocr.admin"; c.Cookie.HttpOnly = true; c.Cookie.SameSite = SameSiteMode.Strict;
    c.Cookie.SecurePolicy = CookieSecurePolicy.SameAsRequest; c.ExpireTimeSpan = TimeSpan.FromHours(8); c.SlidingExpiration = true;
    c.Events.OnRedirectToLogin = ctx => { ctx.Response.StatusCode=401; return Task.CompletedTask; };
    c.Events.OnRedirectToAccessDenied = ctx => { ctx.Response.StatusCode=403; return Task.CompletedTask; };
    c.Events.OnValidatePrincipal=async ctx=>{
        var user=await ctx.HttpContext.RequestServices.GetRequiredService<Store>().Admin(ctx.Principal?.Identity?.Name??"");
        if(user==null || ctx.Principal?.FindFirstValue("password_version")!=Secrets.Hash(user.PasswordHash))
            ctx.RejectPrincipal();
    };
});
builder.Services.AddAuthorization();
builder.Services.AddAntiforgery(a => { a.HeaderName="X-CSRF-TOKEN"; a.Cookie.Name="vietocr.csrf"; a.Cookie.SameSite=SameSiteMode.Strict; });
builder.Services.AddRateLimiter(r => {
    r.RejectionStatusCode=429;
    r.OnRejected = async (ctx,ct) => { ctx.HttpContext.Response.Headers.RetryAfter="10";
        await ctx.HttpContext.Response.WriteAsJsonAsync(new { error="rate_limit",message="Too many requests; retry later." },ct); };
    r.AddPolicy("login", ctx => RateLimitPartition.GetFixedWindowLimiter(ctx.Connection.RemoteIpAddress?.ToString()??"local",
        _ => new FixedWindowRateLimiterOptions { PermitLimit=5,Window=TimeSpan.FromMinutes(1),QueueLimit=0 }));
    r.AddPolicy("client", ctx => RateLimitPartition.GetFixedWindowLimiter((ctx.Items["client"] as ApiClient)?.Id ?? "unknown",
        _ => new FixedWindowRateLimiterOptions { PermitLimit=(ctx.Items["client"] as ApiClient)?.RatePerMinute ?? 5,
            Window=TimeSpan.FromMinutes(1),QueueLimit=0 }));
    r.AddPolicy("poll",ctx=>RateLimitPartition.GetFixedWindowLimiter((ctx.Items["client"] as ApiClient)?.Id??"unknown",
        _=>new FixedWindowRateLimiterOptions { PermitLimit=600,Window=TimeSpan.FromMinutes(1),QueueLimit=0 }));
});
var app = builder.Build();
app.Use(async (ctx,next) => {
    ctx.Response.Headers.XContentTypeOptions="nosniff"; ctx.Response.Headers.CacheControl="no-store";
    var started=Stopwatch.GetTimestamp();
    try { await next(); }
    catch (AntiforgeryValidationException) { ctx.Response.StatusCode=400; await ctx.Response.WriteAsJsonAsync(new { error="csrf",message="Refresh the page and retry." }); }
    catch (DatabaseUnavailableException) { ctx.Response.StatusCode=503; await ctx.Response.WriteAsJsonAsync(new { error="database_unavailable",message="Supabase chưa sẵn sàng. Kiểm tra kết nối và cấu hình server." }); }
    catch (BadHttpRequestException e) { ctx.Response.StatusCode=e.StatusCode; await ctx.Response.WriteAsJsonAsync(new { error="invalid_request",message="Invalid or oversized request." }); }
    catch (ArgumentException e) { ctx.Response.StatusCode=400; await ctx.Response.WriteAsJsonAsync(new { error="invalid_request",message=e.Message }); }
    catch (KeyNotFoundException) { ctx.Response.StatusCode=404; }
    catch (InvalidOperationException e) { ctx.Response.StatusCode=409; await ctx.Response.WriteAsJsonAsync(new { error="conflict",message=e.Message }); }
    catch (OperationCanceledException) when (ctx.RequestAborted.IsCancellationRequested) { }
    catch (Exception e) { app.Logger.LogError("Request failed ({Type}); trace {Trace}",e.GetType().Name,ctx.TraceIdentifier);
        ctx.Response.StatusCode=500; await ctx.Response.WriteAsJsonAsync(new { error="internal_error",traceId=ctx.TraceIdentifier }); }
    finally { if(ctx.Request.Path.StartsWithSegments("/api/v1")) ctx.RequestServices.GetRequiredService<Metrics>()
        .Response(Stopwatch.GetElapsedTime(started).TotalMilliseconds,ctx.Response.StatusCode); }
});
app.UseAuthentication(); app.UseAuthorization();
app.Use(async (ctx,next) => {
    if (ctx.Request.Path.StartsWithSegments("/api/v1"))
    {
        if (!ctx.Request.IsHttps && !options.AllowInsecureLan && ctx.Connection.RemoteIpAddress is { } ip && !System.Net.IPAddress.IsLoopback(ip))
        { ctx.Response.StatusCode=426; await ctx.Response.WriteAsJsonAsync(new { error="https_required" }); return; }
        var header=ctx.Request.Headers.Authorization.ToString();
        if (!header.StartsWith("Bearer ",StringComparison.Ordinal) || header.Length is < 20 or > 8192)
        { ctx.Response.StatusCode=401; return; }
        var token=header[7..];
        var client=token.StartsWith("voc_",StringComparison.Ordinal)
            ? await ctx.RequestServices.GetRequiredService<Store>().Authenticate(token)
            : await ctx.RequestServices.GetRequiredService<GoogleAccounts>().Authenticate(token,ctx.RequestAborted);
        if(client==null) { ctx.Response.StatusCode=401; return; }
        if(!client.Enabled){ctx.Response.StatusCode=403;await ctx.Response.WriteAsJsonAsync(new{error="account_disabled",message="Tài khoản OCR đã bị khoá. Liên hệ quản trị viên."});return;}
        ctx.Items["client"]=client;
    }
    if (ctx.Request.Path.StartsWithSegments("/api/admin") && ctx.Request.Method is not ("GET" or "HEAD" or "OPTIONS"))
        await ctx.RequestServices.GetRequiredService<IAntiforgery>().ValidateRequestAsync(ctx);
    await next();
});
app.UseRateLimiter();
app.MapGet("/api/health/live",() => Results.Ok(new { status="alive" }));
app.MapGet("/api/public/config",()=>Results.Ok(new {supabaseUrl=options.SupabaseUrl,
    publishableKey=options.SupabasePublishableKey,authProvider="google",ocrMode="server-only",
    androidRedirect="vn.pbl4.vietocr://auth/callback",desktopRedirect="http://127.0.0.1:47821/auth/callback",
    dailyLimit=1000,ratePerMinute=60,quotaTimezone="Asia/Ho_Chi_Minh"}));
app.MapGet("/api/health/ready",(Coordinator c) => c.Ready && c.Workers.Any(w=>w.State is "idle" or "busy")
    ? Results.Ok(new { status="ready" }) : Results.Json(new { status="not_ready" },statusCode:503));
app.MapGet("/api/admin/auth/csrf",(HttpContext ctx,IAntiforgery csrf) => Results.Ok(new { token=csrf.GetAndStoreTokens(ctx).RequestToken }));
app.MapPost("/api/admin/auth/login",async (LoginRequest request,HttpContext ctx,Store store) => {
    if(string.IsNullOrEmpty(request.Username) || string.IsNullOrEmpty(request.Password) || request.Username.Length>64 || request.Password.Length>1024) return Results.Unauthorized();
    var admin=await store.Admin(request.Username.Trim());
    // Perform PBKDF2 even for unknown users to avoid a cheap username oracle.
    var dummy="pbkdf2-sha256:600000:AAAAAAAAAAAAAAAAAAAAAA==:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
    var valid=Secrets.VerifyPassword(request.Password,admin?.PasswordHash??dummy);
    if(admin==null || !valid) return Results.Unauthorized();
    var identity=new ClaimsIdentity([new(ClaimTypes.NameIdentifier,admin.Id),new(ClaimTypes.Name,admin.Username),new(ClaimTypes.Role,"admin"),
        new("password_version",Secrets.Hash(admin.PasswordHash))],
        CookieAuthenticationDefaults.AuthenticationScheme);
    await ctx.SignInAsync(CookieAuthenticationDefaults.AuthenticationScheme,new ClaimsPrincipal(identity));
    return Results.Ok(new { admin.Username });
}).RequireRateLimiting("login");
app.MapGet("/api/admin/auth/me",(HttpContext ctx) => Results.Ok(new { username=ctx.User.Identity!.Name })).RequireAuthorization();
app.MapPost("/api/admin/auth/logout",async (HttpContext ctx) => { await ctx.SignOutAsync(); return Results.NoContent(); }).RequireAuthorization();
var adminRoutes=app.MapGroup("/api/admin").RequireAuthorization();
adminRoutes.MapPost("/auth/password",async(ChangePasswordRequest request,HttpContext ctx,Store store)=>{
    if(string.IsNullOrEmpty(request.CurrentPassword)||string.IsNullOrEmpty(request.NewPassword)||request.NewPassword.Length>1024)
        return Results.BadRequest(new{message="Mật khẩu mới cần ít nhất 12 ký tự."});
    var user=await store.Admin(ctx.User.Identity!.Name!);
    if(user==null || !Secrets.VerifyPassword(request.CurrentPassword,user.PasswordHash))return Results.BadRequest(new{message="Mật khẩu hiện tại chưa đúng."});
    await store.ChangePassword(user.Id,request.NewPassword);await ctx.SignOutAsync();
    return Results.NoContent();
}).RequireRateLimiting("login");
adminRoutes.MapGet("/snapshot",async (Metrics metrics) => Results.Ok(await metrics.Snapshot()));
adminRoutes.MapGet("/workers",(Coordinator c)=>Results.Ok(c.Workers));
adminRoutes.MapGet("/devices",async(Hardware h,HttpContext ctx)=>Results.Ok(await h.Devices(ctx.RequestAborted)));
adminRoutes.MapPost("/workers",async (NewWorker? request,Coordinator c,HttpContext ctx,Store store)=>{var worker=await c.AddWorker(ctx.RequestAborted,request?.Device??"auto");
    await store.RecordAudit(ctx.User.Identity!.Name!,"worker.add",worker.Id);return Results.Ok(worker);});
adminRoutes.MapDelete("/workers/{id}",async (string id,Coordinator c,Store store,HttpContext ctx)=>{ await c.RemoveWorker(id);
    await store.RecordAudit(ctx.User.Identity!.Name!,"worker.drain",id);return Results.Accepted(); });
adminRoutes.MapGet("/clients",async (Store store)=>Results.Ok(await store.Clients()));
adminRoutes.MapPost("/clients",async (NewClient request,Store store,HttpContext ctx)=>{ var created=await store.CreateClient(request,ctx.User.Identity!.Name!); return Results.Ok(new { client=created.Client,key=created.Key }); });
adminRoutes.MapPut("/clients/{id}",async(string id,UpdateClient request,Store store,HttpContext ctx)=>
    Results.Ok(await store.UpdateClient(id,request,ctx.User.Identity!.Name!)));
adminRoutes.MapPost("/clients/{id}/rotate",async(string id,Store store,HttpContext ctx)=>{var v=await store.Rotate(id,ctx.User.Identity!.Name!);return Results.Ok(new{client=v.Client,key=v.Key});});
adminRoutes.MapDelete("/clients/{id}",async (string id,Store store,HttpContext ctx)=>{ await store.Revoke(id,ctx.User.Identity!.Name!); return Results.NoContent(); });
adminRoutes.MapGet("/settings",async(Store store)=>Results.Ok(await store.Settings()));
var settingsLock=new SemaphoreSlim(1,1);
adminRoutes.MapPut("/settings",async(RuntimeSettings value,Store store,HttpContext ctx)=>{
    value.Validate();await settingsLock.WaitAsync(ctx.RequestAborted);
    try{await store.SaveSettings(value,ctx.User.Identity!.Name!);value.Apply(options);return Results.Ok(value);}
    finally{settingsLock.Release();}});
adminRoutes.MapGet("/audit",async(Store store)=>Results.Ok(await store.Audit()));
adminRoutes.MapPost("/queue/cancel-pending",async(Store store,Coordinator c,HttpContext ctx)=>{
    var jobs=await store.Jobs(int.MaxValue,true);var count=0;
    foreach(var job in jobs.Where(j=>j.State=="queued")){await c.Cancel(job);count++;}
    await store.RecordAudit(ctx.User.Identity!.Name!,"queue.cancelPending");return Results.Ok(new{cancelled=count});});
adminRoutes.MapGet("/jobs",async (Store store)=>Results.Ok((await store.Jobs()).Select(PublicJob)));
adminRoutes.MapGet("/jobs/{id}",async(string id,Store store)=> await store.Find(id) is { } job ? Results.Ok(PublicJob(job)):Results.NotFound());
adminRoutes.MapDelete("/jobs/{id}",async (string id,Store store,Coordinator c)=>{
    var job=await store.Find(id); if(job==null)return Results.NotFound(); await c.Cancel(job); return Results.Accepted(); });
var api=app.MapGroup("/api/v1");
api.MapGet("/me",async(HttpContext ctx,Store store)=>Results.Ok(await store.Usage(((ApiClient)ctx.Items["client"]!).Id))).RequireRateLimiting("poll");
api.MapGet("/jobs",async(HttpContext ctx,Store store)=>Results.Ok((await store.Jobs(100,client:((ApiClient)ctx.Items["client"]!).Id)).Select(PublicJob))).RequireRateLimiting("poll");
api.MapGet("/status",(Coordinator c)=>Results.Ok(new{status=c.Ready?"available":"unavailable",readyWorkers=c.Workers.Count(w=>w.State is "idle" or "busy"),queued=c.Queued,model="ML_s44"})).RequireRateLimiting("poll");
api.MapPost("/jobs",async (HttpContext ctx,Store store,Coordinator c)=> {
    if(!c.Ready) return Results.Json(new { error="server_not_ready" },statusCode:503);
    if(!c.Uploads.Wait(0)){ctx.Response.Headers.RetryAfter="3";return Results.Json(new{error="uploads_busy"},statusCode:429);}
    try {
    if(!ctx.Request.HasFormContentType) return Results.BadRequest(new { error="multipart_required" });
    var client=(ApiClient)ctx.Items["client"]!;
    var idem=ctx.Request.Headers["Idempotency-Key"].ToString();
    if(idem.Length>128 || idem.Any(ch=>ch<'!' || ch>'~')) return Results.BadRequest(new { error="invalid_idempotency_key" });
    var form=await ctx.Request.ReadFormAsync(ctx.RequestAborted);
    if(form.Files.Count!=1 || form.Files[0].Name!="image")return Results.BadRequest(new { error="one_image_required" });
    var image=form.Files[0]; var layout=form["layout"].ToString(); if(layout=="")layout="auto";
    if(layout is not ("line" or "auto")) return Results.BadRequest(new { error="invalid_layout" });
    if(image.Length is < 16 || image.Length>options.MaxUploadMiB*1048576L) return Results.BadRequest(new { error="image_size" });
    await c.Admission.WaitAsync(ctx.RequestAborted);
    var id=Guid.NewGuid().ToString("N"); var path=options.ImagePath(id); var retained=false;
    try
    {
        if(!c.Ready)return Results.Json(new{error="coordinator_unavailable",message="Server đang khôi phục kết nối Supabase. Hãy thử lại."},statusCode:503);
        await using(var file=new FileStream(path,FileMode.CreateNew,FileAccess.Write,FileShare.None,65536,true))
            await image.CopyToAsync(file,ctx.RequestAborted);
        string hash;
        await using(var file=File.OpenRead(path))
        {
            var signature=new byte[12]; await file.ReadExactlyAsync(signature,ctx.RequestAborted);
            var valid=signature[0]==0xff && signature[1]==0xd8 && signature[2]==0xff ||
                signature.AsSpan(0,8).SequenceEqual(new byte[]{137,80,78,71,13,10,26,10}) ||
                System.Text.Encoding.ASCII.GetString(signature,0,4)=="RIFF" && System.Text.Encoding.ASCII.GetString(signature,8,4)=="WEBP";
            if(!valid) return Results.BadRequest(new { error="image_format",message="JPEG, PNG, WEBP only." });
            file.Position=0; hash=Convert.ToHexStringLower(await SHA256.HashDataAsync(file,ctx.RequestAborted));
        }
        var job=new Job(id,client.Id,client.Name,idem==""?null:idem,hash,layout,"queued",image.Length,DateTime.UtcNow);
        var admitted=await store.Admit(job);
        if(admitted.TryGetProperty("error",out var admissionError)){
            if(admitted.TryGetProperty("retryAfter",out var retry))ctx.Response.Headers.RetryAfter=retry.ToString();
            return Results.Json(new{error=admissionError.GetString(),message=admissionError.GetString() switch {
                "daily_quota"=>"Đã hết hạn mức OCR hôm nay. Hạn mức đặt lại lúc 00:00 giờ Việt Nam.",
                "minute_quota"=>"Tối đa 60 request trong 60 giây. Hãy chờ rồi thử lại.",
                "maintenance"=>"Server đang tạm ngừng nhận công việc mới.",_=>"Chưa nhận được công việc. Hãy thử lại sau."}},
                statusCode:admitted.GetProperty("status").GetInt32());
        }
        if(admitted.GetProperty("duplicate").GetBoolean())return Results.Ok(PublicJob(admitted.GetProperty("job").Deserialize<Job>(new JsonSerializerOptions(JsonSerializerDefaults.Web))!));
        job=admitted.GetProperty("job").Deserialize<Job>(new JsonSerializerOptions(JsonSerializerDefaults.Web))!;
        retained=true; c.Enqueue(job);
        ctx.Response.Headers.RetryAfter="1"; return Results.Accepted("/api/v1/jobs/"+id,PublicJob(job));
    }
    finally { c.Admission.Release(); if(!retained)File.Delete(path); }
    }finally{c.Uploads.Release();}
}).DisableAntiforgery();
api.MapGet("/jobs/{id}",async (string id,int? wait,HttpContext ctx,Store store,Coordinator c)=>{
    var client=((ApiClient)ctx.Items["client"]!).Id;
    var job=await store.Find(id,client);
    if(job==null)return Results.NotFound();
    if(wait>0 && job.State is "queued" or "running"){
        await c.WaitForResult(id,Math.Min(wait.Value,10),ctx.RequestAborted);
        job=await store.Find(id,client)??job;
    }
    return Results.Ok(PublicJob(job)); }).RequireRateLimiting("poll");
api.MapDelete("/jobs/{id}",async (string id,HttpContext ctx,Store store,Coordinator c)=>{
    var job=await store.Find(id,((ApiClient)ctx.Items["client"]!).Id); if(job==null)return Results.NotFound();
    await c.Cancel(job); return Results.Accepted(); }).RequireRateLimiting("poll");
await app.RunAsync();

static object PublicJob(Job j) => new { j.Id,j.ClientId,j.ClientName,j.Layout,j.State,j.ImageBytes,j.CreatedAt,j.StartedAt,j.FinishedAt,
    j.WorkerId,j.Text,j.Error,j.QueueMs,j.InferenceMs,j.TotalMs,j.Attempts,j.Width,j.Height };
public partial class Program;
