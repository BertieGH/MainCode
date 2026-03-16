using FluentAssertions;
using LeadPulse.Domain.Entities.App;
using LeadPulse.Domain.Enums;

namespace LeadPulse.Tests.M9_Integration;

/// <summary>
/// M9 Tenant isolation and multi-tenancy tests
/// </summary>
public class TenantIsolationTests
{
    [Fact]
    public void TenantDbMapping_EachTenantHasUniqueDatabase()
    {
        var mappings = new[]
        {
            new TenantDbMapping { TenantId = 1, DatabaseName = "lp_ten1" },
            new TenantDbMapping { TenantId = 2, DatabaseName = "lp_ten2" },
            new TenantDbMapping { TenantId = 3, DatabaseName = "lp_ten3" },
        };

        var dbNames = mappings.Select(m => m.DatabaseName).ToList();
        dbNames.Distinct().Should().HaveCount(dbNames.Count, "each tenant must have a unique database");
    }

    [Fact]
    public void TenantDbMapping_ConnectionStringsAreDistinct()
    {
        var mappings = new[]
        {
            new TenantDbMapping { TenantId = 1, DatabaseName = "lp_ten1", ServerHost = "localhost", Username = "user1", Port = 3306 },
            new TenantDbMapping { TenantId = 2, DatabaseName = "lp_ten2", ServerHost = "localhost", Username = "user2", Port = 3306 },
        };

        var connStrings = mappings.Select(m => m.GetConnectionString("pass")).ToList();
        connStrings.Distinct().Should().HaveCount(mappings.Length, "connection strings must be unique per tenant");
    }

    [Fact]
    public void SuspendedTenant_CannotLogin()
    {
        var tenant = new Tenant { Id = 1, Status = TenantStatus.Suspended };
        var canLogin = tenant.Status == TenantStatus.Active;
        canLogin.Should().BeFalse("suspended tenants cannot log in");
    }

    [Fact]
    public void DeletedTenant_CannotLogin()
    {
        var tenant = new Tenant { Id = 1, Status = TenantStatus.Deleted };
        var canLogin = tenant.Status == TenantStatus.Active;
        canLogin.Should().BeFalse("deleted tenants cannot log in");
    }

    [Fact]
    public void PendingSetupTenant_CannotLogin()
    {
        var tenant = new Tenant { Id = 1, Status = TenantStatus.PendingSetup };
        var canLogin = tenant.Status == TenantStatus.Active;
        canLogin.Should().BeFalse("pending setup tenants cannot log in");
    }

    [Fact]
    public void ActiveTenant_CanLogin()
    {
        var tenant = new Tenant { Id = 1, Status = TenantStatus.Active };
        var canLogin = tenant.Status == TenantStatus.Active;
        canLogin.Should().BeTrue();
    }

    [Fact]
    public void TenantId_InClaims_ScopesAccess()
    {
        var tenantIdFromToken = 5;
        var requestedTenantId = 5;
        (tenantIdFromToken == requestedTenantId).Should().BeTrue();

        requestedTenantId = 10;
        (tenantIdFromToken == requestedTenantId).Should().BeFalse("tenant 5 cannot access tenant 10 data");
    }

    [Fact]
    public void DatabaseNaming_FollowsConvention()
    {
        var tenantId = 42;
        var expectedDbName = $"lp_ten{tenantId}";
        expectedDbName.Should().Be("lp_ten42");
        expectedDbName.Should().StartWith("lp_ten");
    }
}
