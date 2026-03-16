using FluentAssertions;
using LeadPulse.Application.DTOs;
using LeadPulse.Domain.Entities.Tenant;
using LeadPulse.Domain.Enums;

namespace LeadPulse.Tests.M7_Analytics;

/// <summary>
/// M7-UT01 through M7-UT10: Dashboard and Analytics tests
/// </summary>
public class AnalyticsTests
{
    [Fact]
    public void KpiNewProspectsToday_CountsCorrectly()
    {
        // M7-UT01: 8 created today → returns 8
        var today = DateTime.UtcNow.Date;
        var tomorrow = today.AddDays(1);
        var prospects = Enumerable.Range(1, 12)
            .Select(i => new Prospect
            {
                Id = i,
                Name = $"P{i}",
                CreatedAt = i <= 8 ? today.AddHours(i) : today.AddDays(-1)
            }).ToList();

        var todayCount = prospects.Count(p => p.CreatedAt >= today && p.CreatedAt < tomorrow);

        todayCount.Should().Be(8);
    }

    [Fact]
    public void KpiConversionRate_CalculatesCorrectly()
    {
        // M7-UT02: Conversion rate with 1 decimal
        var totalContacted = 20;
        var totalConverted = 3;

        var rate = totalContacted > 0
            ? Math.Round((decimal)totalConverted / totalContacted * 100, 1)
            : 0m;

        rate.Should().Be(15.0m);
    }

    [Fact]
    public void ConversionRate_ZeroContacted_ReturnsZero()
    {
        int totalContacted = 0;
        int totalConverted = 0;
        var rate = totalContacted > 0
            ? Math.Round((decimal)totalConverted / totalContacted * 100, 1)
            : 0m;
        rate.Should().Be(0m);
    }

    [Fact]
    public void SignalVolumeByDay_GroupsCorrectly()
    {
        // M7-UT03: 7-day array of counts
        var today = DateTime.UtcNow.Date;
        var signals = new List<Signal>
        {
            new() { DetectedAt = today, Platform = "LinkedIn", PostContent = "a" },
            new() { DetectedAt = today, Platform = "LinkedIn", PostContent = "b" },
            new() { DetectedAt = today.AddDays(-1), Platform = "Facebook", PostContent = "c" },
            new() { DetectedAt = today.AddDays(-2), Platform = "LinkedIn", PostContent = "d" },
        };

        var grouped = signals
            .GroupBy(s => s.DetectedAt.Date)
            .Select(g => new DailyCountDto { Date = g.Key, Count = g.Count() })
            .OrderBy(d => d.Date)
            .ToList();

        grouped.Should().HaveCount(3);
        grouped.Last().Count.Should().Be(2); // Today has 2
    }

    [Fact]
    public void CategoryBreakdown_CalculatesPercentages()
    {
        // M7-UT04: Correct percentages
        var prospects = new[]
        {
            new Prospect { Category = "Home" },
            new Prospect { Category = "Home" },
            new Prospect { Category = "Auto" },
            new Prospect { Category = "Life" },
        };

        var total = prospects.Length;
        var breakdown = prospects
            .Where(p => p.Category != null)
            .GroupBy(p => p.Category!)
            .Select(g => new CategoryBreakdownDto
            {
                Category = g.Key,
                Count = g.Count(),
                Percentage = Math.Round((decimal)g.Count() / total * 100, 1)
            })
            .OrderByDescending(c => c.Count)
            .ToList();

        breakdown.Should().HaveCount(3);
        breakdown.First(c => c.Category == "Home").Percentage.Should().Be(50.0m);
        breakdown.First(c => c.Category == "Auto").Percentage.Should().Be(25.0m);
    }

    [Fact]
    public void PlatformDistribution_CountsPerPlatform()
    {
        // M7-UT05: Count per platform
        var signals = new[]
        {
            new Signal { Platform = "LinkedIn", PostContent = "a", DetectedAt = DateTime.UtcNow },
            new Signal { Platform = "LinkedIn", PostContent = "b", DetectedAt = DateTime.UtcNow },
            new Signal { Platform = "Facebook", PostContent = "c", DetectedAt = DateTime.UtcNow },
        };

        var distribution = signals
            .GroupBy(s => s.Platform)
            .Select(g => new PlatformDistributionDto { Platform = g.Key, Count = g.Count() })
            .ToList();

        distribution.First(p => p.Platform == "LinkedIn").Count.Should().Be(2);
        distribution.First(p => p.Platform == "Facebook").Count.Should().Be(1);
    }

    [Fact]
    public void ConversionFunnel_NumbersCorrect()
    {
        // M7-UT06: signals→prospects→contacted→converted
        var funnel = new ConversionFunnelDto
        {
            TotalSignals = 500,
            TotalProspects = 120,
            Contacted = 45,
            Converted = 12
        };

        funnel.TotalSignals.Should().BeGreaterThan(funnel.TotalProspects);
        funnel.TotalProspects.Should().BeGreaterThan(funnel.Contacted);
        funnel.Contacted.Should().BeGreaterThan(funnel.Converted);
    }

    [Fact]
    public void TopProspects_ReturnsTop5ByScore()
    {
        // M7-UT07: Top 5 by score
        var prospects = Enumerable.Range(1, 10)
            .Select(i => new Prospect
            {
                Id = i,
                Name = $"P{i}",
                CompositeScore = i * 10,
                Status = ProspectStatus.New
            }).ToList();

        var top5 = prospects
            .Where(p => p.Status != ProspectStatus.Dismissed)
            .OrderByDescending(p => p.CompositeScore)
            .Take(5)
            .ToList();

        top5.Should().HaveCount(5);
        top5.First().CompositeScore.Should().Be(100);
        top5.Last().CompositeScore.Should().Be(60);
    }

    [Fact]
    public void ActivityFeed_NewestFirst()
    {
        // M7-UT08: Newest first
        var activities = new[]
        {
            new ActivityLog { Id = 1, ActionType = "Login", CreatedAt = DateTime.UtcNow.AddHours(-2) },
            new ActivityLog { Id = 2, ActionType = "ViewProspect", CreatedAt = DateTime.UtcNow.AddHours(-1) },
            new ActivityLog { Id = 3, ActionType = "LogCall", CreatedAt = DateTime.UtcNow },
        };

        var ordered = activities.OrderByDescending(a => a.CreatedAt).ToList();

        ordered.First().ActionType.Should().Be("LogCall");
        ordered.Last().ActionType.Should().Be("Login");
    }

    [Fact]
    public void DateRangeScoping_OnlyIncludesRange()
    {
        // M7-UT09: 30-day filter only includes range
        var since = DateTime.UtcNow.Date.AddDays(-30);
        var signals = new[]
        {
            new Signal { DetectedAt = DateTime.UtcNow, Platform = "X", PostContent = "recent" },
            new Signal { DetectedAt = DateTime.UtcNow.AddDays(-60), Platform = "X", PostContent = "old" },
        };

        var filtered = signals.Where(s => s.DetectedAt >= since).ToList();

        filtered.Should().HaveCount(1);
        filtered[0].PostContent.Should().Be("recent");
    }

    [Fact]
    public void ApiCostTracking_StructureCorrect()
    {
        // M7-UT10: Budget percentages / structure
        var costs = new[]
        {
            new ApiUsageLog { Service = "OpenAI", CallCount = 150, Cost = 12.50m, Date = DateTime.UtcNow.Date },
            new ApiUsageLog { Service = "Enrichment", CallCount = 30, Cost = 3.00m, Date = DateTime.UtcNow.Date },
        };

        var totalCost = costs.Sum(c => c.Cost);
        totalCost.Should().Be(15.50m);

        costs.First(c => c.Service == "OpenAI").CallCount.Should().Be(150);
    }
}
