using LeadPulse.Domain.Enums;

namespace LeadPulse.Domain.Entities.App;

public class Tenant
{
    public int Id { get; set; }
    public string Name { get; set; } = string.Empty;
    public string Slug { get; set; } = string.Empty;
    public string? Industry { get; set; }
    public int PlanId { get; set; }
    public string? BillingEmail { get; set; }
    public string? CustomDomain { get; set; }
    public TenantStatus Status { get; set; } = TenantStatus.PendingSetup;
    public DateTime CreatedAt { get; set; }
    public DateTime? UpdatedAt { get; set; }

    public SubscriptionPlan Plan { get; set; } = null!;
    public TenantDbMapping? DbMapping { get; set; }
    public ICollection<BillingRecord> BillingRecords { get; set; } = new List<BillingRecord>();
}
