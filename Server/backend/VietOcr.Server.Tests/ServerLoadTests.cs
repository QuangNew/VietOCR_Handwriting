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
}
