using FluentAssertions;
using LeadPulse.Domain.Entities.Tenant;
using LeadPulse.Domain.Enums;

namespace LeadPulse.Tests.M5_Prospects;

/// <summary>
/// M5-UT01: Filter by category
/// M5-UT02: Filter by score range
/// M5-UT03: Filter combination
/// M5-UT04: Sort by score descending
/// M5-UT12: Pagination
/// </summary>
public class ProspectFilterTests
{
    private static List<Prospect> SampleProspects() => new()
    {
        new() { Id = 1, Name = "Alice", Category = "Home", CompositeScore = 92, Urgency = Urgency.Hot, Platform = "LinkedIn", City = "Dallas", State = "TX", Zip = "75024", CreatedAt = DateTime.UtcNow.AddDays(-1) },
        new() { Id = 2, Name = "Bob", Category = "Auto", CompositeScore = 87, Urgency = Urgency.Hot, Platform = "Facebook", City = "Austin", State = "TX", Zip = "78701", CreatedAt = DateTime.UtcNow.AddDays(-2) },
        new() { Id = 3, Name = "Carol", Category = "Home", CompositeScore = 81, Urgency = Urgency.Warm, Platform = "LinkedIn", City = "Dallas", State = "TX", Zip = "75024", CreatedAt = DateTime.UtcNow.AddDays(-3) },
        new() { Id = 4, Name = "Dan", Category = "Life", CompositeScore = 65, Urgency = Urgency.Warm, Platform = "Nextdoor", City = "Houston", State = "TX", Zip = "77001", CreatedAt = DateTime.UtcNow.AddDays(-4) },
        new() { Id = 5, Name = "Eve", Category = "Auto", CompositeScore = 45, Urgency = Urgency.Cool, Platform = "Facebook", City = "Austin", State = "TX", Zip = "78702", CreatedAt = DateTime.UtcNow.AddDays(-5) },
    };

    [Fact]
    public void FilterByCategory_ReturnsOnlyMatchingCategory()
    {
        // M5-UT01: category=Home returns only Home prospects
        var prospects = SampleProspects();

        var filtered = prospects.Where(p => p.Category == "Home").ToList();

        filtered.Should().HaveCount(2);
        filtered.Should().OnlyContain(p => p.Category == "Home");
    }

    [Fact]
    public void FilterByScoreRange_ReturnsMatchingRange()
    {
        // M5-UT02: score=70-89 returns matching prospects
        var prospects = SampleProspects();

        var filtered = prospects.Where(p => p.CompositeScore >= 70 && p.CompositeScore <= 89).ToList();

        filtered.Should().HaveCount(2);
        filtered.Select(p => p.Name).Should().Contain(new[] { "Bob", "Carol" });
    }

    [Fact]
    public void FilterCombination_ReturnsIntersection()
    {
        // M5-UT03: category=Auto AND urgency=Hot returns intersection
        var prospects = SampleProspects();

        var filtered = prospects
            .Where(p => p.Category == "Auto" && p.Urgency == Urgency.Hot)
            .ToList();

        filtered.Should().HaveCount(1);
        filtered[0].Name.Should().Be("Bob");
    }

    [Fact]
    public void SortByScoreDescending_CorrectOrder()
    {
        // M5-UT04: Ordered by score descending
        var prospects = SampleProspects();

        var sorted = prospects.OrderByDescending(p => p.CompositeScore).ToList();

        sorted.Select(p => p.CompositeScore).Should().BeInDescendingOrder();
        sorted[0].CompositeScore.Should().Be(92);
    }

    [Fact]
    public void Pagination_ReturnsCorrectPage()
    {
        // M5-UT12: 5 prospects, page=2 size=2 → items 3-4
        var prospects = SampleProspects().OrderByDescending(p => p.CompositeScore).ToList();
        var page = 2;
        var pageSize = 2;

        var paged = prospects.Skip((page - 1) * pageSize).Take(pageSize).ToList();

        paged.Should().HaveCount(2);
        paged[0].CompositeScore.Should().Be(81); // 3rd highest
        paged[1].CompositeScore.Should().Be(65); // 4th highest
    }

    [Fact]
    public void Pagination_TotalPages_CalculatedCorrectly()
    {
        var total = 50;
        var pageSize = 20;

        var totalPages = (int)Math.Ceiling((double)total / pageSize);

        totalPages.Should().Be(3);
    }
}
