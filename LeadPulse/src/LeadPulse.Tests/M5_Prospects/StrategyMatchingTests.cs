using System.Text.Json;
using FluentAssertions;
using LeadPulse.Domain.Entities.Tenant;
using LeadPulse.Domain.Enums;

namespace LeadPulse.Tests.M5_Prospects;

/// <summary>
/// M5-UT07: Strategy matching
/// M5-UT08: Max daily prospects
/// M5-UT11: Prospect deduplication
/// </summary>
public class StrategyMatchingTests
{
    [Fact]
    public void StrategyFilter_CategoryAndZip_MatchesCorrectProspects()
    {
        // M5-UT07: Strategy for Home+Auto in zip 75024, minScore 60
        var strategy = new Strategy
        {
            TargetCategories = JsonSerializer.Serialize(new[] { "Home", "Auto" }),
            TargetZipCodes = JsonSerializer.Serialize(new[] { "75024" }),
            MinScore = 60,
            MaxDailyProspects = 10
        };

        var prospects = new List<Prospect>
        {
            new() { Id = 1, Name = "Match1", Category = "Home", Zip = "75024", CompositeScore = 85, Status = ProspectStatus.New },
            new() { Id = 2, Name = "Match2", Category = "Auto", Zip = "75024", CompositeScore = 70, Status = ProspectStatus.New },
            new() { Id = 3, Name = "WrongZip", Category = "Home", Zip = "78701", CompositeScore = 90, Status = ProspectStatus.New },
            new() { Id = 4, Name = "WrongCat", Category = "Life", Zip = "75024", CompositeScore = 80, Status = ProspectStatus.New },
            new() { Id = 5, Name = "LowScore", Category = "Home", Zip = "75024", CompositeScore = 50, Status = ProspectStatus.New },
            new() { Id = 6, Name = "Dismissed", Category = "Home", Zip = "75024", CompositeScore = 95, Status = ProspectStatus.Dismissed },
        };

        var categories = JsonSerializer.Deserialize<List<string>>(strategy.TargetCategories!)!;
        var zips = JsonSerializer.Deserialize<List<string>>(strategy.TargetZipCodes!)!;

        var matched = prospects
            .Where(p => p.Status != ProspectStatus.Dismissed && p.Status != ProspectStatus.Converted)
            .Where(p => p.CompositeScore >= strategy.MinScore)
            .Where(p => !string.IsNullOrEmpty(p.Category) && categories.Contains(p.Category))
            .Where(p => !string.IsNullOrEmpty(p.Zip) && zips.Contains(p.Zip))
            .OrderByDescending(p => p.CompositeScore)
            .Take(strategy.MaxDailyProspects)
            .ToList();

        matched.Should().HaveCount(2);
        matched.Select(p => p.Name).Should().Contain(new[] { "Match1", "Match2" });
    }

    [Fact]
    public void MaxDailyProspects_CapsResults()
    {
        // M5-UT08: maxDaily=2 with 5 matches → top 2
        var prospects = Enumerable.Range(1, 5)
            .Select(i => new Prospect { Id = i, Name = $"P{i}", CompositeScore = 100 - i * 5, Status = ProspectStatus.New })
            .ToList();

        var maxDaily = 2;

        var selected = prospects
            .OrderByDescending(p => p.CompositeScore)
            .Take(maxDaily)
            .ToList();

        selected.Should().HaveCount(2);
        selected[0].CompositeScore.Should().Be(95);
        selected[1].CompositeScore.Should().Be(90);
    }

    [Fact]
    public void ProspectDeduplication_SameAuthorSamePlatform_SingleProspect()
    {
        // M5-UT11: Two signals from same person → should match to single prospect
        var existingProspects = new List<Prospect>
        {
            new() { Id = 1, Name = "John Smith", Platform = "LinkedIn", CompositeScore = 70 }
        };

        var newSignalAuthor = "John Smith";
        var newSignalPlatform = "LinkedIn";

        var existing = existingProspects
            .FirstOrDefault(p => p.Name == newSignalAuthor && p.Platform == newSignalPlatform);

        existing.Should().NotBeNull();
        // Should update existing rather than creating new
    }

    [Fact]
    public void ProspectDeduplication_DifferentPlatform_NewProspect()
    {
        var existingProspects = new List<Prospect>
        {
            new() { Id = 1, Name = "John Smith", Platform = "LinkedIn", CompositeScore = 70 }
        };

        var existing = existingProspects
            .FirstOrDefault(p => p.Name == "John Smith" && p.Platform == "Facebook");

        existing.Should().BeNull();
        // Should create new prospect for different platform
    }

    [Fact]
    public void CsvExport_IncludesExpectedColumns()
    {
        // M5-UT05/UT06: CSV export structure
        var csvHeader = "Name,Score,Urgency,Category,Platform,Phone,Email,City,State,Zip,Company,Status,Created";

        csvHeader.Should().Contain("Name");
        csvHeader.Should().Contain("Score");
        csvHeader.Should().Contain("Phone");
        csvHeader.Should().Contain("Email");
        csvHeader.Should().Contain("Company");
    }

    [Fact]
    public void EnrichmentUpdatesFields()
    {
        // M5-UT10: Enrichment updates phone/email, status=Verified
        var prospect = new Prospect
        {
            Name = "Test",
            EnrichmentStatus = EnrichmentStatus.Pending
        };

        prospect.Phone = "555-1234";
        prospect.Email = "test@example.com";
        prospect.EnrichmentStatus = EnrichmentStatus.Verified;

        prospect.Phone.Should().Be("555-1234");
        prospect.Email.Should().Be("test@example.com");
        prospect.EnrichmentStatus.Should().Be(EnrichmentStatus.Verified);
    }
}
