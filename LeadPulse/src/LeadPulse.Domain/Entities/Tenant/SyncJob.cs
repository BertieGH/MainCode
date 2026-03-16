using LeadPulse.Domain.Enums;

namespace LeadPulse.Domain.Entities.Tenant;

public class SyncJob
{
    public int Id { get; set; }
    public int SocialAccountId { get; set; }
    public SyncJobStatus Status { get; set; }
    public int PostsFound { get; set; }
    public int SignalsGenerated { get; set; }
    public DateTime? StartedAt { get; set; }
    public DateTime? CompletedAt { get; set; }
    public int? DurationSeconds { get; set; }
    public string? ErrorMessage { get; set; }
    public int RetryCount { get; set; }
    public DateTime CreatedAt { get; set; }

    public SocialAccount SocialAccount { get; set; } = null!;
}
