namespace Survey.Core.Entities;

public class ResponseAnswer
{
    public int Id { get; set; }
    public int ResponseId { get; set; }
    public int SurveyQuestionId { get; set; }
    public string? AnswerText { get; set; }
    public List<int>? SelectedOptionIds { get; set; }  // For multi-choice
    public DateTime CreatedAt { get; set; }

    // Navigation properties
    public Response Response { get; set; } = null!;
    public SurveyQuestion SurveyQuestion { get; set; } = null!;
}
