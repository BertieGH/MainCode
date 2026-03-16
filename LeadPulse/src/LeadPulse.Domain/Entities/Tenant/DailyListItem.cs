using LeadPulse.Domain.Enums;

namespace LeadPulse.Domain.Entities.Tenant;

public class DailyListItem
{
    public int Id { get; set; }
    public int DailyListId { get; set; }
    public int ProspectId { get; set; }
    public ProspectStatus Status { get; set; } = ProspectStatus.New;
    public DateTime? ViewedAt { get; set; }
    public DateTime? ContactedAt { get; set; }

    public DailyList DailyList { get; set; } = null!;
    public Prospect Prospect { get; set; } = null!;
}
