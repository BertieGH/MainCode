namespace LeadPulse.Domain.Entities.Tenant;

public class SignalKeywordMatch
{
    public long Id { get; set; }
    public long SignalId { get; set; }
    public int KeywordRuleId { get; set; }
    public decimal? MatchScore { get; set; }
    public string? MatchedText { get; set; }

    public Signal Signal { get; set; } = null!;
    public KeywordRule KeywordRule { get; set; } = null!;
}
