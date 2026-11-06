using System.Net.Http.Headers;
using System.Text.Json;
namespace VietOcr.Server;

// Auth server validates JWTs, including projects with legacy symmetric signing keys.
public sealed class GoogleAccounts(ServerOptions options,Store store) : IDisposable
{
    private readonly HttpClient http=new(){Timeout=TimeSpan.FromSeconds(12)};
    public async Task<ApiClient?> Authenticate(string accessToken,CancellationToken ct)
    {
        using var request=new HttpRequestMessage(HttpMethod.Get,options.SupabaseUrl.TrimEnd('/')+"/auth/v1/user");
        request.Headers.Add("apikey",options.SupabasePublishableKey);
        request.Headers.Authorization=new AuthenticationHeaderValue("Bearer",accessToken);
        HttpResponseMessage response;
        try {response=await http.SendAsync(request,ct);}
        catch(HttpRequestException){throw new DatabaseUnavailableException("Supabase Auth unreachable.");}
        catch(TaskCanceledException) when(!ct.IsCancellationRequested){throw new DatabaseUnavailableException("Supabase Auth timeout.");}
        using var ownedResponse=response;
        if((int)response.StatusCode is 401 or 403)return null;
        if(!response.IsSuccessStatusCode)throw new DatabaseUnavailableException("Supabase Auth is unavailable.");
        using var document=await JsonDocument.ParseAsync(await response.Content.ReadAsStreamAsync(ct),cancellationToken:ct);
        var user=document.RootElement;
        if(!user.TryGetProperty("email_confirmed_at",out var confirmed)||confirmed.ValueKind!=JsonValueKind.String||
           !user.TryGetProperty("identities",out var identities)||!identities.EnumerateArray().Any(x=>x.GetProperty("provider").GetString()=="google")||
           !user.TryGetProperty("id",out var id)||!Guid.TryParse(id.GetString(),out _)||
           !user.TryGetProperty("email",out var email)||string.IsNullOrWhiteSpace(email.GetString()))return null;
        var client=await store.GoogleUser(id.GetString()!,email.GetString()!);
        return client;
    }
    public void Dispose()=>http.Dispose();
}
