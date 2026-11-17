using VietOcr.Server;
using Xunit;

namespace VietOcr.Server.Tests;
public class ConfigurationTests
{
    [Fact] public void AccountCapsCannotBeRaisedPastUserPolicy()
    {
        Assert.Throws<ArgumentException>(()=>Store.ValidateClient("test",31,500));
        Assert.Throws<ArgumentException>(()=>Store.ValidateClient("test",30,501));
        Assert.Throws<ArgumentException>(()=>new RuntimeSettings(DefaultDailyLimit:501).Validate());
        Assert.Throws<ArgumentException>(()=>new RuntimeSettings(DefaultRatePerMinute:31).Validate());
    }
    [Fact] public void ResourceConfigurationCannotDisableMemoryReserves()
    {
        Assert.Throws<ArgumentException>(()=>new RuntimeSettings(ReserveVramMiB:0).Validate());
        Assert.Throws<ArgumentException>(()=>new RuntimeSettings(ReserveRamMiB:0).Validate());
        Assert.Throws<ArgumentException>(()=>new RuntimeSettings(QueueCapacity:10,PerClientPending:11).Validate());
    }
    [Fact] public void ApplyChangesActualRuntimePolicy()
    {
        var options=new ServerOptions();
        new RuntimeSettings(AcceptingRequests:false,DispatchPaused:true,QueueCapacity:50,PerClientPending:10,JobTimeoutSeconds:45).Apply(options);
        Assert.False(options.AcceptingRequests);Assert.True(options.DispatchPaused);
        Assert.Equal(50,options.QueueCapacity);Assert.Equal(45,options.JobTimeoutSeconds);
    }
}
