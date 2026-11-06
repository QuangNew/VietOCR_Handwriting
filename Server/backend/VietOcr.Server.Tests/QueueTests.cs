using VietOcr.Server;
using Xunit;

namespace VietOcr.Server.Tests;

public class QueueTests
{
    private static Job J(string id,string client) => new(id,client,client,null,"hash","line","queued",100,DateTime.UtcNow);
    [Fact] public void BatchCannotStarveSecondClient()
    {
        var queue=new FairQueue(); for(var i=0;i<50;i++)queue.Add(J("a"+i,"batch"));
        queue.Add(J("b0","interactive")); queue.Add(J("b1","interactive"));
        Assert.Equal("a0",queue.Take()!.Id); Assert.Equal("b0",queue.Take()!.Id);
        Assert.Equal("a1",queue.Take()!.Id); Assert.Equal("b1",queue.Take()!.Id);
        Assert.Equal(48,queue.Count);
    }
    [Fact] public void CancelledJobsAreSkippedWithoutBlockingClient()
    {
        var q=new FairQueue();q.Add(J("1","a"));q.Add(J("2","a"));q.Remove("1");
        Assert.Equal("2",q.Take()!.Id);Assert.Null(q.Take());Assert.Equal(0,q.Count);
    }
    [Fact] public void DuplicateRecoveryDoesNotRunTwice()
    {
        var q=new FairQueue();Assert.True(q.Add(J("1","a")));Assert.False(q.Add(J("1","a")));
        Assert.Equal(1,q.Count);Assert.NotNull(q.Take());Assert.Null(q.Take());
    }
    [Fact] public void ConcurrentProducersKeepAllJobs()
    {
        var q=new FairQueue();Parallel.For(0,1000,i=>q.Add(J(i.ToString(),(i%10).ToString())));
        var ids=new HashSet<string>();while(q.Take() is {} job)Assert.True(ids.Add(job.Id));Assert.Equal(1000,ids.Count);
    }
    [Fact] public void FirstWorkerUsesSafetyAllowanceRatherThanFileSize()
    {Assert.True(Capacity.RequiredMiB(300,[])>=768);}
    [Fact] public void StaleGpuCannotAdmitWorker()
    {Assert.False(Capacity.CanAdd(new("test",6144,100,6044,0,50,DateTime.UtcNow.AddSeconds(-15)),1024,1000));}
    [Theory]
    [InlineData(2000,1000,false)] [InlineData(2024,1000,true)] [InlineData(1024,300,false)]
    public void AdmissionLeavesReserve(int free,int required,bool expected)
    {Assert.Equal(expected,Capacity.CanAdd(new("test",6144,6144-free,free,0,50,DateTime.UtcNow),1024,required));}
    [Fact] public void MissingGpuCannotAdmitCudaWorker(){Assert.False(Capacity.CanAdd(null,1024,300));}
    [Fact] public void PercentileEmptyIsMissingNotZero(){Assert.Null(Capacity.Percentile([],.95));}
    [Fact] public void PercentileIsNearestRank(){Assert.Equal(19,Capacity.Percentile(Enumerable.Range(1,20).Select(i=>(double)i),.95));}
    [Fact] public void KeyHashDoesNotContainToken(){var token=Secrets.Token();Assert.Equal(64,token.Length);Assert.NotEqual(token,Secrets.Hash(token));}
    [Fact] public void PasswordIsSaltedAndVerifiable()
    {var one=Secrets.PasswordHash("my long passphrase");var two=Secrets.PasswordHash("my long passphrase");Assert.NotEqual(one,two);
        Assert.True(Secrets.VerifyPassword("my long passphrase",one));Assert.False(Secrets.VerifyPassword("bad",one));}
    [Fact] public void ShortPasswordRejected(){Assert.Throws<ArgumentException>(()=>Secrets.PasswordHash("short"));}
    [Theory] [InlineData("")] [InlineData("garbage")] [InlineData("pbkdf2-sha256:0:x:x")]
    public void InvalidPasswordRecordFailsClosed(string value){Assert.False(Secrets.VerifyPassword("test",value));}
}
