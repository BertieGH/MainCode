namespace Survey.Core.DTOs.SurveyBuilder;

public class CreateSurveyDto
{
    public string Title { get; set; } = string.Empty;
    public string? Description { get; set; }
    public string? CreatedBy { get; set; }
}
