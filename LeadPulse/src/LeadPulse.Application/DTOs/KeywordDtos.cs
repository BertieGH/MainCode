using LeadPulse.Domain.Enums;

namespace LeadPulse.Application.DTOs;

public class CreateKeywordRuleRequest
{
    public string Keyword { get; set; } = string.Empty;
    public string MatchType { get; set; } = "Contains";
    public string? Category { get; set; }
    public int ScoreBoost { get; set; } = 10;
    public List<string>? Synonyms { get; set; }
    public int SimilarityThreshold { get; set; } = 75;
    public List<string>? NegativeKeywords { get; set; }
    public List<string>? Platforms { get; set; }
}

public class UpdateKeywordRuleRequest
{
    public string Keyword { get; set; } = string.Empty;
    public string MatchType { get; set; } = "Contains";
    public string? Category { get; set; }
    public int ScoreBoost { get; set; } = 10;
    public List<string>? Synonyms { get; set; }
    public int SimilarityThreshold { get; set; } = 75;
    public List<string>? NegativeKeywords { get; set; }
    public List<string>? Platforms { get; set; }
    public bool IsActive { get; set; } = true;
}

public class KeywordRuleResponse
{
    public int Id { get; set; }
    public string Keyword { get; set; } = string.Empty;
    public string MatchType { get; set; } = string.Empty;
    public string? Category { get; set; }
    public int ScoreBoost { get; set; }
    public List<string>? Synonyms { get; set; }
    public int SimilarityThreshold { get; set; }
    public List<string>? NegativeKeywords { get; set; }
    public List<string>? Platforms { get; set; }
    public bool IsActive { get; set; }
    public int HitCount30d { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime? UpdatedAt { get; set; }
}

public class CopyKeywordsRequest
{
    public int SourceTenantId { get; set; }
    public int TargetTenantId { get; set; }
}

public class KeywordCsvRow
{
    public string Keyword { get; set; } = string.Empty;
    public string MatchType { get; set; } = "Contains";
    public string? Category { get; set; }
    public int ScoreBoost { get; set; } = 10;
    public string? Synonyms { get; set; }
    public int SimilarityThreshold { get; set; } = 75;
    public string? NegativeKeywords { get; set; }
    public string? Platforms { get; set; }
}
