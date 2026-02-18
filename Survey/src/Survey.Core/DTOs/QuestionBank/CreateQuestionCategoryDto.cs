namespace Survey.Core.DTOs.QuestionBank;

public class CreateQuestionCategoryDto
{
    public string Name { get; set; } = string.Empty;
    public string? Description { get; set; }
    public int? ParentCategoryId { get; set; }
}
