using Survey.Core.Enums;

namespace Survey.Core.DTOs.QuestionBank;

public class QuestionBankDto
{
    public int Id { get; set; }
    public string QuestionText { get; set; } = string.Empty;
    public QuestionType QuestionType { get; set; }
    public int? CategoryId { get; set; }
    public string? CategoryName { get; set; }
    public int Version { get; set; }
    public bool IsActive { get; set; }
    public string? Tags { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime UpdatedAt { get; set; }
    public string? CreatedBy { get; set; }
    public List<QuestionBankOptionDto> Options { get; set; } = new();
}
