using LeadPulse.Domain.Enums;

namespace LeadPulse.Domain.Entities.Tenant;

public class CallLog
{
    public int Id { get; set; }
    public int ProspectId { get; set; }
    public int UserId { get; set; }
    public ContactMethod ContactMethod { get; set; }
    public string Outcome { get; set; } = string.Empty;
    public string? Notes { get; set; }
    public DateTime? FollowUpDate { get; set; }
    public TimeSpan? FollowUpTime { get; set; }
    public int? DurationSeconds { get; set; }
    public DateTime CreatedAt { get; set; }

    public Prospect Prospect { get; set; } = null!;
    public User User { get; set; } = null!;
}
