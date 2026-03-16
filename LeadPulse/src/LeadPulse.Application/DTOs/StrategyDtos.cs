namespace LeadPulse.Application.DTOs;

public class CreateStrategyRequest
{
    public string Name { get; set; } = string.Empty;
    public List<string>? TargetCategories { get; set; }
    public List<string>? TargetStates { get; set; }
    public List<string>? TargetZipCodes { get; set; }
    public int? Radius { get; set; }
    public int MinScore { get; set; } = 50;
    public string? MinUrgency { get; set; }
    public int MaxDailyProspects { get; set; } = 10;
    public Dictionary<string, int>? KeywordBoosts { get; set; }
}

public class UpdateStrategyRequest : CreateStrategyRequest
{
    public bool IsActive { get; set; }
}

public class StrategyResponse
{
    public int Id { get; set; }
    public string Name { get; set; } = string.Empty;
    public List<string>? TargetCategories { get; set; }
    public List<string>? TargetStates { get; set; }
    public List<string>? TargetZipCodes { get; set; }
    public int? Radius { get; set; }
    public int MinScore { get; set; }
    public string? MinUrgency { get; set; }
    public int MaxDailyProspects { get; set; }
    public Dictionary<string, int>? KeywordBoosts { get; set; }
    public bool IsActive { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime? UpdatedAt { get; set; }
}

public class DailyListResponse
{
    public int Id { get; set; }
    public int StrategyId { get; set; }
    public string StrategyName { get; set; } = string.Empty;
    public DateTime GeneratedDate { get; set; }
    public int ProspectCount { get; set; }
    public List<DailyListItemResponse> Items { get; set; } = new();
    public DateTime CreatedAt { get; set; }
}

public class DailyListItemResponse
{
    public int Id { get; set; }
    public int ProspectId { get; set; }
    public ProspectResponse Prospect { get; set; } = null!;
    public string Status { get; set; } = string.Empty;
    public DateTime? ViewedAt { get; set; }
    public DateTime? ContactedAt { get; set; }
}

public class UpdateDailyListItemStatusRequest
{
    public string Status { get; set; } = string.Empty;
}
