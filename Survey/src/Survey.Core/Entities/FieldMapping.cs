namespace Survey.Core.Entities;

public class FieldMapping
{
    public int Id { get; set; }
    public string CrmFieldName { get; set; } = string.Empty;
    public string SurveyFieldName { get; set; } = string.Empty;
    public string FieldType { get; set; } = string.Empty;
    public bool IsRequired { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime UpdatedAt { get; set; }
}
