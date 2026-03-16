namespace LeadPulse.Domain.Entities.Tenant;

public class Strategy
{
    public int Id { get; set; }
    public string Name { get; set; } = string.Empty;
    public string? TargetCategories { get; set; }
    public string? TargetStates { get; set; }
    public string? TargetZipCodes { get; set; }
    public int? Radius { get; set; }
    public int MinScore { get; set; } = 50;
    public string? MinUrgency { get; set; }
    public int MaxDailyProspects { get; set; } = 10;
    public string? KeywordBoosts { get; set; }
    public bool IsActive { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime? UpdatedAt { get; set; }
}
