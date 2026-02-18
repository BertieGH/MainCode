using Survey.Core.Enums;

namespace Survey.Core.DTOs.SurveyBuilder;

public class SurveyDto
{
    public int Id { get; set; }
    public string Title { get; set; } = string.Empty;
    public string? Description { get; set; }
    public SurveyStatus Status { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime UpdatedAt { get; set; }
    public string? CreatedBy { get; set; }
    public int QuestionCount { get; set; }
    public List<SurveyQuestionDto> Questions { get; set; } = new();
}
