namespace LeadPulse.Domain.Entities.App;

public class ApiRateLimit
{
    public long Id { get; set; }
    public int TenantId { get; set; }
    public DateTime Date { get; set; }
    public int CallCount { get; set; }

    public Tenant Tenant { get; set; } = null!;
}
