namespace Survey.Core.DTOs.QuestionBank;

public class QuestionBankOptionDto
{
    public int Id { get; set; }
    public string OptionText { get; set; } = string.Empty;
    public int OrderIndex { get; set; }
}
