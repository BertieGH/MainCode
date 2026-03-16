using FluentAssertions;
using LeadPulse.Domain.Entities.App;
using LeadPulse.Domain.Enums;
using LeadPulse.Infrastructure.Data;
using LeadPulse.Infrastructure.Services;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Moq;

namespace LeadPulse.Tests.M1_Foundation;

/// <summary>
/// M1-UT03: TenantDbContextFactory creates scoped context
/// M1-UT10: Cross-database isolation
/// </summary>
public class TenantContextTests : IDisposable
{
    private readonly AppDbContext _appDb;

    public TenantContextTests()
    {
        var options = new DbContextOptionsBuilder<AppDbContext>()
            .UseInMemoryDatabase(Guid.NewGuid().ToString())
            .Options;
        _appDb = new AppDbContext(options);
    }

    [Fact]
    public void TenantContext_StartsWithNullTenantId()
    {
        var context = new TenantContext();
        context.TenantId.Should().BeNull();
    }

    [Fact]
    public void TenantContext_CanSetAndGetTenantId()
    {
        var context = new TenantContext();
        context.TenantId = 142;
        context.TenantId.Should().Be(142);
    }

    [Fact]
    public async Task TenantDbResolver_ReturnsCorrectDatabase_ForEachTenant()
    {
        // M1-UT10: Cross-database isolation - each tenant resolves to different DB
        var plan = new SubscriptionPlan { Id = 1, Name = "Starter", MaxUsers = 2, MaxSocialAccounts = 3, MaxKeywords = 10, MaxApiCallsPerDay = 1000 };
        _appDb.SubscriptionPlans.Add(plan);

        _appDb.Tenants.AddRange(
            new Tenant { Id = 1, Name = "Tenant A", Slug = "tenant-a", PlanId = 1, Status = TenantStatus.Active, CreatedAt = DateTime.UtcNow },
            new Tenant { Id = 2, Name = "Tenant B", Slug = "tenant-b", PlanId = 1, Status = TenantStatus.Active, CreatedAt = DateTime.UtcNow }
        );

        _appDb.TenantDbMappings.AddRange(
            new TenantDbMapping { TenantId = 1, DatabaseName = "lp_ten1", ServerHost = "localhost", Port = 3306, Username = "u1", EncryptedPassword = "p1", CreatedAt = DateTime.UtcNow },
            new TenantDbMapping { TenantId = 2, DatabaseName = "lp_ten2", ServerHost = "localhost", Port = 3306, Username = "u2", EncryptedPassword = "p2", CreatedAt = DateTime.UtcNow }
        );

        await _appDb.SaveChangesAsync();

        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?> { ["TenantDb:DefaultPassword"] = "test" })
            .Build();

        var resolver = new TenantDbResolver(_appDb, config, Mock.Of<ILogger<TenantDbResolver>>());

        var connA = await resolver.GetConnectionStringAsync(1);
        var connB = await resolver.GetConnectionStringAsync(2);

        connA.Should().Contain("lp_ten1");
        connB.Should().Contain("lp_ten2");
        connA.Should().NotBe(connB, "each tenant has its own database");
    }

    public void Dispose()
    {
        _appDb.Dispose();
    }
}
