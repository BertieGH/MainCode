using LeadPulse.Application.Interfaces;
using LeadPulse.Domain.Entities.App;
using LeadPulse.Domain.Entities.Tenant;
using LeadPulse.Domain.Enums;
using LeadPulse.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;

namespace LeadPulse.Infrastructure.Services;

public class TenantProvisioningService : ITenantProvisioningService
{
    private readonly AppDbContext _appDb;
    private readonly IPasswordHasher _passwordHasher;
    private readonly IConfiguration _configuration;
    private readonly ILogger<TenantProvisioningService> _logger;

    public TenantProvisioningService(
        AppDbContext appDb,
        IPasswordHasher passwordHasher,
        IConfiguration configuration,
        ILogger<TenantProvisioningService> logger)
    {
        _appDb = appDb;
        _passwordHasher = passwordHasher;
        _configuration = configuration;
        _logger = logger;
    }

    public async Task ProvisionTenantDatabaseAsync(int tenantId, string tenantName)
    {
        var tenant = await _appDb.Tenants.FindAsync(tenantId)
            ?? throw new InvalidOperationException($"Tenant {tenantId} not found");

        var dbName = $"lp_ten{tenantId}";
        var serverHost = _configuration["TenantDb:ServerHost"] ?? "localhost";
        var port = int.Parse(_configuration["TenantDb:Port"] ?? "3306");
        var dbUser = _configuration["TenantDb:Username"] ?? "leadpulse";
        var dbPassword = _configuration["TenantDb:DefaultPassword"] ?? "leadpulse";

        _logger.LogInformation("Provisioning database {Database} for tenant {TenantId} ({TenantName})", dbName, tenantId, tenantName);

        // 1. Create the MySQL database
        var masterConnectionString = $"Server={serverHost};Port={port};User={dbUser};Password={dbPassword}";
        await using var masterConnection = new MySqlConnector.MySqlConnection(masterConnectionString);
        await masterConnection.OpenAsync();
        await using var createCmd = masterConnection.CreateCommand();
        createCmd.CommandText = $"CREATE DATABASE IF NOT EXISTS `{dbName}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci";
        await createCmd.ExecuteNonQueryAsync();

        // 2. Run EF Core migrations on the new database
        var tenantConnectionString = $"Server={serverHost};Port={port};Database={dbName};User={dbUser};Password={dbPassword}";
        var options = new DbContextOptionsBuilder<TenantDbContext>()
            .UseMySql(tenantConnectionString, ServerVersion.AutoDetect(tenantConnectionString))
            .Options;

        await using var tenantDb = new TenantDbContext(options);
        await tenantDb.Database.MigrateAsync();

        // 3. Seed default admin user
        if (!await tenantDb.Users.AnyAsync())
        {
            var adminUser = new User
            {
                FirstName = "Admin",
                LastName = tenantName,
                Email = $"admin@{tenant.Slug}.leadpulse.com",
                PasswordHash = _passwordHasher.Hash("ChangeMe123!"),
                Role = UserRole.TenantAdmin,
                ForcePasswordChange = true,
                Status = UserStatus.Active,
                CreatedAt = DateTime.UtcNow
            };
            tenantDb.Users.Add(adminUser);
            await tenantDb.SaveChangesAsync();
        }

        // 4. Record the DB mapping in App DB
        var mapping = await _appDb.TenantDbMappings
            .FirstOrDefaultAsync(m => m.TenantId == tenantId);

        if (mapping == null)
        {
            mapping = new TenantDbMapping
            {
                TenantId = tenantId,
                DatabaseName = dbName,
                ServerHost = serverHost,
                Port = port,
                Username = dbUser,
                EncryptedPassword = dbPassword,
                MigrationVersion = "Initial",
                CreatedAt = DateTime.UtcNow
            };
            _appDb.TenantDbMappings.Add(mapping);
        }

        // 5. Update tenant status
        tenant.Status = TenantStatus.Active;
        tenant.UpdatedAt = DateTime.UtcNow;

        await _appDb.SaveChangesAsync();

        _logger.LogInformation("Successfully provisioned database {Database} for tenant {TenantId}", dbName, tenantId);
    }
}
