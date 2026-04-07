namespace LeadPulse.Domain.Entities.Tenant;

public class LinkedInScraperSettings
{
    public int Id { get; set; }
    public string? EncryptedApiKey { get; set; }
    public string AiModel { get; set; } = "claude-sonnet-4-6";
    public DateTime UpdatedAt { get; set; }
}
