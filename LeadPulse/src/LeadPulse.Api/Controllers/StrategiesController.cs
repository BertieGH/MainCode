using System.Text.Json;
using LeadPulse.Application.DTOs;
using LeadPulse.Application.Interfaces;
using LeadPulse.Domain.Authorization;
using LeadPulse.Domain.Entities.Tenant;
using LeadPulse.Infrastructure.Authorization;
using LeadPulse.Infrastructure.Data;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace LeadPulse.Api.Controllers;

[ApiController]
[Route("api/strategies")]
[Authorize]
[HasPermission(Permissions.ManageStrategies)]
public class StrategiesController : ControllerBase
{
    private readonly TenantDbContext _tenantDb;
    private readonly ITenantContext _tenantContext;
    private readonly IDailyListGenerator _dailyListGenerator;

    public StrategiesController(
        TenantDbContext tenantDb,
        ITenantContext tenantContext,
        IDailyListGenerator dailyListGenerator)
    {
        _tenantDb = tenantDb;
        _tenantContext = tenantContext;
        _dailyListGenerator = dailyListGenerator;
    }

    [HttpGet]
    public async Task<IActionResult> GetAll()
    {
        var strategies = await _tenantDb.Strategies
            .OrderByDescending(s => s.CreatedAt)
            .ToListAsync();

        return Ok(strategies.Select(MapToResponse));
    }

    [HttpGet("{id}")]
    public async Task<IActionResult> GetById(int id)
    {
        var strategy = await _tenantDb.Strategies.FindAsync(id);
        if (strategy == null) return NotFound();
        return Ok(MapToResponse(strategy));
    }

    [HttpPost]
    public async Task<IActionResult> Create([FromBody] CreateStrategyRequest request)
    {
        var strategy = new Strategy
        {
            Name = request.Name,
            TargetCategories = request.TargetCategories != null ? JsonSerializer.Serialize(request.TargetCategories) : null,
            TargetStates = request.TargetStates != null ? JsonSerializer.Serialize(request.TargetStates) : null,
            TargetZipCodes = request.TargetZipCodes != null ? JsonSerializer.Serialize(request.TargetZipCodes) : null,
            Radius = request.Radius,
            MinScore = request.MinScore,
            MinUrgency = request.MinUrgency,
            MaxDailyProspects = request.MaxDailyProspects,
            KeywordBoosts = request.KeywordBoosts != null ? JsonSerializer.Serialize(request.KeywordBoosts) : null,
            IsActive = true,
            CreatedAt = DateTime.UtcNow
        };

        _tenantDb.Strategies.Add(strategy);
        await _tenantDb.SaveChangesAsync();

        return CreatedAtAction(nameof(GetById), new { id = strategy.Id }, MapToResponse(strategy));
    }

    [HttpPut("{id}")]
    public async Task<IActionResult> Update(int id, [FromBody] UpdateStrategyRequest request)
    {
        var strategy = await _tenantDb.Strategies.FindAsync(id);
        if (strategy == null) return NotFound();

        strategy.Name = request.Name;
        strategy.TargetCategories = request.TargetCategories != null ? JsonSerializer.Serialize(request.TargetCategories) : null;
        strategy.TargetStates = request.TargetStates != null ? JsonSerializer.Serialize(request.TargetStates) : null;
        strategy.TargetZipCodes = request.TargetZipCodes != null ? JsonSerializer.Serialize(request.TargetZipCodes) : null;
        strategy.Radius = request.Radius;
        strategy.MinScore = request.MinScore;
        strategy.MinUrgency = request.MinUrgency;
        strategy.MaxDailyProspects = request.MaxDailyProspects;
        strategy.KeywordBoosts = request.KeywordBoosts != null ? JsonSerializer.Serialize(request.KeywordBoosts) : null;
        strategy.IsActive = request.IsActive;
        strategy.UpdatedAt = DateTime.UtcNow;

        await _tenantDb.SaveChangesAsync();
        return Ok(MapToResponse(strategy));
    }

    [HttpDelete("{id}")]
    public async Task<IActionResult> Delete(int id)
    {
        var strategy = await _tenantDb.Strategies.FindAsync(id);
        if (strategy == null) return NotFound();

        _tenantDb.Strategies.Remove(strategy);
        await _tenantDb.SaveChangesAsync();
        return Ok(new { message = "Strategy deleted" });
    }

    [HttpPost("{id}/generate")]
    public async Task<IActionResult> GenerateDailyList(int id)
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var strategy = await _tenantDb.Strategies.FindAsync(id);
        if (strategy == null) return NotFound();

        await _dailyListGenerator.GenerateDailyListAsync(_tenantContext.TenantId.Value, id);

        return Ok(new { message = "Daily list generated" });
    }

    private static StrategyResponse MapToResponse(Strategy s)
    {
        return new StrategyResponse
        {
            Id = s.Id,
            Name = s.Name,
            TargetCategories = DeserializeList(s.TargetCategories),
            TargetStates = DeserializeList(s.TargetStates),
            TargetZipCodes = DeserializeList(s.TargetZipCodes),
            Radius = s.Radius,
            MinScore = s.MinScore,
            MinUrgency = s.MinUrgency,
            MaxDailyProspects = s.MaxDailyProspects,
            KeywordBoosts = DeserializeDict(s.KeywordBoosts),
            IsActive = s.IsActive,
            CreatedAt = s.CreatedAt,
            UpdatedAt = s.UpdatedAt
        };
    }

    private static List<string>? DeserializeList(string? json)
    {
        if (string.IsNullOrEmpty(json)) return null;
        try { return JsonSerializer.Deserialize<List<string>>(json); }
        catch { return null; }
    }

    private static Dictionary<string, int>? DeserializeDict(string? json)
    {
        if (string.IsNullOrEmpty(json)) return null;
        try { return JsonSerializer.Deserialize<Dictionary<string, int>>(json); }
        catch { return null; }
    }
}
