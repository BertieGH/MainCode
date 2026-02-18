namespace Survey.Core.DTOs.SurveyBuilder;

public class ModifySurveyQuestionDto
{
    public string? QuestionText { get; set; }
    public bool IsRequired { get; set; }
    public List<ModifySurveyQuestionOptionDto>? Options { get; set; }
}

public class ModifySurveyQuestionOptionDto
{
    public int? Id { get; set; }
    public string OptionText { get; set; } = string.Empty;
    public int OrderIndex { get; set; }
}
