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
[Route("api/daily-lists")]
[Authorize]
[HasPermission(Permissions.ViewProspects)]
public class DailyListsController : ControllerBase
{
    private readonly TenantDbContext _tenantDb;

    public DailyListsController(TenantDbContext tenantDb)
    {
        _tenantDb = tenantDb;
    }

    [HttpGet]
    public async Task<IActionResult> GetAll([FromQuery] int? strategyId = null, [FromQuery] int limit = 30)
    {
        var query = _tenantDb.DailyLists
            .Include(d => d.Strategy)
            .AsQueryable();

        if (strategyId.HasValue)
            query = query.Where(d => d.StrategyId == strategyId.Value);

        var lists = await query
            .OrderByDescending(d => d.GeneratedDate)
            .Take(limit)
            .ToListAsync();

        return Ok(lists.Select(d => new DailyListResponse
        {
            Id = d.Id,
            StrategyId = d.StrategyId,
            StrategyName = d.Strategy.Name,
            GeneratedDate = d.GeneratedDate,
            ProspectCount = d.ProspectCount,
            CreatedAt = d.CreatedAt
        }));
    }

    [HttpGet("{id}")]
    public async Task<IActionResult> GetById(int id)
    {
        var list = await _tenantDb.DailyLists
            .Include(d => d.Strategy)
            .Include(d => d.Items)
                .ThenInclude(i => i.Prospect)
                    .ThenInclude(p => p.ProspectSignals)
                        .ThenInclude(ps => ps.Signal)
            .FirstOrDefaultAsync(d => d.Id == id);

        if (list == null) return NotFound();

        return Ok(new DailyListResponse
        {
            Id = list.Id,
            StrategyId = list.StrategyId,
            StrategyName = list.Strategy.Name,
            GeneratedDate = list.GeneratedDate,
            ProspectCount = list.ProspectCount,
            Items = list.Items.Select(i => new DailyListItemResponse
            {
                Id = i.Id,
                ProspectId = i.ProspectId,
                Prospect = MapProspect(i.Prospect),
                Status = i.Status.ToString(),
                ViewedAt = i.ViewedAt,
                ContactedAt = i.ContactedAt
            }).ToList(),
            CreatedAt = list.CreatedAt
        });
    }

    [HttpPut("items/{itemId}/status")]
    public async Task<IActionResult> UpdateItemStatus(int itemId, [FromBody] UpdateDailyListItemStatusRequest request)
    {
        var item = await _tenantDb.DailyListItems
            .Include(i => i.Prospect)
            .FirstOrDefaultAsync(i => i.Id == itemId);

        if (item == null) return NotFound();

        if (!Enum.TryParse<ProspectStatus>(request.Status, true, out var newStatus))
            return BadRequest(new { error = $"Invalid status: {request.Status}" });

        item.Status = newStatus;
        if (newStatus == ProspectStatus.Viewed && item.ViewedAt == null)
            item.ViewedAt = DateTime.UtcNow;
        if (newStatus == ProspectStatus.Contacted && item.ContactedAt == null)
            item.ContactedAt = DateTime.UtcNow;

        // Also update the prospect status
        item.Prospect.Status = newStatus;
        item.Prospect.UpdatedAt = DateTime.UtcNow;

        await _tenantDb.SaveChangesAsync();
        return Ok(new { message = "Status updated" });
    }

    [HttpGet("today")]
    public async Task<IActionResult> GetToday([FromQuery] int? strategyId = null)
    {
        var today = DateTime.UtcNow.Date;
        var query = _tenantDb.DailyLists
            .Include(d => d.Strategy)
            .Include(d => d.Items)
                .ThenInclude(i => i.Prospect)
                    .ThenInclude(p => p.ProspectSignals)
                        .ThenInclude(ps => ps.Signal)
            .Where(d => d.GeneratedDate == today);

        if (strategyId.HasValue)
            query = query.Where(d => d.StrategyId == strategyId.Value);

        var list = await query.FirstOrDefaultAsync();
        if (list == null) return Ok(new { message = "No daily list for today yet" });

        return Ok(new DailyListResponse
        {
            Id = list.Id,
            StrategyId = list.StrategyId,
            StrategyName = list.Strategy.Name,
            GeneratedDate = list.GeneratedDate,
            ProspectCount = list.ProspectCount,
            Items = list.Items.Select(i => new DailyListItemResponse
            {
                Id = i.Id,
                ProspectId = i.ProspectId,
                Prospect = MapProspect(i.Prospect),
                Status = i.Status.ToString(),
                ViewedAt = i.ViewedAt,
                ContactedAt = i.ContactedAt
            }).ToList(),
            CreatedAt = list.CreatedAt
        });
    }

    private static ProspectResponse MapProspect(Domain.Entities.Tenant.Prospect p)
    {
        return new ProspectResponse
        {
            Id = p.Id,
            Name = p.Name,
            Phone = p.Phone,
            Email = p.Email,
            City = p.City,
            State = p.State,
            Zip = p.Zip,
            Company = p.Company,
            CompositeScore = p.CompositeScore,
            Urgency = p.Urgency.ToString(),
            Category = p.Category,
            Platform = p.Platform,
            SignalSnippet = p.SignalSnippet,
            PostUrl = p.ProspectSignals?.Select(ps => ps.Signal?.PostUrl).FirstOrDefault(u => u != null),
            Status = p.Status.ToString(),
            CreatedAt = p.CreatedAt
        };
    }
}
