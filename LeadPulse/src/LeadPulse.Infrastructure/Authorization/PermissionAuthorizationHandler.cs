using System.Security.Claims;
using System.Text.Json;
using LeadPulse.Application.Interfaces;
using LeadPulse.Domain.Authorization;
using LeadPulse.Infrastructure.Data;
using Microsoft.AspNetCore.Authorization;
using Microsoft.EntityFrameworkCore;

namespace LeadPulse.Infrastructure.Authorization;

public class PermissionRequirement : IAuthorizationRequirement
{
    public string Permission { get; }
    public PermissionRequirement(string permission) => Permission = permission;
}

public class PermissionAuthorizationHandler : AuthorizationHandler<PermissionRequirement>
{
    private readonly ITenantContext _tenantContext;
    private readonly TenantDbContext _tenantDb;

    public PermissionAuthorizationHandler(ITenantContext tenantContext, TenantDbContext tenantDb)
    {
        _tenantContext = tenantContext;
        _tenantDb = tenantDb;
    }

    protected override async Task HandleRequirementAsync(
        AuthorizationHandlerContext context, PermissionRequirement requirement)
    {
        var roleClaim = context.User.FindFirstValue(ClaimTypes.Role)
            ?? context.User.FindFirstValue("role");

        if (roleClaim == null)
            return;

        // Super Admin has all permissions
        if (roleClaim == "SuperAdmin")
        {
            context.Succeed(requirement);
            return;
        }

        // Check default role permissions first
        var defaultPermissions = Permissions.GetDefaultPermissions(roleClaim);
        if (defaultPermissions.Contains(requirement.Permission))
        {
            // Check if there's a granular override in the user's Permissions JSON
            if (_tenantContext.TenantId.HasValue)
            {
                var userIdStr = context.User.FindFirstValue(ClaimTypes.NameIdentifier);
                if (int.TryParse(userIdStr, out var userId))
                {
                    var user = await _tenantDb.Users
                        .AsNoTracking()
                        .FirstOrDefaultAsync(u => u.Id == userId);

                    if (user?.Permissions != null)
                    {
                        var overrides = JsonSerializer.Deserialize<Dictionary<string, bool>>(user.Permissions);
                        if (overrides != null && overrides.TryGetValue(requirement.Permission, out var allowed) && !allowed)
                        {
                            return; // Permission explicitly revoked
                        }
                    }
                }
            }

            context.Succeed(requirement);
            return;
        }

        // Check if there's a granular grant (permission not in default but explicitly granted)
        if (_tenantContext.TenantId.HasValue)
        {
            var userIdStr = context.User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (int.TryParse(userIdStr, out var userId))
            {
                var user = await _tenantDb.Users
                    .AsNoTracking()
                    .FirstOrDefaultAsync(u => u.Id == userId);

                if (user?.Permissions != null)
                {
                    var overrides = JsonSerializer.Deserialize<Dictionary<string, bool>>(user.Permissions);
                    if (overrides != null && overrides.TryGetValue(requirement.Permission, out var allowed) && allowed)
                    {
                        context.Succeed(requirement);
                    }
                }
            }
        }
    }
}
