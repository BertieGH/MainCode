using System.ComponentModel.DataAnnotations;

namespace LeadPulse.Application.DTOs;

public class CreateTenantRequest
{
    [Required, MaxLength(200)]
    public string Name { get; set; } = string.Empty;

    [Required, MaxLength(100), RegularExpression(@"^[a-z0-9\-]+$", ErrorMessage = "Slug must be lowercase alphanumeric with hyphens only")]
    public string Slug { get; set; } = string.Empty;

    [MaxLength(100)]
    public string? Industry { get; set; }

    [Required]
    public int PlanId { get; set; }

    [EmailAddress]
    public string? BillingEmail { get; set; }
}
