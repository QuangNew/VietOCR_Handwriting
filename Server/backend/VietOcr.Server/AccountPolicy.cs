using System.Text.Json;

namespace VietOcr.Server;

public static class AccountPolicy
{
    public const int DailyImageCap = 500;
    public const int MinuteRequestCap = 30;
    public const string QuotaTimezone = "Asia/Ho_Chi_Minh";
    public static void RequireDatabasePolicy(JsonElement value)
    {
        static bool Matches(JsonElement root,string name,int expected)=>root.ValueKind==JsonValueKind.Object
            &&root.TryGetProperty(name,out var field)&&field.ValueKind==JsonValueKind.Number&&field.TryGetInt32(out var number)&&number==expected;
        if(!Matches(value,"policyVersion",2)||!Matches(value,"dailyImageCap",DailyImageCap)||!Matches(value,"minuteRequestCap",MinuteRequestCap))
            throw new DatabaseUnavailableException("Apply the 20261109 Supabase policy migration before accepting OCR on this branch.");
    }
}
