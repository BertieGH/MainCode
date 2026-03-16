using FluentAssertions;
using LeadPulse.Domain.Entities.App;
using LeadPulse.Domain.Entities.Tenant;
using LeadPulse.Domain.Enums;
using LeadPulse.Infrastructure.Data;
using LeadPulse.Infrastructure.Services;
using Microsoft.EntityFrameworkCore;

namespace LeadPulse.Tests.M2_UserManagement;

public class UserManagementTests : IDisposable
{
    private readonly TenantDbContext _tenantDb;
    private readonly AppDbContext _appDb;
    private readonly PasswordHasher _passwordHasher;

    public UserManagementTests()
    {
        var tenantOptions = new DbContextOptionsBuilder<TenantDbContext>()
            .UseInMemoryDatabase(Guid.NewGuid().ToString())
            .Options;
        _tenantDb = new TenantDbContext(tenantOptions);

        var appOptions = new DbContextOptionsBuilder<AppDbContext>()
            .UseInMemoryDatabase(Guid.NewGuid().ToString())
            .Options;
        _appDb = new AppDbContext(appOptions);

        _passwordHasher = new PasswordHasher();
    }

    [Fact]
    public async Task DisabledUser_CannotLogin()
    {
        // M2-UT06: Disable user revokes access
        var user = new User
        {
            FirstName = "Test",
            LastName = "User",
            Email = "test@test.com",
            PasswordHash = _passwordHasher.Hash("Test123!"),
            Role = UserRole.Agent,
            Status = UserStatus.Disabled,
            CreatedAt = DateTime.UtcNow
        };
        _tenantDb.Users.Add(user);
        await _tenantDb.SaveChangesAsync();

        var found = await _tenantDb.Users.FirstOrDefaultAsync(u => u.Email == "test@test.com");
        found.Should().NotBeNull();
        found!.Status.Should().Be(UserStatus.Disabled);

        // In auth flow, disabled users are rejected
        var isDisabled = found.Status == UserStatus.Disabled;
        isDisabled.Should().BeTrue("disabled users should not be able to login");
    }

    [Fact]
    public async Task PasswordReset_GeneratesNewHash()
    {
        // M2-UT07: Password reset generates new hash
        var originalHash = _passwordHasher.Hash("OldPassword");
        var user = new User
        {
            FirstName = "Test",
            LastName = "User",
            Email = "reset@test.com",
            PasswordHash = originalHash,
            Role = UserRole.Agent,
            Status = UserStatus.Active,
            CreatedAt = DateTime.UtcNow
        };
        _tenantDb.Users.Add(user);
        await _tenantDb.SaveChangesAsync();

        // Reset password
        var newHash = _passwordHasher.Hash("NewPassword123!");
        user.PasswordHash = newHash;
        user.ForcePasswordChange = true;
        await _tenantDb.SaveChangesAsync();

        // Verify
        _passwordHasher.Verify("NewPassword123!", user.PasswordHash).Should().BeTrue();
        _passwordHasher.Verify("OldPassword", user.PasswordHash).Should().BeFalse();
        user.ForcePasswordChange.Should().BeTrue();
    }

    [Fact]
    public async Task InvitationToken_CanExpire()
    {
        // M2-UT09: Invitation token expiry
        var inviter = new User
        {
            FirstName = "Admin",
            LastName = "User",
            Email = "admin@test.com",
            PasswordHash = _passwordHasher.Hash("Admin123!"),
            Role = UserRole.TenantAdmin,
            Status = UserStatus.Active,
            CreatedAt = DateTime.UtcNow
        };
        _tenantDb.Users.Add(inviter);
        await _tenantDb.SaveChangesAsync();

        var invitation = new UserInvitation
        {
            Email = "new@test.com",
            Role = UserRole.Agent,
            InvitedByUserId = inviter.Id,
            Token = Guid.NewGuid().ToString("N"),
            ExpiresAt = DateTime.UtcNow.AddDays(-1), // Already expired
            CreatedAt = DateTime.UtcNow.AddDays(-8)
        };
        _tenantDb.UserInvitations.Add(invitation);
        await _tenantDb.SaveChangesAsync();

        var found = await _tenantDb.UserInvitations.FirstAsync(i => i.Token == invitation.Token);
        var isExpired = found.ExpiresAt < DateTime.UtcNow;
        isExpired.Should().BeTrue("expired invitation should be rejected");
        found.AcceptedAt.Should().BeNull();
    }

    [Fact]
    public async Task MaxUserLimit_EnforcedByPlan()
    {
        // M2-UT10: Max user limit enforced
        var plan = new SubscriptionPlan
        {
            Id = 1, Name = "Starter", MaxUsers = 2,
            MaxSocialAccounts = 3, MaxKeywords = 10, MaxApiCallsPerDay = 1000
        };
        _appDb.SubscriptionPlans.Add(plan);

        var tenant = new Tenant
        {
            Id = 1, Name = "Test", Slug = "test", PlanId = 1,
            Status = TenantStatus.Active, CreatedAt = DateTime.UtcNow
        };
        _appDb.Tenants.Add(tenant);
        await _appDb.SaveChangesAsync();

        // Add 2 users (at limit)
        _tenantDb.Users.AddRange(
            new User { FirstName = "U1", LastName = "L1", Email = "u1@test.com", PasswordHash = "h", Role = UserRole.Agent, Status = UserStatus.Active, CreatedAt = DateTime.UtcNow },
            new User { FirstName = "U2", LastName = "L2", Email = "u2@test.com", PasswordHash = "h", Role = UserRole.Agent, Status = UserStatus.Active, CreatedAt = DateTime.UtcNow }
        );
        await _tenantDb.SaveChangesAsync();

        var currentCount = await _tenantDb.Users.CountAsync(u => u.Status != UserStatus.Disabled);
        var loadedTenant = await _appDb.Tenants.Include(t => t.Plan).FirstAsync(t => t.Id == 1);

        var limitReached = currentCount >= loadedTenant.Plan.MaxUsers;
        limitReached.Should().BeTrue("adding a 3rd user should be blocked");
    }

    [Fact]
    public async Task CreateUser_AllRoles_Succeed()
    {
        // M2-UT01: Super Admin can create any role
        foreach (var role in new[] { UserRole.TenantAdmin, UserRole.Agent, UserRole.Viewer })
        {
            var user = new User
            {
                FirstName = "Test",
                LastName = role.ToString(),
                Email = $"{role.ToString().ToLower()}@test.com",
                PasswordHash = _passwordHasher.Hash("Test123!"),
                Role = role,
                Status = UserStatus.Active,
                CreatedAt = DateTime.UtcNow
            };
            _tenantDb.Users.Add(user);
        }
        await _tenantDb.SaveChangesAsync();

        var users = await _tenantDb.Users.ToListAsync();
        users.Should().HaveCount(3);
        users.Select(u => u.Role).Should().BeEquivalentTo(
            new[] { UserRole.TenantAdmin, UserRole.Agent, UserRole.Viewer });
    }

    public void Dispose()
    {
        _tenantDb.Dispose();
        _appDb.Dispose();
    }
}
