namespace Survey.Core.Entities;

public class Response
{
    public int Id { get; set; }
    public int SurveyId { get; set; }
    public string CrmClientId { get; set; } = string.Empty;  // Links to CRM
    public string? ClientData { get; set; }  // JSON with mapped CRM fields
    public DateTime StartedAt { get; set; }
    public DateTime? CompletedAt { get; set; }
    public bool IsComplete { get; set; }
    public string? IpAddress { get; set; }
    public string? UserAgent { get; set; }
    public DateTime CreatedAt { get; set; }

    // Navigation properties
    public Survey Survey { get; set; } = null!;
    public ICollection<ResponseAnswer> Answers { get; set; } = new List<ResponseAnswer>();
}
