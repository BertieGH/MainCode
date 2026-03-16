using LeadPulse.Application.Interfaces;
using LeadPulse.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace LeadPulse.Infrastructure.Services;

public class TenantDbContextFactory
{
    private readonly ITenantDbResolver _resolver;
    private readonly ILogger<TenantDbContextFactory> _logger;

    public TenantDbContextFactory(ITenantDbResolver resolver, ILogger<TenantDbContextFactory> logger)
    {
        _resolver = resolver;
        _logger = logger;
    }

    public async Task<TenantDbContext> CreateContextAsync(int tenantId)
    {
        var connectionString = await _resolver.GetConnectionStringAsync(tenantId);

        var options = new DbContextOptionsBuilder<TenantDbContext>()
            .UseMySql(connectionString, ServerVersion.AutoDetect(connectionString))
            .Options;

        _logger.LogDebug("Created TenantDbContext for tenant {TenantId}", tenantId);

        return new TenantDbContext(options);
    }
}
