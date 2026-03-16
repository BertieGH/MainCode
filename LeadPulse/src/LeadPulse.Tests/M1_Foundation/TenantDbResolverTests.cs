using FluentAssertions;
using LeadPulse.Domain.Entities.App;
using LeadPulse.Domain.Enums;
using LeadPulse.Domain.Exceptions;
using LeadPulse.Infrastructure.Data;
using LeadPulse.Infrastructure.Services;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Moq;

namespace LeadPulse.Tests.M1_Foundation;

/// <summary>
/// M1-UT01, M1-UT02, M1-UT09: TenantDbResolver tests
/// </summary>
public class TenantDbResolverTests : IDisposable
{
    private readonly AppDbContext _appDb;
    private readonly TenantDbResolver _resolver;

    public TenantDbResolverTests()
    {
        var options = new DbContextOptionsBuilder<AppDbContext>()
            .UseInMemoryDatabase(Guid.NewGuid().ToString())
            .Options;

        _appDb = new AppDbContext(options);

        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["TenantDb:DefaultPassword"] = "testpassword"
            })
            .Build();

        var logger = Mock.Of<ILogger<TenantDbResolver>>();

        _resolver = new TenantDbResolver(_appDb, config, logger);
    }

    [Fact]
    public async Task GetConnectionString_ReturnsCorrectConnectionString_ForValidTenant()
    {
        // M1-UT01: Given TenantId=142, resolver returns connection string for lp_ten142
        var plan = new SubscriptionPlan { Id = 1, Name = "Starter", MaxUsers = 2, MaxSocialAccounts = 3, MaxKeywords = 10, MaxApiCallsPerDay = 1000 };
        _appDb.SubscriptionPlans.Add(plan);

        var tenant = new Tenant { Id = 142, Name = "Test Tenant", Slug = "test", PlanId = 1, Status = TenantStatus.Active, CreatedAt = DateTime.UtcNow };
        _appDb.Tenants.Add(tenant);

        var mapping = new TenantDbMapping
        {
            TenantId = 142,
            DatabaseName = "lp_ten142",
            ServerHost = "db-server",
            Port = 3306,
            Username = "tenant142",
            EncryptedPassword = "enc",
            CreatedAt = DateTime.UtcNow
        };
        _appDb.TenantDbMappings.Add(mapping);
        await _appDb.SaveChangesAsync();

        var connectionString = await _resolver.GetConnectionStringAsync(142);

        connectionString.Should().Contain("lp_ten142");
        connectionString.Should().Contain("db-server");
        connectionString.Should().Contain("3306");
    }

    [Fact]
    public async Task GetConnectionString_ThrowsTenantNotFound_ForUnknownTenant()
    {
        // M1-UT02: Given TenantId=999, throws TenantNotFoundException
        var act = () => _resolver.GetConnectionStringAsync(999);

        await act.Should().ThrowAsync<TenantNotFoundException>()
            .Where(e => e.TenantId == 999);
    }

    [Fact]
    public async Task GetConnectionString_ThrowsTenantSuspended_ForSuspendedTenant()
    {
        // M1-UT09: Given tenant with Status=Suspended, throws TenantSuspendedException
        var plan = new SubscriptionPlan { Id = 1, Name = "Starter", MaxUsers = 2, MaxSocialAccounts = 3, MaxKeywords = 10, MaxApiCallsPerDay = 1000 };
        _appDb.SubscriptionPlans.Add(plan);

        var tenant = new Tenant { Id = 50, Name = "Suspended Tenant", Slug = "suspended", PlanId = 1, Status = TenantStatus.Suspended, CreatedAt = DateTime.UtcNow };
        _appDb.Tenants.Add(tenant);
        await _appDb.SaveChangesAsync();

        var act = () => _resolver.GetConnectionStringAsync(50);

        await act.Should().ThrowAsync<TenantSuspendedException>()
            .Where(e => e.TenantId == 50);
    }

    public void Dispose()
    {
        _appDb.Dispose();
    }
}
