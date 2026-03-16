namespace LeadPulse.Application.Interfaces;

public interface ITenantDbResolver
{
    Task<string> GetConnectionStringAsync(int tenantId);
}
