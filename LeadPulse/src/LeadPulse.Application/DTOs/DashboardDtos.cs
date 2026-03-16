namespace LeadPulse.Application.DTOs;

public class DashboardResponse
{
    public int NewProspectsToday { get; set; }
    public int CallsMadeToday { get; set; }
    public decimal ConversionRate { get; set; }
    public int ActiveSignals { get; set; }
    public List<TopProspectDto> TopProspects { get; set; } = new();
    public List<FollowUpReminderDto> FollowUpReminders { get; set; } = new();
    public List<ActivityDto> RecentActivity { get; set; } = new();
}

public class TopProspectDto
{
    public int Id { get; set; }
    public string Name { get; set; } = string.Empty;
    public int CompositeScore { get; set; }
    public string Urgency { get; set; } = string.Empty;
    public string? Category { get; set; }
    public string? Platform { get; set; }
}

public class FollowUpReminderDto
{
    public int CallLogId { get; set; }
    public int ProspectId { get; set; }
    public string ProspectName { get; set; } = string.Empty;
    public DateTime FollowUpDate { get; set; }
    public TimeSpan? FollowUpTime { get; set; }
    public string? Notes { get; set; }
}

public class ActivityDto
{
    public long Id { get; set; }
    public string ActionType { get; set; } = string.Empty;
    public string? Description { get; set; }
    public string? UserName { get; set; }
    public DateTime CreatedAt { get; set; }
}

public class AnalyticsResponse
{
    public List<DailyCountDto> SignalVolume { get; set; } = new();
    public List<CategoryBreakdownDto> CategoryBreakdown { get; set; } = new();
    public List<PlatformDistributionDto> PlatformDistribution { get; set; } = new();
    public ConversionFunnelDto Funnel { get; set; } = new();
    public List<ApiCostDto> ApiCosts { get; set; } = new();
}

public class DailyCountDto
{
    public DateTime Date { get; set; }
    public int Count { get; set; }
}

public class CategoryBreakdownDto
{
    public string Category { get; set; } = string.Empty;
    public int Count { get; set; }
    public decimal Percentage { get; set; }
}

public class PlatformDistributionDto
{
    public string Platform { get; set; } = string.Empty;
    public int Count { get; set; }
}

public class ConversionFunnelDto
{
    public int TotalSignals { get; set; }
    public int TotalProspects { get; set; }
    public int Contacted { get; set; }
    public int Converted { get; set; }
}

public class ApiCostDto
{
    public string Service { get; set; } = string.Empty;
    public int CallCount { get; set; }
    public decimal Cost { get; set; }
    public DateTime Date { get; set; }
}
