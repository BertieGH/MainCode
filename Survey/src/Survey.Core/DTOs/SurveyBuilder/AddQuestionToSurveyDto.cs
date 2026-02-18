namespace Survey.Core.DTOs.SurveyBuilder;

public class AddQuestionToSurveyDto
{
    public int QuestionBankId { get; set; }
    public bool IsRequired { get; set; }
    public int? OrderIndex { get; set; }
}
