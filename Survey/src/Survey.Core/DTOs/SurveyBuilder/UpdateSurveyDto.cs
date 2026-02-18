using Survey.Core.Enums;

namespace Survey.Core.DTOs.SurveyBuilder;

public class UpdateSurveyDto
{
    public string Title { get; set; } = string.Empty;
    public string? Description { get; set; }
}

public class UpdateSurveyStatusDto
{
    public SurveyStatus Status { get; set; }
}
