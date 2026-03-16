using System.ComponentModel.DataAnnotations;

namespace LeadPulse.Application.DTOs;

public class PlatformLoginRequest
{
    [Required, EmailAddress]
    public string Email { get; set; } = string.Empty;

    [Required]
    public string Password { get; set; } = string.Empty;
}

public class TenantLoginRequest
{
    [Required]
    public int TenantId { get; set; }

    [Required, EmailAddress]
    public string Email { get; set; } = string.Empty;

    [Required]
    public string Password { get; set; } = string.Empty;
}
