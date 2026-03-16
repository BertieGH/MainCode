namespace LeadPulse.Domain.Entities.Tenant;

public class EnrichmentSettings
{
    public int Id { get; set; }
    public string Provider { get; set; } = string.Empty; // "ContactOut" or "Apollo"
    public string? Username { get; set; }
    public string? EncryptedPassword { get; set; }
    public string? EncryptedApiKey { get; set; }
    public bool IsEnabled { get; set; }
    public DateTime UpdatedAt { get; set; }
}
