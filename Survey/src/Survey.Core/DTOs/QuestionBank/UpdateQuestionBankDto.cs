using Survey.Core.Enums;

namespace Survey.Core.DTOs.QuestionBank;

public class UpdateQuestionBankDto
{
    public string QuestionText { get; set; } = string.Empty;
    public QuestionType QuestionType { get; set; }
    public int? CategoryId { get; set; }
    public string? Tags { get; set; }
    public List<CreateQuestionBankOptionDto> Options { get; set; } = new();
}
