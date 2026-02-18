using Survey.Core.Enums;

namespace Survey.Core.DTOs.QuestionBank;

public class CreateQuestionBankDto
{
    public string QuestionText { get; set; } = string.Empty;
    public QuestionType QuestionType { get; set; }
    public int? CategoryId { get; set; }
    public string? Tags { get; set; }
    public string? CreatedBy { get; set; }
    public List<CreateQuestionBankOptionDto> Options { get; set; } = new();
}

public class CreateQuestionBankOptionDto
{
    public string OptionText { get; set; } = string.Empty;
    public int OrderIndex { get; set; }
}
