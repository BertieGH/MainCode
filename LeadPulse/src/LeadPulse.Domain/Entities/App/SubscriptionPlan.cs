namespace LeadPulse.Domain.Entities.App;

public class SubscriptionPlan
{
    public int Id { get; set; }
    public string Name { get; set; } = string.Empty;
    public int MaxUsers { get; set; }
    public int MaxSocialAccounts { get; set; }
    public int MaxKeywords { get; set; }
    public int MaxApiCallsPerDay { get; set; }
    public bool DedicatedDbServer { get; set; }
    public decimal? PriceMonthly { get; set; }
    public bool IsActive { get; set; } = true;
}
