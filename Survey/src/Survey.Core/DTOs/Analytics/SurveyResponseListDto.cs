namespace Survey.Core.DTOs.Analytics;

public class SurveyResponseListDto
{
    public int ResponseId { get; set; }
    public string CrmClientId { get; set; } = string.Empty;
    public DateTime StartedAt { get; set; }
    public DateTime? CompletedAt { get; set; }
    public bool IsComplete { get; set; }
}

public class ResponseDetailDto
{
    public int ResponseId { get; set; }
    public int SurveyId { get; set; }
    public string SurveyTitle { get; set; } = string.Empty;
    public string CrmClientId { get; set; } = string.Empty;
    public DateTime StartedAt { get; set; }
    public DateTime? CompletedAt { get; set; }
    public bool IsComplete { get; set; }
    public List<ResponseAnswerDetailDto> Answers { get; set; } = new();
}

public class ResponseAnswerDetailDto
{
    public int SurveyQuestionId { get; set; }
    public string QuestionText { get; set; } = string.Empty;
    public string QuestionType { get; set; } = string.Empty;
    public string? AnswerText { get; set; }
    public List<string> SelectedOptions { get; set; } = new();
}
