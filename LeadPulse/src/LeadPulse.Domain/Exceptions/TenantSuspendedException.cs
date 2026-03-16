namespace LeadPulse.Domain.Exceptions;

public class TenantSuspendedException : Exception
{
    public int TenantId { get; }

    public TenantSuspendedException(int tenantId)
        : base($"Tenant with ID {tenantId} is suspended.")
    {
        TenantId = tenantId;
    }
}
