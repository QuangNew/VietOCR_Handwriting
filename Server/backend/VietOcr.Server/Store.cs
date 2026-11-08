using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;

namespace VietOcr.Server;

public sealed class DatabaseUnavailableException(string message) : Exception(message);

// Atomic quota/admission/idempotency lives in Postgres, not in-memory counters.
public sealed class Store : IAsyncDisposable
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private readonly ServerOptions options;
    private readonly HttpClient http = new() { Timeout = TimeSpan.FromSeconds(15) };
    private readonly string owner = Guid.NewGuid().ToString("N");
    private bool leased;
    public bool Ready { get; private set; }
    public string? Error { get; private set; }
    public Store(ServerOptions options)
    {
        this.options=options;
        if (!Uri.TryCreate(options.SupabaseUrl,UriKind.Absolute,out var url) || url.Scheme!="https" || !url.Host.EndsWith(".supabase.co",StringComparison.Ordinal))
            throw new InvalidOperationException("Configure an HTTPS Supabase project URL in server.local.json.");
        http.BaseAddress=new Uri(options.SupabaseUrl.TrimEnd('/')+"/rest/v1/");
        http.DefaultRequestHeaders.Add("apikey",options.SupabaseServiceKey);
        if (options.SupabaseServiceKey.StartsWith("eyJ"))
            http.DefaultRequestHeaders.Authorization=new AuthenticationHeaderValue("Bearer",options.SupabaseServiceKey);
    }
    public async Task<JsonElement> Rpc(string action, object? p=null, CancellationToken ct=default)
    {
        try {
            using var response=await http.PostAsJsonAsync("rpc/ocr_backend",new { action,p=p??new{} },Json,ct);
            if(!response.IsSuccessStatusCode) {
                Error=$"Supabase RPC HTTP {(int)response.StatusCode}";
                throw new DatabaseUnavailableException(Error+". Check migration and server credentials.");
            }
            var value=await response.Content.ReadFromJsonAsync<JsonElement>(Json,ct);
            Error=null;return value;
        } catch(HttpRequestException) { Error="Supabase unreachable";throw new DatabaseUnavailableException(Error); }
        catch(TaskCanceledException) when(!ct.IsCancellationRequested) { Error="Supabase timeout";throw new DatabaseUnavailableException(Error); }
    }
    private async Task<T?> Call<T>(string action,object? p=null,CancellationToken ct=default) =>
        (await Rpc(action,p,ct)).Deserialize<T>(Json);
    public async Task Initialize(CancellationToken ct=default,bool coordinator=true)
    {
        Ready=false;
        // Readiness gate, once per coordinator initialization, not one extra DB call per photo.
        try
        {
            using var policy=await http.PostAsJsonAsync("rpc/ocr_policy_version",new{},Json,ct);
            if(!policy.IsSuccessStatusCode)
                throw new DatabaseUnavailableException("Apply the 20261109 Supabase policy migration before starting this server build.");
            AccountPolicy.RequireDatabasePolicy(await policy.Content.ReadFromJsonAsync<JsonElement>(Json,ct));
        }
        catch(HttpRequestException){Error="Supabase unavailable during policy check";throw new DatabaseUnavailableException(Error);}
        catch(TaskCanceledException)when(!ct.IsCancellationRequested){Error="Supabase policy check timed out";throw new DatabaseUnavailableException(Error);}
        await Settings(ct);
        if(coordinator) {
            var value=await Rpc("lease",new{owner},ct);
            if(!value.GetProperty("alive").GetBoolean())throw new InvalidOperationException("Another VietOCR coordinator owns this database. Stop it before starting another.");
            leased=true;
        }
        Ready=true;Error=null;
    }
    public async Task<bool> Ping(CancellationToken ct)
    {
        return (await Rpc("ping",new{owner},ct)).GetProperty("alive").GetBoolean();
    }
    public Task<AdminUser?> Admin(string username)=>Call<AdminUser>("admin",new{username});
    public async Task CreateAdmin(string username,string password)
    {
        if(username.Length is <3 or >64)throw new ArgumentException("Username length: 3–64.");
        await Rpc("createAdmin",new{id=Guid.NewGuid().ToString("N"),username,hash=Secrets.PasswordHash(password)});
    }
    public Task ChangePassword(string id,string password)=>Rpc("password",new{id,hash=Secrets.PasswordHash(password)});
    public Task<ApiClient?> Authenticate(string token)=>Call<ApiClient>("authenticate",new{hash=Secrets.Hash(token)});
    public async Task<ApiClient> GoogleUser(string userId,string email)=>(await Call<ApiClient>("googleUser",new{userId,email}))!;
    public async Task<List<ApiClient>> Clients()=>(await Call<List<ApiClient>>("clients"))!;
    public static void ValidateClient(string name,int rate,int daily)
    {
        if(string.IsNullOrWhiteSpace(name)||name.Trim().Length>80||rate is <1 or >AccountPolicy.MinuteRequestCap||daily is <1 or >AccountPolicy.DailyImageCap)
            throw new ArgumentException("Tên: 1–80 ký tự; hạn mức: 1–30 request/phút và 1–500 ảnh/ngày.");
    }
    public async Task<(ApiClient Client,string Key)> CreateClient(NewClient request,string actor="system")
    {
        ValidateClient(request.Name,request.RatePerMinute,request.DailyLimit);
        var key="voc_"+Secrets.Token();
        var c=await Call<ApiClient>("createClient",new{id=Guid.NewGuid().ToString("N"),name=request.Name.Trim(),prefix=key[..12],
            hash=Secrets.Hash(key),request.RatePerMinute,request.DailyLimit,actor});return(c!,key);
    }
    public async Task<ApiClient> UpdateClient(string id,UpdateClient request,string actor)
    {
        ValidateClient(request.Name,request.RatePerMinute,request.DailyLimit);
        if(!(await Clients()).Any(c=>c.Id==id))throw new KeyNotFoundException();
        return (await Call<ApiClient>("updateClient",new{id,name=request.Name.Trim(),request.RatePerMinute,request.DailyLimit,request.Enabled,actor}))!;
    }
    public async Task<(ApiClient Client,string Key)> Rotate(string id,string actor)
    {
        var existing=(await Clients()).FirstOrDefault(c=>c.Id==id)??throw new KeyNotFoundException();
        if(existing.UserId!=null)throw new ArgumentException("Định danh Google là cố định. Dùng khoá/mở tài khoản để quản lý.");
        var key="voc_"+Secrets.Token();
        return((await Call<ApiClient>("rotateClient",new{id,prefix=key[..12],hash=Secrets.Hash(key),actor}))!,key);
    }
    public Task Revoke(string id,string actor="system")=>Rpc("revoke",new{id,actor});
    public Task<Job?> Find(string id,string? client=null,string? idempotency=null)=>Call<Job>("find",new{id,client,idem=idempotency});
    public async Task<List<Job>> Jobs(int limit=100,bool pending=false,string? client=null)=>(await Call<List<Job>>("jobs",new{limit,pending,client}))!;
    public Task<JsonElement> Admit(Job job)=>Rpc("admit",job);
    public Task<JsonElement> Usage(string id)=>Rpc("usage",new{id});
    public async Task<Job> Start(Job job,string worker)=>await Call<Job>("start",new{id=job.Id,worker})??throw new OperationCanceledException();
    public Task Finish(Job job,string state,string? text=null,string? error=null,double? elapsed=null,int width=0,int height=0)=>
        Rpc("finish",new{id=job.Id,state,text,error,elapsed,width,height});
    public Task Requeue(string id)=>Rpc("requeue",new{id});
    public Task Cleanup()=>Rpc("cleanup",new{hours=options.RetentionHours});
    public async Task<List<Job>> Window(DateTime since)=>(await Call<List<Job>>("window",new{since}))!;
    public async Task<WindowTotals> Totals(DateTime since)=>(await Call<WindowTotals>("totals",new{since}))!;
    public async Task<RuntimeSettings> Settings(CancellationToken ct=default)
    {
        var settings=(await Call<RuntimeSettings>("settings",ct:ct))!;
        // Forward-compatible startup while an operator is applying the additive 500/30 migration.
        // The database migration remains necessary for atomic quota enforcement on existing accounts.
        return settings with {DefaultDailyLimit=Math.Min(AccountPolicy.DailyImageCap,settings.DefaultDailyLimit),
            DefaultRatePerMinute=Math.Min(AccountPolicy.MinuteRequestCap,settings.DefaultRatePerMinute)};
    }
    public Task SaveSettings(RuntimeSettings value,string actor)=>Rpc("saveSettings",new{value,actor});
    public Task<JsonElement> Audit()=>Rpc("audit");
    public Task RecordAudit(string actor,string action,string? id=null)=>Rpc("recordAudit",new{actor,name=action,id});
    public async ValueTask DisposeAsync()
    {
        if(leased){try{await Rpc("release",new{owner});}catch{}leased=false;}
        http.Dispose();
    }
}
public sealed record WindowTotals(int Completed,int Failed,int Cancelled,int Matched,int PerMinute,double? InferenceMs,double? QueueMs);
