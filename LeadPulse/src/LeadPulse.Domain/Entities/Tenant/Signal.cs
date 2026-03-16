namespace LeadPulse.Domain.Entities.Tenant;

public class Signal
{
    public long Id { get; set; }
    public int SocialAccountId { get; set; }
    public string Platform { get; set; } = string.Empty;
    public string? AuthorName { get; set; }
    public string? AuthorProfileUrl { get; set; }
    public string PostContent { get; set; } = string.Empty;
    public string? PostUrl { get; set; }
    public DateTime? PostDate { get; set; }
    public DateTime DetectedAt { get; set; }

    // AI Intent Analysis fields
    public int? IntentScore { get; set; }
    public string? IntentCategory { get; set; }
    public string? Sentiment { get; set; }
    public string? AiSummary { get; set; }
    public string? AiProvider { get; set; }
    public DateTime? AnalyzedAt { get; set; }

    public SocialAccount SocialAccount { get; set; } = null!;
    public ICollection<SignalKeywordMatch> KeywordMatches { get; set; } = new List<SignalKeywordMatch>();
}
