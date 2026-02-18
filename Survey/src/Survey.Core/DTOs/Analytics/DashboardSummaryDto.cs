namespace Survey.Core.DTOs.Analytics;

public class DashboardSummaryDto
{
    public int TotalSurveys { get; set; }
    public int ActiveSurveys { get; set; }
    public int TotalResponses { get; set; }
    public int TotalClients { get; set; }
    public double OverallCompletionRate { get; set; }
    public List<SurveySummaryDto> RecentSurveys { get; set; } = new();
    public List<RecentResponseDto> RecentResponses { get; set; } = new();
}

public class SurveySummaryDto
{
    public int SurveyId { get; set; }
    public string Title { get; set; } = string.Empty;
    public string Status { get; set; } = string.Empty;
    public int ResponseCount { get; set; }
    public double CompletionRate { get; set; }
}

public class RecentResponseDto
{
    public int ResponseId { get; set; }
    public string SurveyTitle { get; set; } = string.Empty;
    public string CrmClientId { get; set; } = string.Empty;
    public DateTime CompletedAt { get; set; }
}
