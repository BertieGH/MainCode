namespace Survey.Core.DTOs.FieldMapping;

public class FieldMappingDto
{
    public int Id { get; set; }
    public string CrmFieldName { get; set; } = string.Empty;
    public string SurveyFieldName { get; set; } = string.Empty;
    public string FieldType { get; set; } = string.Empty;
    public bool IsRequired { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime UpdatedAt { get; set; }
}

public class CreateFieldMappingDto
{
    public string CrmFieldName { get; set; } = string.Empty;
    public string SurveyFieldName { get; set; } = string.Empty;
    public string FieldType { get; set; } = string.Empty;
    public bool IsRequired { get; set; }
}

public class UpdateFieldMappingDto
{
    public string CrmFieldName { get; set; } = string.Empty;
    public string SurveyFieldName { get; set; } = string.Empty;
    public string FieldType { get; set; } = string.Empty;
    public bool IsRequired { get; set; }
}

public class TestMappingDto
{
    public Dictionary<string, string> SampleData { get; set; } = new();
}

public class TestMappingResultDto
{
    public Dictionary<string, string> MappedData { get; set; } = new();
    public List<string> Errors { get; set; } = new();
    public bool IsValid { get; set; }
}
