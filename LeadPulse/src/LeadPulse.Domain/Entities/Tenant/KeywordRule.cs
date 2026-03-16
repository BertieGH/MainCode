using LeadPulse.Domain.Enums;

namespace LeadPulse.Domain.Entities.Tenant;

public class KeywordRule
{
    public int Id { get; set; }
    public string Keyword { get; set; } = string.Empty;
    public KeywordMatchType MatchType { get; set; }
    public string? Category { get; set; }
    public int ScoreBoost { get; set; } = 10;
    public string? Synonyms { get; set; }
    public int SimilarityThreshold { get; set; } = 75;
    public string? NegativeKeywords { get; set; }
    public string? Platforms { get; set; }
    public bool IsActive { get; set; } = true;
    public int HitCount30d { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime? UpdatedAt { get; set; }
}
