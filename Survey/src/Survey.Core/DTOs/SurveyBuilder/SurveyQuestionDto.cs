using Survey.Core.Enums;

namespace Survey.Core.DTOs.SurveyBuilder;

public class SurveyQuestionDto
{
    public int Id { get; set; }
    public int SurveyId { get; set; }
    public int QuestionBankId { get; set; }
    public string QuestionText { get; set; } = string.Empty;
    public QuestionType QuestionType { get; set; }
    public bool IsRequired { get; set; }
    public bool IsActive { get; set; }
    public int OrderIndex { get; set; }
    public bool IsModified { get; set; }
    public DateTime CreatedAt { get; set; }
    public List<SurveyQuestionOptionDto> Options { get; set; } = new();
}

public class SurveyQuestionOptionDto
{
    public int Id { get; set; }
    public string OptionText { get; set; } = string.Empty;
    public int OrderIndex { get; set; }
}
