using System.Text.Json;
using System.Text.RegularExpressions;
using LeadPulse.Application.Interfaces;
using LeadPulse.Domain.Entities.Tenant;
using LeadPulse.Domain.Enums;

namespace LeadPulse.Infrastructure.Services;

public class KeywordMatchEngine : IKeywordMatchEngine
{
    public List<KeywordMatchResult> FindMatches(string text, IEnumerable<KeywordRule> activeRules, string? platform = null)
    {
        var results = new List<KeywordMatchResult>();
        if (string.IsNullOrWhiteSpace(text)) return results;

        foreach (var rule in activeRules)
        {
            // Platform filter
            if (!string.IsNullOrEmpty(rule.Platforms))
            {
                var platforms = DeserializeList(rule.Platforms);
                if (platforms != null && platforms.Count > 0 && platform != null)
                {
                    if (!platforms.Any(p => p.Equals(platform, StringComparison.OrdinalIgnoreCase)))
                        continue;
                }
            }

            // Negative keyword check
            if (!string.IsNullOrEmpty(rule.NegativeKeywords))
            {
                var negatives = DeserializeList(rule.NegativeKeywords);
                if (negatives != null && negatives.Any(neg =>
                    text.Contains(neg, StringComparison.OrdinalIgnoreCase)))
                    continue;
            }

            var match = rule.MatchType switch
            {
                KeywordMatchType.Exact => MatchExact(text, rule),
                KeywordMatchType.Contains => MatchContains(text, rule),
                KeywordMatchType.Similar => MatchSimilar(text, rule),
                KeywordMatchType.Regex => MatchRegex(text, rule),
                KeywordMatchType.Semantic => MatchSemantic(text, rule),
                _ => null
            };

            if (match != null)
                results.Add(match);
        }

        return results;
    }

    private static KeywordMatchResult? MatchExact(string text, KeywordRule rule)
    {
        // Exact: the keyword must appear as a complete phrase (case-insensitive)
        var index = text.IndexOf(rule.Keyword, StringComparison.OrdinalIgnoreCase);
        if (index < 0) return null;

        // Check word boundaries
        var before = index > 0 ? text[index - 1] : ' ';
        var afterIdx = index + rule.Keyword.Length;
        var after = afterIdx < text.Length ? text[afterIdx] : ' ';

        if (!IsWordBoundary(before) || !IsWordBoundary(after))
            return null;

        return new KeywordMatchResult
        {
            KeywordRuleId = rule.Id,
            MatchScore = 100m,
            MatchedText = rule.Keyword,
            ScoreBoost = rule.ScoreBoost,
            Category = rule.Category
        };
    }

    private static KeywordMatchResult? MatchContains(string text, KeywordRule rule)
    {
        if (!text.Contains(rule.Keyword, StringComparison.OrdinalIgnoreCase))
            return null;

        return new KeywordMatchResult
        {
            KeywordRuleId = rule.Id,
            MatchScore = 90m,
            MatchedText = rule.Keyword,
            ScoreBoost = rule.ScoreBoost,
            Category = rule.Category
        };
    }

    private static KeywordMatchResult? MatchSimilar(string text, KeywordRule rule)
    {
        var threshold = rule.SimilarityThreshold;
        var keywords = new List<string> { rule.Keyword };

        // Add synonyms
        if (!string.IsNullOrEmpty(rule.Synonyms))
        {
            var synonyms = DeserializeList(rule.Synonyms);
            if (synonyms != null) keywords.AddRange(synonyms);
        }

        // Check each keyword/synonym against words in text
        var textLower = text.ToLowerInvariant();
        foreach (var keyword in keywords)
        {
            // Direct contains check first
            if (textLower.Contains(keyword.ToLowerInvariant()))
            {
                return new KeywordMatchResult
                {
                    KeywordRuleId = rule.Id,
                    MatchScore = 100m,
                    MatchedText = keyword,
                    ScoreBoost = rule.ScoreBoost,
                    Category = rule.Category
                };
            }

            // Fuzzy match: compare keyword against sliding windows of text
            var keywordLower = keyword.ToLowerInvariant();
            var words = ExtractNGrams(textLower, keywordLower.Split(' ').Length);

            foreach (var window in words)
            {
                var similarity = CalculateSimilarity(keywordLower, window);
                if (similarity >= threshold)
                {
                    return new KeywordMatchResult
                    {
                        KeywordRuleId = rule.Id,
                        MatchScore = (decimal)similarity,
                        MatchedText = window,
                        ScoreBoost = rule.ScoreBoost,
                        Category = rule.Category
                    };
                }
            }
        }

        return null;
    }

    private static KeywordMatchResult? MatchRegex(string text, KeywordRule rule)
    {
        try
        {
            var regex = new Regex(rule.Keyword, RegexOptions.IgnoreCase, TimeSpan.FromSeconds(1));
            var match = regex.Match(text);
            if (!match.Success) return null;

            return new KeywordMatchResult
            {
                KeywordRuleId = rule.Id,
                MatchScore = 95m,
                MatchedText = match.Value,
                ScoreBoost = rule.ScoreBoost,
                Category = rule.Category
            };
        }
        catch (RegexParseException)
        {
            return null;
        }
    }

    private static KeywordMatchResult? MatchSemantic(string text, KeywordRule rule)
    {
        // Stub: In production, call OpenAI embeddings API for semantic similarity.
        // For now, fall back to a contains + synonym check.
        var containsResult = MatchContains(text, rule);
        if (containsResult != null)
        {
            containsResult.MatchScore = 85m; // Lower confidence for semantic stub
            return containsResult;
        }

        // Check synonyms as fallback
        if (!string.IsNullOrEmpty(rule.Synonyms))
        {
            var synonyms = DeserializeList(rule.Synonyms);
            if (synonyms != null)
            {
                foreach (var syn in synonyms)
                {
                    if (text.Contains(syn, StringComparison.OrdinalIgnoreCase))
                    {
                        return new KeywordMatchResult
                        {
                            KeywordRuleId = rule.Id,
                            MatchScore = 80m,
                            MatchedText = syn,
                            ScoreBoost = rule.ScoreBoost,
                            Category = rule.Category
                        };
                    }
                }
            }
        }

        return null;
    }

    /// <summary>
    /// Levenshtein distance-based similarity (0-100%).
    /// </summary>
    public static double CalculateSimilarity(string a, string b)
    {
        if (a == b) return 100.0;
        if (a.Length == 0 || b.Length == 0) return 0.0;

        var distance = LevenshteinDistance(a, b);
        var maxLen = Math.Max(a.Length, b.Length);
        return (1.0 - (double)distance / maxLen) * 100.0;
    }

    private static int LevenshteinDistance(string a, string b)
    {
        var m = a.Length;
        var n = b.Length;
        var d = new int[m + 1, n + 1];

        for (var i = 0; i <= m; i++) d[i, 0] = i;
        for (var j = 0; j <= n; j++) d[0, j] = j;

        for (var i = 1; i <= m; i++)
        {
            for (var j = 1; j <= n; j++)
            {
                var cost = a[i - 1] == b[j - 1] ? 0 : 1;
                d[i, j] = Math.Min(
                    Math.Min(d[i - 1, j] + 1, d[i, j - 1] + 1),
                    d[i - 1, j - 1] + cost);
            }
        }

        return d[m, n];
    }

    private static List<string> ExtractNGrams(string text, int n)
    {
        var words = text.Split(new[] { ' ', '\t', '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries);
        var ngrams = new List<string>();

        for (var i = 0; i <= words.Length - n; i++)
        {
            ngrams.Add(string.Join(' ', words.Skip(i).Take(n)));
        }

        return ngrams;
    }

    private static bool IsWordBoundary(char c)
    {
        return !char.IsLetterOrDigit(c);
    }

    private static List<string>? DeserializeList(string? json)
    {
        if (string.IsNullOrEmpty(json)) return null;
        try { return JsonSerializer.Deserialize<List<string>>(json); }
        catch { return null; }
    }
}
