using FluentAssertions;
using LeadPulse.Application.Interfaces;
using LeadPulse.Domain.Entities.Tenant;
using LeadPulse.Infrastructure.Services;

namespace LeadPulse.Tests.M4_SignalProcessing;

/// <summary>
/// M4-UT09: Score boost application
/// M4-UT12: Composite scoring algorithm
/// </summary>
public class CompositeScoringTests
{
    [Fact]
    public void CompositeScore_SumsKeywordBoosts()
    {
        // M4-UT12: Signal with 2 keyword matches (+20, +15) = 35 base
        var matches = new List<KeywordMatchResult>
        {
            new() { KeywordRuleId = 1, MatchScore = 90m, ScoreBoost = 20, Category = "Home" },
            new() { KeywordRuleId = 2, MatchScore = 85m, ScoreBoost = 15, Category = "Home" }
        };

        var signal = new Signal
        {
            PostDate = DateTime.UtcNow.AddHours(-2), // Recent — within 24h
            DetectedAt = DateTime.UtcNow
        };

        var score = SignalProcessor.CalculateCompositeScore(matches, signal);

        // 35 (boosts) + 15 (recency 24h) + 8 (quality avg 87.5/10) = 58
        score.Should().BeGreaterThan(35);
        score.Should().BeLessThanOrEqualTo(100);
    }

    [Fact]
    public void CompositeScore_RecencyBonus_24h()
    {
        var matches = new List<KeywordMatchResult>
        {
            new() { KeywordRuleId = 1, MatchScore = 100m, ScoreBoost = 10 }
        };

        var recentSignal = new Signal { PostDate = DateTime.UtcNow.AddHours(-12), DetectedAt = DateTime.UtcNow };
        var oldSignal = new Signal { PostDate = DateTime.UtcNow.AddDays(-10), DetectedAt = DateTime.UtcNow };

        var recentScore = SignalProcessor.CalculateCompositeScore(matches, recentSignal);
        var oldScore = SignalProcessor.CalculateCompositeScore(matches, oldSignal);

        recentScore.Should().BeGreaterThan(oldScore);
    }

    [Fact]
    public void CompositeScore_CappedAt100()
    {
        var matches = new List<KeywordMatchResult>
        {
            new() { KeywordRuleId = 1, MatchScore = 100m, ScoreBoost = 40 },
            new() { KeywordRuleId = 2, MatchScore = 100m, ScoreBoost = 40 },
            new() { KeywordRuleId = 3, MatchScore = 100m, ScoreBoost = 40 }
        };

        var signal = new Signal { PostDate = DateTime.UtcNow, DetectedAt = DateTime.UtcNow };

        var score = SignalProcessor.CalculateCompositeScore(matches, signal);

        score.Should().Be(100);
    }

    [Fact]
    public void CompositeScore_NoPostDate_NoRecencyBonus()
    {
        var matches = new List<KeywordMatchResult>
        {
            new() { KeywordRuleId = 1, MatchScore = 100m, ScoreBoost = 10 }
        };

        var signal = new Signal { PostDate = null, DetectedAt = DateTime.UtcNow };

        var score = SignalProcessor.CalculateCompositeScore(matches, signal);

        // 10 (boost) + 0 (no recency) + 10 (quality 100/10) = 20
        score.Should().Be(20);
    }

    [Fact]
    public void LevenshteinSimilarity_IdenticalStrings_Returns100()
    {
        var result = KeywordMatchEngine.CalculateSimilarity("hello", "hello");
        result.Should().Be(100.0);
    }

    [Fact]
    public void LevenshteinSimilarity_OneCharDifference()
    {
        // "homeowner" vs "homeownr" — 1 deletion out of 9 chars
        var result = KeywordMatchEngine.CalculateSimilarity("homeowner", "homeownr");
        result.Should().BeGreaterThanOrEqualTo(80);
    }

    [Fact]
    public void LevenshteinSimilarity_CompletelyDifferent()
    {
        var result = KeywordMatchEngine.CalculateSimilarity("abc", "xyz");
        result.Should().BeLessThan(50);
    }
}
