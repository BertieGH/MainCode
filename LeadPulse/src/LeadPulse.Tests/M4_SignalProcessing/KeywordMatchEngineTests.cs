using System.Text.Json;
using FluentAssertions;
using LeadPulse.Domain.Entities.Tenant;
using LeadPulse.Domain.Enums;
using LeadPulse.Infrastructure.Services;

namespace LeadPulse.Tests.M4_SignalProcessing;

/// <summary>
/// M4-UT01 through M4-UT10: Keyword match engine tests
/// </summary>
public class KeywordMatchEngineTests
{
    private readonly KeywordMatchEngine _engine = new();

    private static KeywordRule MakeRule(
        int id, string keyword, KeywordMatchType matchType,
        string? category = null, int scoreBoost = 10,
        List<string>? synonyms = null, int similarityThreshold = 75,
        List<string>? negativeKeywords = null, List<string>? platforms = null)
    {
        return new KeywordRule
        {
            Id = id,
            Keyword = keyword,
            MatchType = matchType,
            Category = category,
            ScoreBoost = scoreBoost,
            Synonyms = synonyms != null ? JsonSerializer.Serialize(synonyms) : null,
            SimilarityThreshold = similarityThreshold,
            NegativeKeywords = negativeKeywords != null ? JsonSerializer.Serialize(negativeKeywords) : null,
            Platforms = platforms != null ? JsonSerializer.Serialize(platforms) : null,
            IsActive = true
        };
    }

    [Fact]
    public void ExactMatch_MatchesExactPhrase()
    {
        // M4-UT01: "insurance premiums" matches "insurance premiums"
        var rule = MakeRule(1, "insurance premiums", KeywordMatchType.Exact);
        var text = "I'm worried about my insurance premiums going up";

        var results = _engine.FindMatches(text, new[] { rule });

        results.Should().HaveCount(1);
        results[0].MatchScore.Should().Be(100m);
    }

    [Fact]
    public void ExactMatch_DoesNotMatchPartial()
    {
        // M4-UT01: "insurance premiums" does NOT match "insurance premium" (missing 's')
        var rule = MakeRule(1, "insurance premiums", KeywordMatchType.Exact);
        var text = "my insurance premium is too high";

        var results = _engine.FindMatches(text, new[] { rule });

        results.Should().BeEmpty();
    }

    [Fact]
    public void ContainsMatch_FindsSubstring()
    {
        // M4-UT02: "home insurance" matches within longer text
        var rule = MakeRule(1, "home insurance", KeywordMatchType.Contains, "Home");
        var text = "I need home insurance for my new house";

        var results = _engine.FindMatches(text, new[] { rule });

        results.Should().HaveCount(1);
        results[0].Category.Should().Be("Home");
    }

    [Fact]
    public void SimilarMatch_MatchesSynonym()
    {
        // M4-UT03: "car insurance" with synonym "auto insurance" matches
        var rule = MakeRule(1, "car insurance", KeywordMatchType.Similar,
            synonyms: new List<string> { "auto insurance", "vehicle coverage" });
        var text = "looking for auto insurance quotes";

        var results = _engine.FindMatches(text, new[] { rule });

        results.Should().HaveCount(1);
        results[0].MatchedText.Should().Be("auto insurance");
    }

    [Fact]
    public void SimilarMatch_FuzzyMisspelling()
    {
        // M4-UT04: "homeowner" at 80% threshold matches "homeownr"
        var rule = MakeRule(1, "homeowner", KeywordMatchType.Similar, similarityThreshold: 80);
        var text = "any homeownr insurance recommendations";

        var results = _engine.FindMatches(text, new[] { rule });

        results.Should().HaveCount(1);
        results[0].MatchScore.Should().BeGreaterThanOrEqualTo(80m);
    }

    [Fact]
    public void RegexMatch_MatchesPattern()
    {
        // M4-UT05: regex pattern matches both alternatives
        var rule = MakeRule(1, @"business insurance|commercial policy", KeywordMatchType.Regex);
        var text = "I need a commercial policy for my LLC";

        var results = _engine.FindMatches(text, new[] { rule });

        results.Should().HaveCount(1);
        results[0].MatchedText.Should().Be("commercial policy");
    }

    [Fact]
    public void RegexMatch_MatchesAlternative()
    {
        var rule = MakeRule(1, @"business insurance|commercial policy", KeywordMatchType.Regex);
        var text = "looking for business insurance options";

        var results = _engine.FindMatches(text, new[] { rule });

        results.Should().HaveCount(1);
        results[0].MatchedText.Should().Be("business insurance");
    }

    [Fact]
    public void SemanticMatch_FallsBackToSynonyms()
    {
        // M4-UT06: semantic stub falls back to synonym check
        var rule = MakeRule(1, "shopping for coverage", KeywordMatchType.Semantic,
            synonyms: new List<string> { "thinking about switching providers" });
        var text = "I've been thinking about switching providers lately";

        var results = _engine.FindMatches(text, new[] { rule });

        results.Should().HaveCount(1);
    }

    [Fact]
    public void NegativeKeyword_ExcludesMatch()
    {
        // M4-UT07: negative "spam,selling" excludes "selling insurance"
        var rule = MakeRule(1, "insurance", KeywordMatchType.Contains,
            negativeKeywords: new List<string> { "spam", "selling" });
        var text = "I'm selling insurance policies at great rates";

        var results = _engine.FindMatches(text, new[] { rule });

        results.Should().BeEmpty();
    }

    [Fact]
    public void SimilarityThreshold_EnforcedStrictly()
    {
        // M4-UT08: threshold 90%, fuzzy match below 90% excluded
        var rule = MakeRule(1, "homeowner", KeywordMatchType.Similar, similarityThreshold: 90);
        var text = "any homownr tips"; // Low similarity — 5 chars vs 9 chars keyword

        var results = _engine.FindMatches(text, new[] { rule });

        // Should not match because "homownr" similarity to "homeowner" is below 90%
        results.Should().BeEmpty();
    }

    [Fact]
    public void ScoreBoost_IncludedInResult()
    {
        // M4-UT09: keyword with +20 boost appears in result
        var rule = MakeRule(1, "insurance", KeywordMatchType.Contains, scoreBoost: 20);
        var text = "need insurance help";

        var results = _engine.FindMatches(text, new[] { rule });

        results.Should().HaveCount(1);
        results[0].ScoreBoost.Should().Be(20);
    }

    [Fact]
    public void PlatformFilter_ExcludesWrongPlatform()
    {
        // M4-UT10: keyword for Facebook only, LinkedIn posts not matched
        var rule = MakeRule(1, "insurance", KeywordMatchType.Contains,
            platforms: new List<string> { "Facebook" });
        var text = "need insurance advice";

        var results = _engine.FindMatches(text, new[] { rule }, "LinkedIn");

        results.Should().BeEmpty();
    }

    [Fact]
    public void PlatformFilter_IncludesCorrectPlatform()
    {
        var rule = MakeRule(1, "insurance", KeywordMatchType.Contains,
            platforms: new List<string> { "Facebook" });
        var text = "need insurance advice";

        var results = _engine.FindMatches(text, new[] { rule }, "Facebook");

        results.Should().HaveCount(1);
    }

    [Fact]
    public void MultipleRules_MatchMultiple()
    {
        var rules = new[]
        {
            MakeRule(1, "home insurance", KeywordMatchType.Contains, "Home", 15),
            MakeRule(2, "flood coverage", KeywordMatchType.Contains, "Home", 10),
            MakeRule(3, "auto insurance", KeywordMatchType.Contains, "Auto", 10)
        };
        var text = "I need home insurance and flood coverage for my property";

        var results = _engine.FindMatches(text, rules);

        results.Should().HaveCount(2);
        results.Select(r => r.KeywordRuleId).Should().Contain(new[] { 1, 2 });
    }

    [Fact]
    public void EmptyText_ReturnsNoMatches()
    {
        var rule = MakeRule(1, "insurance", KeywordMatchType.Contains);

        var results = _engine.FindMatches("", new[] { rule });

        results.Should().BeEmpty();
    }

    [Fact]
    public void InvalidRegex_DoesNotThrow()
    {
        var rule = MakeRule(1, "[invalid(regex", KeywordMatchType.Regex);
        var text = "some text";

        var results = _engine.FindMatches(text, new[] { rule });

        results.Should().BeEmpty();
    }
}
