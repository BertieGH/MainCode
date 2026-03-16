using LeadPulse.Domain.Entities.Tenant;

namespace LeadPulse.Application.Interfaces;

public interface IKeywordMatchEngine
{
    List<KeywordMatchResult> FindMatches(string text, IEnumerable<KeywordRule> activeRules, string? platform = null);
}

public class KeywordMatchResult
{
    public int KeywordRuleId { get; set; }
    public decimal MatchScore { get; set; }
    public string MatchedText { get; set; } = string.Empty;
    public int ScoreBoost { get; set; }
    public string? Category { get; set; }
}
