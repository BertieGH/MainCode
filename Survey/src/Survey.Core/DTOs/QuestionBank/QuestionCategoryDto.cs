namespace Survey.Core.DTOs.QuestionBank;

public class QuestionCategoryDto
{
    public int Id { get; set; }
    public string Name { get; set; } = string.Empty;
    public string? Description { get; set; }
    public int? ParentCategoryId { get; set; }
    public string? ParentCategoryName { get; set; }
    public DateTime CreatedAt { get; set; }
    public List<QuestionCategoryDto> SubCategories { get; set; } = new();
    public int QuestionCount { get; set; }
}
