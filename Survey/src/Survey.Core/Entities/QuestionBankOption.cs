namespace Survey.Core.Entities;

public class QuestionBankOption
{
    public int Id { get; set; }
    public int QuestionBankId { get; set; }
    public string OptionText { get; set; } = string.Empty;
    public int OrderIndex { get; set; }

    // Navigation properties
    public QuestionBank QuestionBank { get; set; } = null!;
}
