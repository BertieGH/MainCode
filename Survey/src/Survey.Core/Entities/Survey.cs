using Survey.Core.Enums;

namespace Survey.Core.Entities;

public class Survey
{
    public int Id { get; set; }
    public string Title { get; set; } = string.Empty;
    public string? Description { get; set; }
    public SurveyStatus Status { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime UpdatedAt { get; set; }
    public string? CreatedBy { get; set; }

    // Navigation properties
    public ICollection<SurveyQuestion> Questions { get; set; } = new List<SurveyQuestion>();
    public ICollection<Response> Responses { get; set; } = new List<Response>();
}
