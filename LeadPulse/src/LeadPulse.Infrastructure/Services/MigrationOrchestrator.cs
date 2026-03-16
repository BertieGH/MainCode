using LeadPulse.Application.Interfaces;
using LeadPulse.Domain.Enums;
using LeadPulse.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace LeadPulse.Infrastructure.Services;

public class MigrationOrchestrator : IMigrationOrchestrator
{
    private readonly AppDbContext _appDb;
    private readonly ITenantDbResolver _resolver;
    private readonly ILogger<MigrationOrchestrator> _logger;

    public MigrationOrchestrator(AppDbContext appDb, ITenantDbResolver resolver, ILogger<MigrationOrchestrator> logger)
    {
        _appDb = appDb;
        _resolver = resolver;
        _logger = logger;
    }

    public async Task MigrateAllTenantsAsync()
    {
        var activeTenants = await _appDb.Tenants
            .Where(t => t.Status == TenantStatus.Active)
            .Select(t => t.Id)
            .ToListAsync();

        _logger.LogInformation("Starting migration for {Count} active tenants", activeTenants.Count);

        foreach (var tenantId in activeTenants)
        {
            try
            {
                await MigrateTenantAsync(tenantId);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to migrate tenant {TenantId}", tenantId);
            }
        }

        _logger.LogInformation("Migration orchestration complete");
    }

    public async Task MigrateTenantAsync(int tenantId)
    {
        var connectionString = await _resolver.GetConnectionStringAsync(tenantId);

        var options = new DbContextOptionsBuilder<TenantDbContext>()
            .UseMySql(connectionString, ServerVersion.AutoDetect(connectionString))
            .Options;

        await using var tenantDb = new TenantDbContext(options);

        var pending = await tenantDb.Database.GetPendingMigrationsAsync();
        var pendingList = pending.ToList();

        if (pendingList.Count > 0)
        {
            _logger.LogInformation("Applying {Count} pending migrations to tenant {TenantId}", pendingList.Count, tenantId);
            await tenantDb.Database.MigrateAsync();

            // Update migration version in App DB
            var mapping = await _appDb.TenantDbMappings.FirstOrDefaultAsync(m => m.TenantId == tenantId);
            if (mapping != null)
            {
                var applied = await tenantDb.Database.GetAppliedMigrationsAsync();
                mapping.MigrationVersion = applied.LastOrDefault();
                await _appDb.SaveChangesAsync();
            }
        }
        else
        {
            _logger.LogDebug("Tenant {TenantId} is up to date", tenantId);
        }
    }
}
