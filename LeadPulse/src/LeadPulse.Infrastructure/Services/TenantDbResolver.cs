using LeadPulse.Application.Interfaces;
using LeadPulse.Domain.Enums;
using LeadPulse.Domain.Exceptions;
using LeadPulse.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;

namespace LeadPulse.Infrastructure.Services;

public class TenantDbResolver : ITenantDbResolver
{
    private readonly AppDbContext _appDb;
    private readonly IConfiguration _configuration;
    private readonly ILogger<TenantDbResolver> _logger;

    public TenantDbResolver(AppDbContext appDb, IConfiguration configuration, ILogger<TenantDbResolver> logger)
    {
        _appDb = appDb;
        _configuration = configuration;
        _logger = logger;
    }

    public async Task<string> GetConnectionStringAsync(int tenantId)
    {
        var tenant = await _appDb.Tenants
            .AsNoTracking()
            .FirstOrDefaultAsync(t => t.Id == tenantId);

        if (tenant == null)
            throw new TenantNotFoundException(tenantId);

        if (tenant.Status == TenantStatus.Suspended)
            throw new TenantSuspendedException(tenantId);

        var mapping = await _appDb.TenantDbMappings
            .AsNoTracking()
            .FirstOrDefaultAsync(m => m.TenantId == tenantId);

        if (mapping == null)
            throw new TenantNotFoundException(tenantId);

        var dbPassword = _configuration["TenantDb:DefaultPassword"] ?? "leadpulse";

        var connectionString = $"Server={mapping.ServerHost};Port={mapping.Port};Database={mapping.DatabaseName};User={mapping.Username};Password={dbPassword}";

        _logger.LogDebug("Resolved connection for tenant {TenantId} to database {Database}", tenantId, mapping.DatabaseName);

        return connectionString;
    }
}
