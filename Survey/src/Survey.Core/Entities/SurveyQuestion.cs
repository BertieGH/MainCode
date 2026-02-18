using Survey.Core.Enums;

namespace Survey.Core.Entities;

public class SurveyQuestion
{
    public int Id { get; set; }
    public int SurveyId { get; set; }
    public int QuestionBankId { get; set; }
    public string? QuestionText { get; set; }  // Override if modified
    public QuestionType QuestionType { get; set; }
    public bool IsRequired { get; set; }
    public int OrderIndex { get; set; }
    public bool IsModified { get; set; }  // True if customized from bank
    public DateTime CreatedAt { get; set; }

    // Navigation properties
    public Survey Survey { get; set; } = null!;
    public QuestionBank QuestionBank { get; set; } = null!;
    public ICollection<SurveyQuestionOption> Options { get; set; } = new List<SurveyQuestionOption>();
    public ICollection<ResponseAnswer> ResponseAnswers { get; set; } = new List<ResponseAnswer>();
}
