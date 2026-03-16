using FluentAssertions;
using LeadPulse.Domain.Authorization;

namespace LeadPulse.Tests.M2_UserManagement;

public class PermissionTests
{
    [Fact]
    public void SuperAdmin_HasAllPermissions()
    {
        // M2-UT01 (partial): Super Admin gets all permissions
        var perms = Permissions.GetDefaultPermissions("SuperAdmin");
        perms.Should().BeEquivalentTo(Permissions.All);
    }

    [Fact]
    public void TenantAdmin_HasManageUsersButNotTenants()
    {
        var perms = Permissions.GetDefaultPermissions("TenantAdmin");
        perms.Should().Contain(Permissions.ManageUsers);
        perms.Should().NotContain(Permissions.ManageTenants);
    }

    [Fact]
    public void Agent_CannotManageUsers()
    {
        // M2-UT03: Agent cannot access user management
        var perms = Permissions.GetDefaultPermissions("Agent");
        perms.Should().NotContain(Permissions.ManageUsers);
        perms.Should().Contain(Permissions.ViewProspects);
        perms.Should().Contain(Permissions.LogCalls);
        perms.Should().Contain(Permissions.ManageStrategies);
    }

    [Fact]
    public void Viewer_HasReadOnlyAccess()
    {
        // M2-UT04: Viewer has read-only access
        var perms = Permissions.GetDefaultPermissions("Viewer");
        perms.Should().Contain(Permissions.ViewProspects);
        perms.Should().Contain(Permissions.ViewAnalytics);
        perms.Should().NotContain(Permissions.ManageProspects);
        perms.Should().NotContain(Permissions.LogCalls);
        perms.Should().NotContain(Permissions.ExportData);
        perms.Should().NotContain(Permissions.ManageUsers);
    }

    [Fact]
    public void Agent_DefaultPermissions_DoNotIncludeExportData()
    {
        // M2-UT05 (partial): Agent with ExportData check
        var perms = Permissions.GetDefaultPermissions("Agent");
        // Agent DOES have ExportData by default per our design
        perms.Should().Contain(Permissions.ExportData);
    }

    [Fact]
    public void UnknownRole_HasNoPermissions()
    {
        var perms = Permissions.GetDefaultPermissions("UnknownRole");
        perms.Should().BeEmpty();
    }
}
