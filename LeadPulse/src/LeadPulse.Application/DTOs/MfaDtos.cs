using System.ComponentModel.DataAnnotations;

namespace LeadPulse.Application.DTOs;

public class MfaVerifyRequest
{
    [Required, StringLength(6, MinimumLength = 6)]
    public string Code { get; set; } = string.Empty;
}
