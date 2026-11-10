namespace VietOcr.Server;

public sealed record FlowCancellationResult(string State,bool Accepted);

public static class FlowCancellation
{
    // The route resolves the owner through the Google-session RPC first. Both
    // job lookups stay scoped to that client. Accepted quota is never refunded.
    public static async Task<FlowCancellationResult> Apply(FlowIntent intent,IFlowDatabase db,
        Func<Task<Job?>> findJob,Func<Job,Task> cancel,CancellationToken ct)
    {
        var job=await findJob();
        if(job!=null){
            if(job.State is "queued" or "running"){
                await cancel(job);
                job=await findJob()??job;
            }
            return new(job.State,true);
        }
        if(intent.State is "queued" or "running" or "succeeded" or "failed")
            throw new V2Exception(410,"result_expired");
        FlowJson.Check(await db.Gateway("release",new{
            intent.UserId,intent.SessionId,jobId=intent.Id,
            intent.Generation,cancel=true},ct));
        return new("cancelled",false);
    }
}
