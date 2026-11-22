using System.Text.Json;
using VietOcr.Server;
using Xunit;

namespace VietOcr.Server.Tests;
public class ServerLoadTests
{
    [Fact]public void CpuUsesHostTimeDeltasAndDoesNotInventTheFirstSample()
    {
        var cpu=new CpuLoadSampler();Assert.Null(cpu.Observe(100,1000));
        Assert.Equal(85,cpu.Observe(115,1100));Assert.Null(cpu.Observe(115,1100));
        Assert.Null(cpu.Observe(1,2));Assert.Null(cpu.Observe(500,100));
    }
    [Fact]public async Task WindowsHostSamplerActuallyCallsTheSystemApi()
    {
        if(!OperatingSystem.IsWindows())return;
        var cpu=new CpuLoadSampler();Assert.Null(cpu.Sample());await Task.Delay(80);
        var value=cpu.Sample();Assert.NotNull(value);Assert.InRange(value.Value,0,100);
    }
    [Fact]public void MachineCredentialIsSeparateFromAdminOrClientAuth()
    {
        var token="random_test_credential_at_least_32_chars";var hash=Secrets.Hash(token);
        Assert.True(GatewayTelemetryCredential.Validate("Bearer "+token,hash));
        Assert.False(GatewayTelemetryCredential.Validate("Bearer "+token+"x",hash));
        Assert.False(GatewayTelemetryCredential.Validate("Bearer voc_short",hash));
        Assert.False(GatewayTelemetryCredential.Validate("",hash));
        Assert.False(GatewayTelemetryCredential.Validate("Bearer "+token,"not-a-hex-hash"));
    }
    [Fact]public void SharedPolicyAndDefaultAccountConfigurationAgree()
    {
        var policy=JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory,"policy.json"))).RootElement;
        Assert.Equal(AccountPolicy.DailyImageCap,policy.GetProperty("dailyImageCap").GetInt32());
        Assert.Equal(AccountPolicy.MinuteRequestCap,policy.GetProperty("minuteRequestCap").GetInt32());
        Assert.Equal(500,new NewClient("example").DailyLimit);Assert.Equal(30,new NewClient("example").RatePerMinute);
        Store.ValidateClient("lower account",5,50);
    }
    [Fact]public void OldDatabasePolicyCannotAdvertiseReadinessAndSilentlyAdmitOverTheNewCaps()
    {
        using var valid=JsonDocument.Parse("{\"policyVersion\":2,\"dailyImageCap\":500,\"minuteRequestCap\":30}");
        AccountPolicy.RequireDatabasePolicy(valid.RootElement);
        using var old=JsonDocument.Parse("{\"policyVersion\":1,\"dailyImageCap\":1000,\"minuteRequestCap\":60}");
        Assert.Throws<DatabaseUnavailableException>(()=>AccountPolicy.RequireDatabasePolicy(old.RootElement));
        using var missing=JsonDocument.Parse("{}");
        Assert.Throws<DatabaseUnavailableException>(()=>AccountPolicy.RequireDatabasePolicy(missing.RootElement));
    }
    [Fact]public void WorkerMetricsDeserializesBartphoRamAndDefaultsCleanly()
    {
        var opts=new JsonSerializerOptions(JsonSerializerDefaults.Web);
        var legacy=JsonSerializer.Deserialize<WorkerMetrics>("{\"ramMiB\":900,\"reservedMiB\":200}",opts)!;
        Assert.Equal(900,legacy.RamMiB);Assert.False(legacy.BartphoLoaded);
        Assert.Equal(0,legacy.BartphoRamMiB);Assert.Equal(0,legacy.BartphoRamPercent);Assert.Null(legacy.BartphoDevice);
        var loaded=JsonSerializer.Deserialize<WorkerMetrics>(
            "{\"ramMiB\":1450,\"bartphoLoaded\":true,\"bartphoRamMiB\":412.5,\"bartphoRamPercent\":2.58,\"bartphoVramMiB\":760.3,\"bartphoDevice\":\"cuda:0\"}",opts)!;
        Assert.True(loaded.BartphoLoaded);Assert.Equal(412.5,loaded.BartphoRamMiB);
        Assert.Equal(2.58,loaded.BartphoRamPercent);Assert.Equal(760.3,loaded.BartphoVramMiB);
        Assert.Equal("cuda:0",loaded.BartphoDevice);
    }
}
