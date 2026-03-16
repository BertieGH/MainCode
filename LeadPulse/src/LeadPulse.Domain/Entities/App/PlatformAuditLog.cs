namespace LeadPulse.Domain.Entities.App;

public class PlatformAuditLog
{
    public long Id { get; set; }
    public int? PlatformUserId { get; set; }
    public string Action { get; set; } = string.Empty;
    public int? TargetTenantId { get; set; }
    public string? Details { get; set; }
    public string? IpAddress { get; set; }
    public DateTime CreatedAt { get; set; }
}
