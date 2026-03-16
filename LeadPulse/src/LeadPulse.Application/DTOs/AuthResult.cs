namespace LeadPulse.Application.DTOs;

public class AuthResult
{
    public bool Success { get; set; }
    public string? Token { get; set; }
    public string? Error { get; set; }
    public int? UserId { get; set; }
    public int? TenantId { get; set; }
    public string? Role { get; set; }
    public bool ForcePasswordChange { get; set; }

    public static AuthResult Failed(string error) => new() { Success = false, Error = error };

    public static AuthResult Succeeded(string token, int userId, int? tenantId, string role, bool forcePasswordChange = false)
        => new()
        {
            Success = true,
            Token = token,
            UserId = userId,
            TenantId = tenantId,
            Role = role,
            ForcePasswordChange = forcePasswordChange
        };
}
