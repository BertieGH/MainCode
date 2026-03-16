namespace LeadPulse.Domain.Entities.Tenant;

public class AiSettings
{
    public int Id { get; set; }
    public string AiProvider { get; set; } = "Local"; // Local, Claude, OpenAI
    public string? EncryptedApiKey { get; set; }
    public string? AiModel { get; set; }
    public DateTime UpdatedAt { get; set; }
}
