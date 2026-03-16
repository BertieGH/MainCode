using LeadPulse.Domain.Enums;

namespace LeadPulse.Domain.Entities.Tenant;

public class Prospect
{
    public int Id { get; set; }
    public string Name { get; set; } = string.Empty;
    public string? Phone { get; set; }
    public string? Email { get; set; }
    public string? Address { get; set; }
    public string? City { get; set; }
    public string? State { get; set; }
    public string? Zip { get; set; }
    public string? Company { get; set; }
    public string? LinkedInUrl { get; set; }
    public int CompositeScore { get; set; }
    public Urgency Urgency { get; set; } = Urgency.Cool;
    public string? Category { get; set; }
    public string? Platform { get; set; }
    public string? SignalSnippet { get; set; }
    public EnrichmentStatus EnrichmentStatus { get; set; } = EnrichmentStatus.Pending;
    public ProspectStatus Status { get; set; } = ProspectStatus.New;
    public int? AssignedToUserId { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime? UpdatedAt { get; set; }

    public User? AssignedTo { get; set; }
    public ICollection<ProspectSignal> ProspectSignals { get; set; } = new List<ProspectSignal>();
    public ICollection<CallLog> CallLogs { get; set; } = new List<CallLog>();
}
