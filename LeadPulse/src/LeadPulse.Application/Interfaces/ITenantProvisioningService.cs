namespace LeadPulse.Application.Interfaces;

public interface ITenantProvisioningService
{
    Task ProvisionTenantDatabaseAsync(int tenantId, string tenantName);
}
