using LeadPulse.Domain.Entities.App;
using LeadPulse.Infrastructure.Data;
using Microsoft.AspNetCore.Http;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace LeadPulse.Infrastructure.Middleware;

public class RateLimitingMiddleware
{
    private readonly RequestDelegate _next;
    private readonly ILogger<RateLimitingMiddleware> _logger;

    public RateLimitingMiddleware(RequestDelegate next, ILogger<RateLimitingMiddleware> logger)
    {
        _next = next;
        _logger = logger;
    }

    public async Task InvokeAsync(HttpContext context, AppDbContext appDb)
    {
        var tenantIdClaim = context.User.FindFirst("tenantId")?.Value;
        if (string.IsNullOrEmpty(tenantIdClaim) || !int.TryParse(tenantIdClaim, out var tenantId))
        {
            await _next(context);
            return;
        }

        var today = DateTime.UtcNow.Date;

        // Get tenant plan limit
        var tenant = await appDb.Tenants
            .Include(t => t.Plan)
            .FirstOrDefaultAsync(t => t.Id == tenantId);

        if (tenant == null)
        {
            await _next(context);
            return;
        }

        var maxCalls = tenant.Plan.MaxApiCallsPerDay;

        // Get or create today's rate limit record
        var rateLimit = await appDb.ApiRateLimits
            .FirstOrDefaultAsync(r => r.TenantId == tenantId && r.Date == today);

        if (rateLimit == null)
        {
            rateLimit = new ApiRateLimit
            {
                TenantId = tenantId,
                Date = today,
                CallCount = 0
            };
            appDb.ApiRateLimits.Add(rateLimit);
        }

        if (rateLimit.CallCount >= maxCalls)
        {
            _logger.LogWarning("Rate limit exceeded for tenant {TenantId}: {Count}/{Max}",
                tenantId, rateLimit.CallCount, maxCalls);

            context.Response.StatusCode = 429;
            context.Response.Headers.Append("Retry-After", "86400");
            await context.Response.WriteAsJsonAsync(new
            {
                error = "API rate limit exceeded",
                limit = maxCalls,
                resetAt = today.AddDays(1).ToString("o")
            });
            return;
        }

        rateLimit.CallCount++;
        await appDb.SaveChangesAsync();

        await _next(context);
    }
}
