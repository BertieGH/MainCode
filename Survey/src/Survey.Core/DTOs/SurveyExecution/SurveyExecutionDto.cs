using Survey.Core.DTOs.SurveyBuilder;

namespace Survey.Core.DTOs.SurveyExecution;

public class SurveyExecutionDto
{
    public int SurveyId { get; set; }
    public string SurveyTitle { get; set; } = string.Empty;
    public string? Description { get; set; }
    public List<ExecutionQuestionDto> Questions { get; set; } = new();
    public Dictionary<string, string> ClientData { get; set; } = new();
    public string CrmClientId { get; set; } = string.Empty;
}

public class ExecutionQuestionDto
{
    public int SurveyQuestionId { get; set; }
    public string QuestionText { get; set; } = string.Empty;
    public string QuestionType { get; set; } = string.Empty;
    public bool IsRequired { get; set; }
    public int OrderIndex { get; set; }
    public List<ExecutionOptionDto> Options { get; set; } = new();
}

public class ExecutionOptionDto
{
    public int Id { get; set; }
    public string OptionText { get; set; } = string.Empty;
    public int OrderIndex { get; set; }
}

public class StartSurveyDto
{
    public int SurveyId { get; set; }
    public string CrmClientId { get; set; } = string.Empty;
    public Dictionary<string, string> ClientData { get; set; } = new();
}

public class SubmitAnswerDto
{
    public int SurveyQuestionId { get; set; }
    public string? AnswerText { get; set; }
    public List<int>? SelectedOptionIds { get; set; }
}

public class SubmitResponseDto
{
    public int ResponseId { get; set; }
    public List<SubmitAnswerDto> Answers { get; set; } = new();
}

public class ResponseDto
{
    public int Id { get; set; }
    public int SurveyId { get; set; }
    public string CrmClientId { get; set; } = string.Empty;
    public Dictionary<string, string>? ClientData { get; set; }
    public DateTime StartedAt { get; set; }
    public DateTime? CompletedAt { get; set; }
    public bool IsComplete { get; set; }
    public List<ResponseAnswerDto> Answers { get; set; } = new();
}

public class ResponseAnswerDto
{
    public int Id { get; set; }
    public int SurveyQuestionId { get; set; }
    public string? AnswerText { get; set; }
    public List<int>? SelectedOptionIds { get; set; }
}
