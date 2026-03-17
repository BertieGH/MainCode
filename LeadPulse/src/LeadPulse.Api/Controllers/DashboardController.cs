using LeadPulse.Application.DTOs;
using LeadPulse.Domain.Enums;
using LeadPulse.Infrastructure.Data;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace LeadPulse.Api.Controllers;

[ApiController]
[Route("api/dashboard")]
[Authorize]
public class DashboardController : ControllerBase
{
    private readonly TenantDbContext _tenantDb;

    public DashboardController(TenantDbContext tenantDb)
    {
        _tenantDb = tenantDb;
    }

    [HttpGet]
    public async Task<IActionResult> GetDashboard()
    {
        var today = DateTime.UtcNow.Date;
        var tomorrow = today.AddDays(1);

        var newProspectsToday = await _tenantDb.Prospects
            .CountAsync(p => p.CreatedAt >= today && p.CreatedAt < tomorrow);

        var callsMadeToday = await _tenantDb.CallLogs
            .CountAsync(c => c.CreatedAt >= today && c.CreatedAt < tomorrow);

        var totalContacted = await _tenantDb.Prospects
            .CountAsync(p => p.Status == ProspectStatus.Contacted || p.Status == ProspectStatus.Converted);
        var totalConverted = await _tenantDb.Prospects
            .CountAsync(p => p.Status == ProspectStatus.Converted);
        var conversionRate = totalContacted > 0
            ? Math.Round((decimal)totalConverted / totalContacted * 100, 1)
            : 0m;

        var activeSignals = await _tenantDb.Signals
            .CountAsync(s => s.DetectedAt >= today.AddDays(-7));

        // Prior day comparison for trends
        var yesterday = today.AddDays(-1);
        var prevProspects = await _tenantDb.Prospects
            .CountAsync(p => p.CreatedAt >= yesterday && p.CreatedAt < today);
        var prevCalls = await _tenantDb.CallLogs
            .CountAsync(c => c.CreatedAt >= yesterday && c.CreatedAt < today);
        var prevSignals = await _tenantDb.Signals
            .CountAsync(s => s.DetectedAt >= today.AddDays(-14) && s.DetectedAt < today.AddDays(-7));

        // Previous week conversion rate
        var prevContacted = await _tenantDb.Prospects
            .CountAsync(p => p.CreatedAt < today.AddDays(-7) &&
                (p.Status == ProspectStatus.Contacted || p.Status == ProspectStatus.Converted));
        var prevConverted = await _tenantDb.Prospects
            .CountAsync(p => p.CreatedAt < today.AddDays(-7) &&
                p.Status == ProspectStatus.Converted);
        var prevConversionRate = prevContacted > 0
            ? Math.Round((decimal)prevConverted / prevContacted * 100, 1)
            : 0m;

        static decimal CalcTrend(int current, int prior)
            => prior > 0 ? Math.Round((decimal)(current - prior) / prior * 100, 1) : 0;

        var topProspects = await _tenantDb.Prospects
            .Where(p => p.Status != ProspectStatus.Dismissed && p.Status != ProspectStatus.Converted)
            .OrderByDescending(p => p.CompositeScore)
            .Take(5)
            .Select(p => new TopProspectDto
            {
                Id = p.Id,
                Name = p.Name,
                CompositeScore = p.CompositeScore,
                Urgency = p.Urgency.ToString(),
                Category = p.Category,
                Platform = p.Platform
            })
            .ToListAsync();

        var followUps = await _tenantDb.CallLogs
            .Include(c => c.Prospect)
            .Where(c => c.FollowUpDate != null && c.FollowUpDate >= today)
            .OrderBy(c => c.FollowUpDate)
            .ThenBy(c => c.FollowUpTime)
            .Take(10)
            .Select(c => new FollowUpReminderDto
            {
                CallLogId = c.Id,
                ProspectId = c.ProspectId,
                ProspectName = c.Prospect.Name,
                FollowUpDate = c.FollowUpDate!.Value,
                FollowUpTime = c.FollowUpTime,
                Notes = c.Notes
            })
            .ToListAsync();

        var recentActivity = await _tenantDb.ActivityLogs
            .Include(a => a.User)
            .OrderByDescending(a => a.CreatedAt)
            .Take(20)
            .Select(a => new ActivityDto
            {
                Id = a.Id,
                ActionType = a.ActionType,
                Description = a.Description,
                UserName = a.User != null ? a.User.FirstName + " " + a.User.LastName : null,
                CreatedAt = a.CreatedAt
            })
            .ToListAsync();

        return Ok(new DashboardResponse
        {
            NewProspectsToday = newProspectsToday,
            CallsMadeToday = callsMadeToday,
            ConversionRate = conversionRate,
            ActiveSignals = activeSignals,
            ProspectsTrend = CalcTrend(newProspectsToday, prevProspects),
            CallsTrend = CalcTrend(callsMadeToday, prevCalls),
            ConversionTrend = prevConversionRate > 0
                ? Math.Round(conversionRate - prevConversionRate, 1)
                : 0,
            SignalsTrend = CalcTrend(activeSignals, prevSignals),
            TopProspects = topProspects,
            FollowUpReminders = followUps,
            RecentActivity = recentActivity
        });
    }
}
