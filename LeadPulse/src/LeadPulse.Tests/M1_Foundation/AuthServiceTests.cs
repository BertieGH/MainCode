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
/// M1-UT07, M1-UT08: Authentication tests
/// </summary>
public class AuthServiceTests : IDisposable
{
    private readonly AppDbContext _appDb;
    private readonly PasswordHasher _passwordHasher;
    private readonly JwtTokenService _jwtService;
    private readonly IConfiguration _configuration;

    public AuthServiceTests()
    {
        var options = new DbContextOptionsBuilder<AppDbContext>()
            .UseInMemoryDatabase(Guid.NewGuid().ToString())
            .Options;

        _appDb = new AppDbContext(options);
        _passwordHasher = new PasswordHasher();

        _configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Jwt:Secret"] = "LeadPulse-JWT-Secret-Key-Change-In-Production-Min32Chars!",
                ["Jwt:Issuer"] = "LeadPulse",
                ["Jwt:Audience"] = "LeadPulse",
                ["Jwt:ExpiryHours"] = "8",
                ["TenantDb:DefaultPassword"] = "testpassword"
            })
            .Build();

        _jwtService = new JwtTokenService(_configuration);
    }

    [Fact]
    public async Task LoginPlatformUser_Succeeds_WithValidCredentials()
    {
        // M1-UT07: Super Admin login uses App DB PlatformUsers
        var user = new PlatformUser
        {
            Email = "admin@leadpulse.com",
            PasswordHash = _passwordHasher.Hash("Admin123!"),
            FirstName = "Super",
            LastName = "Admin",
            Status = PlatformUserStatus.Active,
            CreatedAt = DateTime.UtcNow
        };
        _appDb.PlatformUsers.Add(user);
        await _appDb.SaveChangesAsync();

        var tenantResolver = new TenantDbResolver(_appDb, _configuration, Mock.Of<ILogger<TenantDbResolver>>());
        var tenantDbFactory = new TenantDbContextFactory(tenantResolver, Mock.Of<ILogger<TenantDbContextFactory>>());

        var authService = new AuthService(
            _appDb, tenantDbFactory, _passwordHasher, _jwtService, Mock.Of<ILogger<AuthService>>());

        var result = await authService.LoginPlatformUserAsync("admin@leadpulse.com", "Admin123!");

        result.Success.Should().BeTrue();
        result.Token.Should().NotBeNullOrEmpty();
        result.Role.Should().Be("SuperAdmin");
        result.TenantId.Should().BeNull("Super Admin is not tied to a tenant");
    }

    [Fact]
    public async Task LoginPlatformUser_Fails_WithInvalidPassword()
    {
        var user = new PlatformUser
        {
            Email = "admin@leadpulse.com",
            PasswordHash = _passwordHasher.Hash("Admin123!"),
            Status = PlatformUserStatus.Active,
            CreatedAt = DateTime.UtcNow
        };
        _appDb.PlatformUsers.Add(user);
        await _appDb.SaveChangesAsync();

        var tenantResolver = new TenantDbResolver(_appDb, _configuration, Mock.Of<ILogger<TenantDbResolver>>());
        var tenantDbFactory = new TenantDbContextFactory(tenantResolver, Mock.Of<ILogger<TenantDbContextFactory>>());

        var authService = new AuthService(
            _appDb, tenantDbFactory, _passwordHasher, _jwtService, Mock.Of<ILogger<AuthService>>());

        var result = await authService.LoginPlatformUserAsync("admin@leadpulse.com", "WrongPassword");

        result.Success.Should().BeFalse();
        result.Error.Should().Be("Invalid credentials");
    }

    [Fact]
    public async Task LoginPlatformUser_Fails_WhenDisabled()
    {
        var user = new PlatformUser
        {
            Email = "disabled@leadpulse.com",
            PasswordHash = _passwordHasher.Hash("Admin123!"),
            Status = PlatformUserStatus.Disabled,
            CreatedAt = DateTime.UtcNow
        };
        _appDb.PlatformUsers.Add(user);
        await _appDb.SaveChangesAsync();

        var tenantResolver = new TenantDbResolver(_appDb, _configuration, Mock.Of<ILogger<TenantDbResolver>>());
        var tenantDbFactory = new TenantDbContextFactory(tenantResolver, Mock.Of<ILogger<TenantDbContextFactory>>());

        var authService = new AuthService(
            _appDb, tenantDbFactory, _passwordHasher, _jwtService, Mock.Of<ILogger<AuthService>>());

        var result = await authService.LoginPlatformUserAsync("disabled@leadpulse.com", "Admin123!");

        result.Success.Should().BeFalse();
        result.Error.Should().Be("Account disabled");
    }

    public void Dispose()
    {
        _appDb.Dispose();
    }
}
