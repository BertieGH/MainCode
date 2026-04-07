namespace LeadPulse.Application.DTOs;

public class IntentAnalysisResult
{
    public int IntentScore { get; set; }
    public string IntentCategory { get; set; } = "None";
    public string Sentiment { get; set; } = "Neutral";
    public string Summary { get; set; } = string.Empty;
    public string? Phone { get; set; }
    public string? Email { get; set; }
}

public class AiSettingsRequest
{
    public string AiProvider { get; set; } = "Local";
    public string? ApiKey { get; set; }
    public string? AiModel { get; set; }
}

public class AiSettingsResponse
{
    public string AiProvider { get; set; } = "Local";
    public bool HasApiKey { get; set; }
    public string? AiModel { get; set; }
    public DateTime? UpdatedAt { get; set; }
}

public class ScraperSettingsRequest
{
    public string? ApiKey { get; set; }
    public string? AiModel { get; set; }
}

public class ScraperSettingsResponse
{
    public bool HasApiKey { get; set; }
    public string AiModel { get; set; } = "claude-sonnet-4-6";
    public DateTime? UpdatedAt { get; set; }
}
