namespace LeadPulse.Domain.Entities.Tenant;

public class LinkedInPost
{
    public int Id { get; set; }
    public int ProspectId { get; set; }
    public string Content { get; set; } = string.Empty;
    public string? PostUrl { get; set; }
    public DateTime? PostDate { get; set; }
    public int Likes { get; set; }
    public int Comments { get; set; }
    public DateTime ScrapedAt { get; set; }

    public Prospect Prospect { get; set; } = null!;
}
