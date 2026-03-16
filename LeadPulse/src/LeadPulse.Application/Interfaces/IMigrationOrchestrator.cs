namespace LeadPulse.Application.Interfaces;

public interface IMigrationOrchestrator
{
    Task MigrateAllTenantsAsync();
    Task MigrateTenantAsync(int tenantId);
}
