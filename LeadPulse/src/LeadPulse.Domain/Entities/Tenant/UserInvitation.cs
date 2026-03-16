using LeadPulse.Domain.Enums;

namespace LeadPulse.Domain.Entities.Tenant;

public class UserInvitation
{
    public int Id { get; set; }
    public string Email { get; set; } = string.Empty;
    public UserRole Role { get; set; }
    public int InvitedByUserId { get; set; }
    public string Token { get; set; } = string.Empty;
    public DateTime ExpiresAt { get; set; }
    public DateTime? AcceptedAt { get; set; }
    public DateTime CreatedAt { get; set; }

    public User InvitedBy { get; set; } = null!;
}
