namespace Survey.Core.DTOs.Analytics;

public class ClientSurveyHistoryDto
{
    public string CrmClientId { get; set; } = string.Empty;
    public string ClientName { get; set; } = string.Empty;
    public int TotalSurveysCompleted { get; set; }
    public DateTime? FirstSurveyDate { get; set; }
    public DateTime? LastSurveyDate { get; set; }
    public List<ClientSurveyResponseDto> Responses { get; set; } = new();
}

public class ClientSurveyResponseDto
{
    public int ResponseId { get; set; }
    public int SurveyId { get; set; }
    public string SurveyTitle { get; set; } = string.Empty;
    public DateTime CompletedAt { get; set; }
    public bool IsComplete { get; set; }
}
