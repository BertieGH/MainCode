using Survey.Core.Enums;

namespace Survey.Core.Entities;

public class QuestionBank
{
    public int Id { get; set; }
    public string QuestionText { get; set; } = string.Empty;
    public QuestionType QuestionType { get; set; }
    public int? CategoryId { get; set; }
    public int Version { get; set; }
    public bool IsActive { get; set; }
    public string? Tags { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime UpdatedAt { get; set; }
    public string? CreatedBy { get; set; }

    // Navigation properties
    public QuestionCategory? Category { get; set; }
    public ICollection<QuestionBankOption> Options { get; set; } = new List<QuestionBankOption>();
    public ICollection<SurveyQuestion> SurveyQuestions { get; set; } = new List<SurveyQuestion>();
}
