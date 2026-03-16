namespace LeadPulse.Domain.Entities.Tenant;

public class DailyList
{
    public int Id { get; set; }
    public int StrategyId { get; set; }
    public DateTime GeneratedDate { get; set; }
    public int ProspectCount { get; set; }
    public DateTime CreatedAt { get; set; }

    public Strategy Strategy { get; set; } = null!;
    public ICollection<DailyListItem> Items { get; set; } = new List<DailyListItem>();
}
