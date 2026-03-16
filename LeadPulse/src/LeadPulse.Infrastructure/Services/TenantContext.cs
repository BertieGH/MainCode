using LeadPulse.Application.Interfaces;

namespace LeadPulse.Infrastructure.Services;

public class TenantContext : ITenantContext
{
    public int? TenantId { get; set; }
}
