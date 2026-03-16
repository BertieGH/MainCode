using System.Security.Claims;
using LeadPulse.Application.Interfaces;
using LeadPulse.Domain.Exceptions;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;

namespace LeadPulse.Infrastructure.Middleware;

public class TenantResolutionMiddleware
{
    private readonly RequestDelegate _next;
    private readonly ILogger<TenantResolutionMiddleware> _logger;

    public TenantResolutionMiddleware(RequestDelegate next, ILogger<TenantResolutionMiddleware> logger)
    {
        _next = next;
        _logger = logger;
    }

    public async Task InvokeAsync(HttpContext context, ITenantContext tenantContext, ITenantDbResolver resolver)
    {
        // Skip tenant resolution for auth endpoints and health checks
        var path = context.Request.Path.Value?.ToLower();
        if (path != null && (path.StartsWith("/api/auth") || path.StartsWith("/health")))
        {
            await _next(context);
            return;
        }

        int? tenantId = null;

        // Super Admin can override via X-Tenant-Id header (impersonation)
        if (context.Request.Headers.TryGetValue("X-Tenant-Id", out var headerTenantId)
            && int.TryParse(headerTenantId, out var overrideTenantId))
        {
            var role = context.User.FindFirstValue(ClaimTypes.Role);
            if (role == "SuperAdmin")
            {
                tenantId = overrideTenantId;
                _logger.LogInformation("Super Admin impersonating tenant {TenantId}", tenantId);
            }
        }

        // Otherwise extract from JWT claims
        if (!tenantId.HasValue)
        {
            var tenantClaim = context.User.FindFirstValue("tenantId");
            if (int.TryParse(tenantClaim, out var claimTenantId))
            {
                tenantId = claimTenantId;
            }
        }

        if (tenantId.HasValue)
        {
            try
            {
                // Validate tenant is active (this will throw if suspended/not found)
                await resolver.GetConnectionStringAsync(tenantId.Value);
                tenantContext.TenantId = tenantId.Value;
            }
            catch (TenantSuspendedException)
            {
                context.Response.StatusCode = 403;
                await context.Response.WriteAsJsonAsync(new { error = "Tenant suspended" });
                return;
            }
            catch (TenantNotFoundException)
            {
                context.Response.StatusCode = 404;
                await context.Response.WriteAsJsonAsync(new { error = "Tenant not found" });
                return;
            }
        }

        await _next(context);
    }
}
