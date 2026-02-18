namespace Survey.Core.DTOs.SurveyBuilder;

public class ReorderQuestionsDto
{
    public List<QuestionOrderDto> Questions { get; set; } = new();
}

public class QuestionOrderDto
{
    public int SurveyQuestionId { get; set; }
    public int OrderIndex { get; set; }
}
