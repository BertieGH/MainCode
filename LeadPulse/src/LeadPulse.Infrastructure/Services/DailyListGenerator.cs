using System.Text.Json;
using LeadPulse.Application.Interfaces;
using LeadPulse.Domain.Entities.Tenant;
using LeadPulse.Domain.Enums;
using LeadPulse.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace LeadPulse.Infrastructure.Services;

public class DailyListGenerator : IDailyListGenerator
{
    private readonly TenantDbContextFactory _tenantDbFactory;
    private readonly ILogger<DailyListGenerator> _logger;

    public DailyListGenerator(
        TenantDbContextFactory tenantDbFactory,
        ILogger<DailyListGenerator> logger)
    {
        _tenantDbFactory = tenantDbFactory;
        _logger = logger;
    }

    public async Task GenerateDailyListAsync(int tenantId, int strategyId)
    {
        await using var db = await _tenantDbFactory.CreateContextAsync(tenantId);

        var strategy = await db.Strategies.FindAsync(strategyId);
        if (strategy == null)
        {
            _logger.LogWarning("Strategy {StrategyId} not found for tenant {TenantId}", strategyId, tenantId);
            return;
        }

        var today = DateTime.UtcNow.Date;

        // Remove existing daily list for today so it can be regenerated with latest strategy settings
        var existing = await db.DailyLists
            .Include(d => d.Items)
            .FirstOrDefaultAsync(d => d.StrategyId == strategyId && d.GeneratedDate == today);

        if (existing != null)
        {
            db.DailyListItems.RemoveRange(existing.Items);
            db.DailyLists.Remove(existing);
            await db.SaveChangesAsync();
            _logger.LogInformation("Replacing daily list for strategy {StrategyId} on {Date}", strategyId, today);
        }

        // Build query with strategy filters
        var query = db.Prospects
            .Where(p => p.Status != ProspectStatus.Dismissed && p.Status != ProspectStatus.Converted);

        // Min score filter
        query = query.Where(p => p.CompositeScore >= strategy.MinScore);

        // Urgency filter
        if (!string.IsNullOrEmpty(strategy.MinUrgency) && Enum.TryParse<Urgency>(strategy.MinUrgency, true, out var minUrgency))
        {
            query = query.Where(p => p.Urgency >= minUrgency);
        }

        // Load candidates for in-memory filtering of JSON fields
        var candidates = await query
            .OrderByDescending(p => p.CompositeScore)
            .ToListAsync();

        // Category filter (JSON array in strategy)
        var targetCategories = DeserializeList(strategy.TargetCategories);
        if (targetCategories != null && targetCategories.Count > 0)
        {
            candidates = candidates
                .Where(p => !string.IsNullOrEmpty(p.Category) && targetCategories.Contains(p.Category, StringComparer.OrdinalIgnoreCase))
                .ToList();
        }

        // State filter — include prospects with no state data (can't determine exclusion)
        var targetStates = DeserializeList(strategy.TargetStates);
        if (targetStates != null && targetStates.Count > 0)
        {
            candidates = candidates
                .Where(p => string.IsNullOrEmpty(p.State) || targetStates.Contains(p.State, StringComparer.OrdinalIgnoreCase))
                .ToList();
        }

        // Zip code filter — include prospects with no zip data
        var targetZips = DeserializeList(strategy.TargetZipCodes);
        if (targetZips != null && targetZips.Count > 0)
        {
            candidates = candidates
                .Where(p => string.IsNullOrEmpty(p.Zip) || targetZips.Contains(p.Zip))
                .ToList();
        }

        // Cap to max daily
        var selected = candidates.Take(strategy.MaxDailyProspects).ToList();

        // Create daily list
        var dailyList = new DailyList
        {
            StrategyId = strategyId,
            GeneratedDate = today,
            ProspectCount = selected.Count,
            CreatedAt = DateTime.UtcNow
        };

        db.DailyLists.Add(dailyList);
        await db.SaveChangesAsync();

        foreach (var prospect in selected)
        {
            db.DailyListItems.Add(new DailyListItem
            {
                DailyListId = dailyList.Id,
                ProspectId = prospect.Id,
                Status = ProspectStatus.New
            });
        }

        await db.SaveChangesAsync();

        _logger.LogInformation("Generated daily list with {Count} prospects for strategy {StrategyId}, tenant {TenantId}",
            selected.Count, strategyId, tenantId);
    }

    private static List<string>? DeserializeList(string? json)
    {
        if (string.IsNullOrEmpty(json)) return null;
        try { return JsonSerializer.Deserialize<List<string>>(json); }
        catch { return null; }
    }
}
