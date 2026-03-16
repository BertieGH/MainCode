namespace LeadPulse.Domain.Entities.Tenant;

public class ApiUsageLog
{
    public int Id { get; set; }
    public string Service { get; set; } = string.Empty;
    public int CallCount { get; set; }
    public decimal Cost { get; set; }
    public DateTime Date { get; set; }
}
