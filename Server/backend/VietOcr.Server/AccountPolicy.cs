namespace VietOcr.Server;

public static class AccountPolicy
{
    public const int DailyImageCap = 500;
    public const int MinuteRequestCap = 30;
    public const string QuotaTimezone = "Asia/Ho_Chi_Minh";
}
