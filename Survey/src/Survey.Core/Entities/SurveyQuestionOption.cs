namespace Survey.Core.Entities;

public class SurveyQuestionOption
{
    public int Id { get; set; }
    public int SurveyQuestionId { get; set; }
    public string OptionText { get; set; } = string.Empty;
    public int OrderIndex { get; set; }

    // Navigation properties
    public SurveyQuestion SurveyQuestion { get; set; } = null!;
}
