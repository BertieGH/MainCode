using LeadPulse.Domain.Enums;

namespace LeadPulse.Domain.Entities.App;

public class PlatformUser
{
    public int Id { get; set; }
    public string Email { get; set; } = string.Empty;
    public string PasswordHash { get; set; } = string.Empty;
    public string? FirstName { get; set; }
    public string? LastName { get; set; }
    public bool MfaEnabled { get; set; }
    public string? MfaSecret { get; set; }
    public PlatformUserStatus Status { get; set; } = PlatformUserStatus.Active;
    public DateTime? LastLoginAt { get; set; }
    public DateTime CreatedAt { get; set; }
}
