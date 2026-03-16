using LeadPulse.Domain.Enums;

namespace LeadPulse.Domain.Entities.App;

public class BillingRecord
{
    public int Id { get; set; }
    public int TenantId { get; set; }
    public int PlanId { get; set; }
    public DateTime PeriodStart { get; set; }
    public DateTime PeriodEnd { get; set; }
    public decimal? Amount { get; set; }
    public BillingStatus Status { get; set; }
    public DateTime CreatedAt { get; set; }

    public Tenant Tenant { get; set; } = null!;
}
