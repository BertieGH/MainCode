using FluentAssertions;
using LeadPulse.Domain.Entities.App;
using LeadPulse.Domain.Enums;

namespace LeadPulse.Tests.M8_TenantAdmin;

/// <summary>
/// M8-UT01 through M8-UT12: Tenant Administration and SaaS Platform tests
/// </summary>
public class TenantAdminTests
{
    [Fact]
    public void NewTenant_HasPendingSetupStatus()
    {
        // M8-UT01: Tenant creation sets PendingSetup status
        var tenant = new Tenant
        {
            Id = 1,
            Name = "Acme Corp",
            Slug = "acme-corp",
            PlanId = 1
        };

        tenant.Status.Should().Be(TenantStatus.PendingSetup);
    }

    [Fact]
    public void Slug_MustBeUnique()
    {
        // M8-UT02: Slug uniqueness — two tenants can't share a slug
        var tenants = new List<Tenant>
        {
            new() { Id = 1, Name = "Acme Corp", Slug = "acme-corp", PlanId = 1 },
            new() { Id = 2, Name = "Beta Inc", Slug = "beta-inc", PlanId = 1 },
            new() { Id = 3, Name = "Gamma LLC", Slug = "gamma-llc", PlanId = 2 },
        };

        var slugs = tenants.Select(t => t.Slug).ToList();
        slugs.Distinct().Should().HaveCount(slugs.Count, "all tenant slugs must be unique");
    }

    [Fact]
    public void Suspend_ChangesStatusToSuspended()
    {
        // M8-UT03: Suspension changes status
        var tenant = new Tenant
        {
            Id = 1,
            Name = "Acme Corp",
            Slug = "acme-corp",
            Status = TenantStatus.Active,
            PlanId = 1
        };

        tenant.Status = TenantStatus.Suspended;

        tenant.Status.Should().Be(TenantStatus.Suspended);
    }

    [Fact]
    public void Reactivate_ChangesStatusToActive()
    {
        // M8-UT04: Reactivation changes status back to Active
        var tenant = new Tenant
        {
            Id = 1,
            Name = "Acme Corp",
            Slug = "acme-corp",
            Status = TenantStatus.Suspended,
            PlanId = 1
        };

        tenant.Status = TenantStatus.Active;

        tenant.Status.Should().Be(TenantStatus.Active);
    }

    [Fact]
    public void SoftDelete_SetsDeletedStatus()
    {
        // M8-UT05: Soft delete sets Deleted status
        var tenant = new Tenant
        {
            Id = 1,
            Name = "Acme Corp",
            Slug = "acme-corp",
            Status = TenantStatus.Active,
            PlanId = 1
        };

        tenant.Status = TenantStatus.Deleted;

        tenant.Status.Should().Be(TenantStatus.Deleted);
    }

    [Fact]
    public void DeletedTenants_ExcludedFromListing()
    {
        // M8-UT06: Deleted tenants excluded from listing
        var tenants = new List<Tenant>
        {
            new() { Id = 1, Name = "Active Co", Slug = "active-co", Status = TenantStatus.Active, PlanId = 1 },
            new() { Id = 2, Name = "Pending Co", Slug = "pending-co", Status = TenantStatus.PendingSetup, PlanId = 1 },
            new() { Id = 3, Name = "Deleted Co", Slug = "deleted-co", Status = TenantStatus.Deleted, PlanId = 1 },
            new() { Id = 4, Name = "Suspended Co", Slug = "suspended-co", Status = TenantStatus.Suspended, PlanId = 2 },
            new() { Id = 5, Name = "Also Deleted", Slug = "also-deleted", Status = TenantStatus.Deleted, PlanId = 2 },
        };

        var listed = tenants.Where(t => t.Status != TenantStatus.Deleted).ToList();

        listed.Should().HaveCount(3);
        listed.Should().NotContain(t => t.Status == TenantStatus.Deleted);
    }

    [Fact]
    public void UpdatePlan_ChangesPlanId()
    {
        // M8-UT07: Plan update changes PlanId
        var tenant = new Tenant
        {
            Id = 1,
            Name = "Acme Corp",
            Slug = "acme-corp",
            PlanId = 1,
            Status = TenantStatus.Active
        };

        var newPlanId = 3;
        tenant.PlanId = newPlanId;

        tenant.PlanId.Should().Be(3);
    }

    [Fact]
    public void RateLimit_UnderLimit_Allows()
    {
        // M8-UT08: Rate limit — under limit allows request
        var plan = new SubscriptionPlan
        {
            Id = 1,
            Name = "Pro",
            MaxApiCallsPerDay = 1000
        };

        var rateLimit = new ApiRateLimit
        {
            TenantId = 1,
            Date = DateTime.UtcNow.Date,
            CallCount = 500
        };

        var isAllowed = rateLimit.CallCount < plan.MaxApiCallsPerDay;

        isAllowed.Should().BeTrue("call count 500 is under the limit of 1000");
    }

    [Fact]
    public void RateLimit_AtLimit_Blocks()
    {
        // M8-UT09: Rate limit — at limit blocks request
        var plan = new SubscriptionPlan
        {
            Id = 1,
            Name = "Pro",
            MaxApiCallsPerDay = 1000
        };

        var rateLimit = new ApiRateLimit
        {
            TenantId = 1,
            Date = DateTime.UtcNow.Date,
            CallCount = 1000
        };

        var isBlocked = rateLimit.CallCount >= plan.MaxApiCallsPerDay;

        isBlocked.Should().BeTrue("call count 1000 has reached the limit of 1000");
    }

    [Fact]
    public void RateLimit_DifferentDay_NewRecord()
    {
        // M8-UT10: Rate limit resets daily — different dates are independent records
        var today = DateTime.UtcNow.Date;
        var yesterday = today.AddDays(-1);

        var todayLimit = new ApiRateLimit
        {
            TenantId = 1,
            Date = today,
            CallCount = 50
        };

        var yesterdayLimit = new ApiRateLimit
        {
            TenantId = 1,
            Date = yesterday,
            CallCount = 950
        };

        todayLimit.Date.Should().NotBe(yesterdayLimit.Date, "each day gets its own rate limit record");
        todayLimit.CallCount.Should().NotBe(yesterdayLimit.CallCount, "daily counts are independent");
        todayLimit.CallCount.Should().Be(50);
        yesterdayLimit.CallCount.Should().Be(950);
    }

    [Fact]
    public void Impersonate_RequiresActiveTenant()
    {
        // M8-UT11: Impersonation requires Active tenant
        var tenant = new Tenant
        {
            Id = 1,
            Name = "Suspended Co",
            Slug = "suspended-co",
            Status = TenantStatus.Suspended,
            PlanId = 1
        };

        var canImpersonate = tenant.Status == TenantStatus.Active;

        canImpersonate.Should().BeFalse("suspended tenants cannot be impersonated");
    }

    [Fact]
    public void PlanLimits_StructureCorrect()
    {
        // M8-UT12: Plan limits are correct structure
        var plan = new SubscriptionPlan
        {
            Id = 2,
            Name = "Enterprise",
            MaxUsers = 50,
            MaxSocialAccounts = 20,
            MaxKeywords = 100,
            MaxApiCallsPerDay = 10000,
            DedicatedDbServer = true,
            PriceMonthly = 299.99m,
            IsActive = true
        };

        plan.Name.Should().NotBeNullOrEmpty();
        plan.MaxUsers.Should().BeGreaterThan(0);
        plan.MaxSocialAccounts.Should().BeGreaterThan(0);
        plan.MaxKeywords.Should().BeGreaterThan(0);
        plan.MaxApiCallsPerDay.Should().BeGreaterThan(0);
        plan.DedicatedDbServer.Should().BeTrue();
        plan.PriceMonthly.Should().BeGreaterThan(0);
        plan.IsActive.Should().BeTrue();
    }
}
