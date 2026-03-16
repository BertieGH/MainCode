using System.Text.RegularExpressions;
using LeadPulse.Application.DTOs;
using LeadPulse.Application.Interfaces;

namespace LeadPulse.Infrastructure.Services;

public class LocalIntentAnalyzer : IIntentAnalyzer
{
    private static readonly (string phrase, int weight)[] IntentPhrases =
    {
        ("looking for insurance", 40), ("need insurance", 40), ("need coverage", 35),
        ("shopping for insurance", 35), ("looking for an agent", 35), ("insurance quote", 35),
        ("recommendations for", 30), ("recommend a good", 30), ("can anyone recommend", 30),
        ("anyone know a good", 25), ("switching insurance", 20), ("switching from", 20),
        ("comparing insurance", 20), ("best insurance", 20), ("cheap insurance", 20),
        ("affordable insurance", 20), ("insurance rates", 15), ("insurance premium", 15),
        ("filing a claim", 15), ("insurance claim", 15), ("policy renewal", 15),
        ("new homeowner", 15), ("just bought a house", 15), ("just bought a car", 15),
        ("new driver", 15), ("first time buyer", 15), ("moving to", 10),
        ("insurance company", 10), ("coverage options", 10), ("deductible", 10),
    };

    private static readonly Dictionary<string, string[]> CategoryKeywords = new(StringComparer.OrdinalIgnoreCase)
    {
        ["Auto"] = new[] { "car insurance", "auto insurance", "vehicle insurance", "car accident", "auto coverage", "driver", "driving", "car", "vehicle", "motorcycle", "truck" },
        ["Home"] = new[] { "home insurance", "homeowner", "house insurance", "property insurance", "renters insurance", "flood insurance", "home", "house", "property", "roof", "foundation" },
        ["Life"] = new[] { "life insurance", "term life", "whole life", "life policy", "beneficiary", "life coverage" },
        ["Health"] = new[] { "health insurance", "medical insurance", "health plan", "dental insurance", "vision insurance", "healthcare" },
        ["Commercial"] = new[] { "business insurance", "commercial insurance", "liability insurance", "workers comp", "professional liability", "E&O insurance" },
    };

    private static readonly string[] UrgencyWords = { "asap", "immediately", "urgent", "emergency", "help", "right away", "today", "quickly", "desperate", "need now" };
    private static readonly string[] NegativeWords = { "terrible", "worst", "horrible", "awful", "scam", "rip off", "ripoff", "fraud", "hate", "refused", "denied" };

    public Task<IntentAnalysisResult> AnalyzeAsync(string postContent, string platform)
    {
        var lower = postContent.ToLowerInvariant();

        // Calculate intent score from phrase weights
        int score = 0;
        foreach (var (phrase, weight) in IntentPhrases)
        {
            if (lower.Contains(phrase))
                score += weight;
        }
        score = Math.Min(score, 100);

        // Detect category
        string category = "None";
        int bestCategoryHits = 0;
        foreach (var (cat, keywords) in CategoryKeywords)
        {
            int hits = keywords.Count(k => lower.Contains(k.ToLowerInvariant()));
            if (hits > bestCategoryHits)
            {
                bestCategoryHits = hits;
                category = cat;
            }
        }
        if (bestCategoryHits == 0 && score > 0)
            category = "General";

        // Detect sentiment
        string sentiment = "Neutral";
        bool hasUrgency = UrgencyWords.Any(w => lower.Contains(w));
        bool hasNegative = NegativeWords.Any(w => lower.Contains(w));

        if (hasUrgency)
            sentiment = "Urgent";
        else if (hasNegative)
            sentiment = "Negative";
        else if (lower.Contains("love") || lower.Contains("great") || lower.Contains("happy") || lower.Contains("excellent") || lower.Contains("thank"))
            sentiment = "Positive";

        // Generate summary
        string summary;
        if (score >= 60)
            summary = $"High-intent {category.ToLower()} insurance lead from {platform}. Actively seeking coverage.";
        else if (score >= 30)
            summary = $"Moderate-intent signal related to {category.ToLower()} insurance from {platform}.";
        else if (score > 0)
            summary = $"Low-intent mention of insurance-related topics from {platform}.";
        else
            summary = $"No clear insurance intent detected in this {platform} post.";

        // Extract phone and email via regex
        var phoneMatch = Regex.Match(postContent, @"(\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4})");
        var emailMatch = Regex.Match(postContent, @"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}");

        return Task.FromResult(new IntentAnalysisResult
        {
            IntentScore = score,
            IntentCategory = category,
            Sentiment = sentiment,
            Summary = summary,
            Phone = phoneMatch.Success ? phoneMatch.Value : null,
            Email = emailMatch.Success ? emailMatch.Value : null
        });
    }
}
