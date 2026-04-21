namespace LeadPulse.Domain.Entities.Tenant;

public class LinkedInScraperSettings
{
    public int Id { get; set; }
    public string? EncryptedApiKey { get; set; }
    public string AiModel { get; set; } = "claude-sonnet-4-6";
    public string? EncryptedLinkedInCookie { get; set; }
    public DateTime? LinkedInCookieExpiresAt { get; set; }
    public DateTime UpdatedAt { get; set; }
}
