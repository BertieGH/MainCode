using LeadPulse.Domain.Enums;

namespace LeadPulse.Domain.Entities.Tenant;

public class SocialAccount
{
    public int Id { get; set; }
    public string Platform { get; set; } = string.Empty;
    public string Username { get; set; } = string.Empty;
    public string EncryptedPassword { get; set; } = string.Empty;
    public string? EncryptedMfaSecret { get; set; }
    public int SyncFrequencyMinutes { get; set; } = 360;
    public TimeSpan? SyncWindowStart { get; set; }
    public TimeSpan? SyncWindowEnd { get; set; }
    public int MaxPostsPerSync { get; set; } = 500;
    public string ScrapeDepth { get; set; } = "48h";
    public int AutoRetryMax { get; set; } = 3;
    public SocialAccountStatus Status { get; set; } = SocialAccountStatus.Active;
    public DateTime? LastLoginAt { get; set; }
    public DateTime? LastSyncAt { get; set; }
    public int TotalPostsScraped { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime? UpdatedAt { get; set; }

    public ICollection<MonitoredGroup> MonitoredGroups { get; set; } = new List<MonitoredGroup>();
    public ICollection<SyncJob> SyncJobs { get; set; } = new List<SyncJob>();
}
