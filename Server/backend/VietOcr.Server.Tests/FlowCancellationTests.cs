using System.Text.Json;
using VietOcr.Server;
using Xunit;
namespace VietOcr.Server.Tests;

public sealed class FlowCancellationTests
{
    private readonly FlowIntent intent=new(Guid.NewGuid(),Guid.NewGuid(),Guid.NewGuid(),
        "owner","uploading",new string('a',64),1024,"image/jpeg","auto",1,7);

    [Fact] public async Task UnacceptedCancellationReleasesTheCurrentLeaseInsteadOfDefaultGenerationZero()
    {
        var db=new Db();
        var result=await FlowCancellation.Apply(intent,db,()=>Task.FromResult<Job?>(null),
            _=>throw new InvalidOperationException("No accepted job"),default);
        Assert.Equal(new FlowCancellationResult("cancelled",false),result);
        var call=Assert.Single(db.Calls);Assert.Equal("release",call.Action);
        Assert.Equal(7,call.Body.GetProperty("generation").GetInt64());
        Assert.True(call.Body.GetProperty("cancel").GetBoolean());
        Assert.Equal(intent.UserId,call.Body.GetProperty("userId").GetGuid());
    }

    [Theory][InlineData("queued")][InlineData("running")]
    public async Task AcceptedJobStopsWithoutRefundingOrRechargingQuota(string state)
    {
        var db=new Db();var job=Job(state);var stops=0;
        var result=await FlowCancellation.Apply(intent with{State=state},db,
            ()=>Task.FromResult<Job?>(job),j=>{stops++;job=j with{State="cancelled"};return Task.CompletedTask;},default);
        Assert.Equal(1,stops);Assert.Equal(new FlowCancellationResult("cancelled",true),result);
        Assert.Empty(db.Calls);
    }

    [Theory][InlineData("succeeded")][InlineData("failed")][InlineData("cancelled")]
    public async Task FinishedJobKeepsItsRealResultWhenStopArrivesLate(string state)
    {
        var db=new Db();
        var result=await FlowCancellation.Apply(intent,db,()=>Task.FromResult<Job?>(Job(state)),
            _=>throw new InvalidOperationException("Already finished"),default);
        Assert.Equal(new FlowCancellationResult(state,true),result);Assert.Empty(db.Calls);
    }

    [Fact] public async Task PurgedAcceptedJobCannotBecomeAnUnacceptedRefund()
    {
        var db=new Db();
        var error=await Assert.ThrowsAsync<V2Exception>(()=>FlowCancellation.Apply(intent with{State="succeeded"},db,
            ()=>Task.FromResult<Job?>(null),_=>Task.CompletedTask,default));
        Assert.Equal(410,error.Status);Assert.Empty(db.Calls);
    }

    private Job Job(string state)=>new(intent.Id.ToString("D"),intent.ClientId,"Owner",null,intent.Sha256,
        "auto",state,intent.ImageBytes,DateTime.UtcNow,Text:state=="succeeded"?"Preserved text":null);
    private sealed class Db:IFlowDatabase
    {
        public List<(string Action,JsonElement Body)> Calls {get;}=[];
        public Task<JsonElement> Gateway(string action,object body,CancellationToken ct=default)
        {
            Calls.Add((action,JsonSerializer.SerializeToElement(body,FlowJson.Options)));
            return Task.FromResult(JsonSerializer.SerializeToElement(new{released=true}));
        }
        public Task<JsonElement> Commit(FlowIntent i,CancellationToken ct=default)=>
            throw new InvalidOperationException("Cancellation must never create a quota charge");
    }
}
