namespace LeadPulse.Domain.Entities.App;

public class GlobalSetting
{
    public string Key { get; set; } = string.Empty;
    public string? Value { get; set; }
    public DateTime? UpdatedAt { get; set; }
}
