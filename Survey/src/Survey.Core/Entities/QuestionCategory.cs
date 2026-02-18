namespace Survey.Core.Entities;

public class QuestionCategory
{
    public int Id { get; set; }
    public string Name { get; set; } = string.Empty;
    public string? Description { get; set; }
    public int? ParentCategoryId { get; set; }
    public DateTime CreatedAt { get; set; }

    // Navigation properties
    public QuestionCategory? ParentCategory { get; set; }
    public ICollection<QuestionCategory> SubCategories { get; set; } = new List<QuestionCategory>();
    public ICollection<QuestionBank> Questions { get; set; } = new List<QuestionBank>();
}
