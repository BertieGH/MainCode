namespace Survey.Core.DTOs.Analytics;

public class SurveyStatisticsDto
{
    public int SurveyId { get; set; }
    public string SurveyTitle { get; set; } = string.Empty;
    public int TotalResponses { get; set; }
    public int CompleteResponses { get; set; }
    public int IncompleteResponses { get; set; }
    public double CompletionRate { get; set; }
    public DateTime? FirstResponseDate { get; set; }
    public DateTime? LastResponseDate { get; set; }
    public double AverageCompletionTimeMinutes { get; set; }
    public List<QuestionAnalyticsDto> QuestionAnalytics { get; set; } = new();
}
