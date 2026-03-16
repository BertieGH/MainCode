namespace LeadPulse.Domain.Entities.Tenant;

public class ProspectSignal
{
    public int Id { get; set; }
    public int ProspectId { get; set; }
    public long SignalId { get; set; }

    public Prospect Prospect { get; set; } = null!;
    public Signal Signal { get; set; } = null!;
}
