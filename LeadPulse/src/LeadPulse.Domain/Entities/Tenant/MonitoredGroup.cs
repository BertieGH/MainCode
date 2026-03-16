namespace LeadPulse.Domain.Entities.Tenant;

public class MonitoredGroup
{
    public int Id { get; set; }
    public int SocialAccountId { get; set; }
    public string Platform { get; set; } = string.Empty;
    public string GroupUrl { get; set; } = string.Empty;
    public string? GroupName { get; set; }
    public bool IsActive { get; set; } = true;

    public SocialAccount SocialAccount { get; set; } = null!;
}
