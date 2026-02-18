using Survey.Core.Enums;

namespace Survey.Core.DTOs.Analytics;

public class QuestionAnalyticsDto
{
    public int QuestionId { get; set; }
    public string QuestionText { get; set; } = string.Empty;
    public QuestionType QuestionType { get; set; }
    public int TotalAnswers { get; set; }
    public Dictionary<string, int> OptionDistribution { get; set; } = new();
    public double? AverageRating { get; set; }
    public List<string> TextResponses { get; set; } = new();
    public int YesCount { get; set; }
    public int NoCount { get; set; }
}
