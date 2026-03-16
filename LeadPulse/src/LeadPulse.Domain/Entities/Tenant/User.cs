using LeadPulse.Domain.Enums;

namespace LeadPulse.Domain.Entities.Tenant;

public class User
{
    public int Id { get; set; }
    public string FirstName { get; set; } = string.Empty;
    public string LastName { get; set; } = string.Empty;
    public string Email { get; set; } = string.Empty;
    public string PasswordHash { get; set; } = string.Empty;
    public string? Phone { get; set; }
    public UserRole Role { get; set; }
    public string? Permissions { get; set; }
    public bool MfaEnabled { get; set; }
    public string? MfaSecret { get; set; }
    public bool ForcePasswordChange { get; set; } = true;
    public UserStatus Status { get; set; } = UserStatus.Active;
    public DateTime? LastLoginAt { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime? UpdatedAt { get; set; }
}
