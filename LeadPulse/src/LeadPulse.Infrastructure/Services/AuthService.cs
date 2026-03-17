using LeadPulse.Application.DTOs;
using LeadPulse.Application.Interfaces;
using LeadPulse.Domain.Enums;
using LeadPulse.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace LeadPulse.Infrastructure.Services;

public class AuthService : IAuthService
{
    private readonly AppDbContext _appDb;
    private readonly TenantDbContextFactory _tenantDbFactory;
    private readonly IPasswordHasher _passwordHasher;
    private readonly JwtTokenService _jwtService;
    private readonly ILogger<AuthService> _logger;

    public AuthService(
        AppDbContext appDb,
        TenantDbContextFactory tenantDbFactory,
        IPasswordHasher passwordHasher,
        JwtTokenService jwtService,
        ILogger<AuthService> logger)
    {
        _appDb = appDb;
        _tenantDbFactory = tenantDbFactory;
        _passwordHasher = passwordHasher;
        _jwtService = jwtService;
        _logger = logger;
    }

    public async Task<AuthResult> LoginPlatformUserAsync(string email, string password)
    {
        var user = await _appDb.PlatformUsers
            .FirstOrDefaultAsync(u => u.Email == email);

        if (user == null)
            return AuthResult.Failed("Invalid credentials");

        if (user.Status == PlatformUserStatus.Disabled)
            return AuthResult.Failed("Account disabled");

        if (!_passwordHasher.Verify(password, user.PasswordHash))
            return AuthResult.Failed("Invalid credentials");

        user.LastLoginAt = DateTime.UtcNow;
        await _appDb.SaveChangesAsync();

        var token = _jwtService.GenerateToken(user.Id, null, "SuperAdmin", user.Email);

        _logger.LogInformation("Platform user {Email} logged in", email);

        return AuthResult.Succeeded(token, user.Id, null, "SuperAdmin");
    }

    public async Task<AuthResult> LoginTenantUserAsync(int tenantId, string email, string password)
    {
        var tenant = await _appDb.Tenants.FindAsync(tenantId);
        if (tenant == null)
            return AuthResult.Failed("Tenant not found");

        if (tenant.Status == TenantStatus.Suspended)
            return AuthResult.Failed("Tenant suspended");

        if (tenant.Status != TenantStatus.Active)
            return AuthResult.Failed("Tenant not active");

        await using var tenantDb = await _tenantDbFactory.CreateContextAsync(tenantId);

        var user = await tenantDb.Users
            .FirstOrDefaultAsync(u => u.Email == email);

        if (user == null)
            return AuthResult.Failed("Invalid credentials");

        if (user.Status == UserStatus.Disabled)
            return AuthResult.Failed("Account disabled");

        if (!_passwordHasher.Verify(password, user.PasswordHash))
            return AuthResult.Failed("Invalid credentials");

        user.LastLoginAt = DateTime.UtcNow;
        await tenantDb.SaveChangesAsync();

        var token = _jwtService.GenerateToken(user.Id, tenantId, user.Role.ToString(), user.Email, tenant.Name);

        _logger.LogInformation("Tenant user {Email} logged in to tenant {TenantId}", email, tenantId);

        return AuthResult.Succeeded(token, user.Id, tenantId, user.Role.ToString(), user.ForcePasswordChange);
    }
}
