using System.Text.Json;
using System.Security.Cryptography;
using Microsoft.AspNetCore.DataProtection;
using VietOcr.Server;
using Xunit;
namespace VietOcr.Server.Tests;

public sealed class V2FlowTests:IDisposable
{
    private readonly string root=Path.Combine(Path.GetTempPath(),"vietocr-flow-test-"+Guid.NewGuid().ToString("N"));
    private readonly FakeDb db=new();
    private ServerOptions Options=>new(){Root=root,ConcurrentUploads=2};
    private readonly byte[] image=Enumerable.Range(0,300).Select(i=>(byte)i).ToArray();
    private FlowIntent Intent=>new(Guid.Parse("10000000-0000-4000-8000-000000000001"),Guid.NewGuid(),Guid.NewGuid(),"test-account","upload_granted",Convert.ToHexStringLower(SHA256.HashData(image)),image.Length,"image/jpeg","auto",1,1);
    public V2FlowTests(){Directory.CreateDirectory(root);}
    public void Dispose(){if(Path.GetFileName(root).StartsWith("vietocr-flow-test-",StringComparison.Ordinal))Directory.Delete(root,true);}
    private V2Spool Spool=>new(Options,db,new Verifier());
    [Fact]public async Task ResumeChecksOffsetRollsBackPartialChunkAndCommitsOnlyAfterDurableFullFile(){
        var i=Intent;var spool=Spool;
        Assert.Equal(100,await spool.Append(i,0,new MemoryStream(image[..100]),100,default));
        Assert.Equal(0,db.Charges);
        await Assert.ThrowsAsync<V2Exception>(()=>spool.Append(i,0,new MemoryStream(image[..10]),10,default));
        await Assert.ThrowsAsync<V2Exception>(()=>spool.Append(i,100,new MemoryStream(image[100..110]),50,default));
        Assert.Equal(100,await spool.Offset(i,default));
        await Assert.ThrowsAsync<V2Exception>(()=>spool.Complete(i,default));
        await spool.Append(i,100,new MemoryStream(image[100..]),200,default);
        var receipt=await spool.Complete(i,default);Assert.True(receipt.GetProperty("accepted").GetBoolean());
        Assert.Equal(image,await File.ReadAllBytesAsync(Options.ImagePath(i.Id.ToString("D"))));Assert.Equal(1,db.Charges);
        await spool.Complete(i with{State="queued"},default);Assert.Equal(1,db.Charges);
    }
    [Fact]public async Task WrongHashNeverCreatesAJobOrQuotaCharge(){
        var i=Intent with{Sha256=new string('a',64)};var spool=Spool;await spool.Append(i,0,new MemoryStream(image),image.Length,default);
        var error=await Assert.ThrowsAsync<V2Exception>(()=>spool.Complete(i,default));Assert.Equal("image_integrity",error.Code);Assert.Equal(0,db.Charges);
    }
    [Fact]public async Task CancelledUnacceptedIntentCannotBeAcknowledgedAsAccepted(){
        var error=await Assert.ThrowsAsync<V2Exception>(()=>Spool.Complete(Intent with{State="cancelled"},default));
        Assert.Equal("intent_closed",error.Code);Assert.Equal(0,db.Charges);
    }
    [Theory]
    [InlineData("queued")][InlineData("running")][InlineData("succeeded")][InlineData("failed")]
    public void PurgedAcceptedResultIsExpiredInsteadOfLookingLikeANewUpload(string state){
        var error=Assert.Throws<V2Exception>(()=>FlowResultState.WithoutJob(state));
        Assert.Equal(410,error.Status);Assert.Equal("result_expired",error.Code);
    }
    [Theory][InlineData("awaiting_upload")][InlineData("cancelled")]
    public void UnacceptedIntentKeepsItsActualState(string state)=>Assert.Equal(state,FlowResultState.WithoutJob(state));
    [Fact]public async Task RestartRecoversAcceptedImageAfterAmbiguousDatabaseResponseWithoutRecharging(){
        var i=Intent;var spool=Spool;await spool.Append(i,0,new MemoryStream(image),image.Length,default);
        db.FailOnce=true;await Assert.ThrowsAsync<DatabaseUnavailableException>(()=>spool.Complete(i,default));Assert.Equal(1,db.Charges);
        Assert.Single(Directory.EnumerateFiles(Path.Combine(Options.Runtime,"v2-spool"),"*.receipt.json"));
        await Spool.Recover(default);Assert.Equal(1,db.Charges);Assert.Empty(Directory.EnumerateFiles(Path.Combine(Options.Runtime,"v2-spool"),"*.receipt.json"));
    }
    [Fact]public void ResultTicketsAreScopedAuthenticatedAndCannotBecomeUploadCredentials(){
        var tickets=new ResultTickets(new EphemeralDataProtectionProvider());var i=Intent;var ticket=tickets.Issue(i);
        Assert.Equal(i.ClientId,tickets.Read(ticket,i.Id).ClientId);
        Assert.Throws<V2Exception>(()=>tickets.Read(ticket,Guid.NewGuid()));Assert.Throws<V2Exception>(()=>tickets.Read(ticket+"tamper",i.Id));
        Assert.Throws<V2Exception>(()=>tickets.Read("voc_old_permanent_key",i.Id));
        Assert.False(GatewayTelemetryCredential.Validate("Bearer "+ticket,Secrets.Hash("machine-key-example-example-example")));
    }
    private sealed class Verifier:IImageVerifier{public Task<ImageInfo> Verify(string path,CancellationToken ct)=>Task.FromResult(new ImageInfo(1920,1080,"image/jpeg"));}
    private sealed class FakeDb:IFlowDatabase{
        private readonly HashSet<Guid> committed=[];public int Charges;public bool FailOnce;
        public Task<JsonElement> Gateway(string action,object p,CancellationToken ct=default)=>throw new NotSupportedException();
        public Task<JsonElement> Commit(FlowIntent i,CancellationToken ct=default){if(committed.Add(i.Id))Charges++;if(FailOnce){FailOnce=false;throw new DatabaseUnavailableException("Test: receipt committed but response lost");}return Task.FromResult(JsonSerializer.SerializeToElement(new{accepted=true,jobId=i.Id}));}
    }
}
