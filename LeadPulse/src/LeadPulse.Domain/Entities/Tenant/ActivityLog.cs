namespace LeadPulse.Domain.Entities.Tenant;

public class ActivityLog
{
    public long Id { get; set; }
    public int? UserId { get; set; }
    public string ActionType { get; set; } = string.Empty;
    public string? Description { get; set; }
    public string? RelatedEntityType { get; set; }
    public int? RelatedEntityId { get; set; }
    public DateTime CreatedAt { get; set; }

    public User? User { get; set; }
}
