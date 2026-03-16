using LeadPulse.Application.DTOs;
using LeadPulse.Domain.Authorization;
using LeadPulse.Domain.Enums;
using LeadPulse.Infrastructure.Authorization;
using LeadPulse.Infrastructure.Data;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace LeadPulse.Api.Controllers;

[ApiController]
[Route("api/analytics")]
[Authorize]
[HasPermission(Permissions.ViewAnalytics)]
public class AnalyticsController : ControllerBase
{
    private readonly TenantDbContext _tenantDb;

    public AnalyticsController(TenantDbContext tenantDb)
    {
        _tenantDb = tenantDb;
    }

    [HttpGet]
    public async Task<IActionResult> GetAnalytics([FromQuery] int days = 30)
    {
        days = Math.Clamp(days, 1, 365);
        var since = DateTime.UtcNow.Date.AddDays(-days);

        // Signal volume by day
        var signals = await _tenantDb.Signals
            .Where(s => s.DetectedAt >= since)
            .GroupBy(s => s.DetectedAt.Date)
            .Select(g => new DailyCountDto { Date = g.Key, Count = g.Count() })
            .OrderBy(d => d.Date)
            .ToListAsync();

        // Category breakdown
        var totalProspects = await _tenantDb.Prospects.CountAsync(p => p.CreatedAt >= since);
        var categories = await _tenantDb.Prospects
            .Where(p => p.CreatedAt >= since && p.Category != null)
            .GroupBy(p => p.Category!)
            .Select(g => new CategoryBreakdownDto
            {
                Category = g.Key,
                Count = g.Count(),
                Percentage = totalProspects > 0 ? Math.Round((decimal)g.Count() / totalProspects * 100, 1) : 0
            })
            .OrderByDescending(c => c.Count)
            .ToListAsync();

        // Platform distribution
        var platforms = await _tenantDb.Signals
            .Where(s => s.DetectedAt >= since)
            .GroupBy(s => s.Platform)
            .Select(g => new PlatformDistributionDto { Platform = g.Key, Count = g.Count() })
            .OrderByDescending(p => p.Count)
            .ToListAsync();

        // Conversion funnel
        var funnel = new ConversionFunnelDto
        {
            TotalSignals = await _tenantDb.Signals.CountAsync(s => s.DetectedAt >= since),
            TotalProspects = totalProspects,
            Contacted = await _tenantDb.Prospects.CountAsync(p => p.CreatedAt >= since &&
                (p.Status == ProspectStatus.Contacted || p.Status == ProspectStatus.Converted)),
            Converted = await _tenantDb.Prospects.CountAsync(p => p.CreatedAt >= since &&
                p.Status == ProspectStatus.Converted)
        };

        // API costs
        var apiCosts = await _tenantDb.ApiUsageLogs
            .Where(a => a.Date >= since)
            .OrderByDescending(a => a.Date)
            .Take(50)
            .Select(a => new ApiCostDto
            {
                Service = a.Service,
                CallCount = a.CallCount,
                Cost = a.Cost,
                Date = a.Date
            })
            .ToListAsync();

        return Ok(new AnalyticsResponse
        {
            SignalVolume = signals,
            CategoryBreakdown = categories,
            PlatformDistribution = platforms,
            Funnel = funnel,
            ApiCosts = apiCosts
        });
    }

    [HttpGet("signal-volume")]
    public async Task<IActionResult> GetSignalVolume([FromQuery] int days = 7)
    {
        var since = DateTime.UtcNow.Date.AddDays(-days);

        var volume = await _tenantDb.Signals
            .Where(s => s.DetectedAt >= since)
            .GroupBy(s => s.DetectedAt.Date)
            .Select(g => new DailyCountDto { Date = g.Key, Count = g.Count() })
            .OrderBy(d => d.Date)
            .ToListAsync();

        return Ok(volume);
    }

    [HttpGet("funnel")]
    public async Task<IActionResult> GetFunnel([FromQuery] int days = 30)
    {
        var since = DateTime.UtcNow.Date.AddDays(-days);

        return Ok(new ConversionFunnelDto
        {
            TotalSignals = await _tenantDb.Signals.CountAsync(s => s.DetectedAt >= since),
            TotalProspects = await _tenantDb.Prospects.CountAsync(p => p.CreatedAt >= since),
            Contacted = await _tenantDb.Prospects.CountAsync(p => p.CreatedAt >= since &&
                (p.Status == ProspectStatus.Contacted || p.Status == ProspectStatus.Converted)),
            Converted = await _tenantDb.Prospects.CountAsync(p => p.CreatedAt >= since &&
                p.Status == ProspectStatus.Converted)
        });
    }
}
