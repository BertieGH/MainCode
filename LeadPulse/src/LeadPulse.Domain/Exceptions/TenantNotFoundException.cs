namespace LeadPulse.Domain.Exceptions;

public class TenantNotFoundException : Exception
{
    public int TenantId { get; }

    public TenantNotFoundException(int tenantId)
        : base($"Tenant with ID {tenantId} was not found.")
    {
        TenantId = tenantId;
    }
}
