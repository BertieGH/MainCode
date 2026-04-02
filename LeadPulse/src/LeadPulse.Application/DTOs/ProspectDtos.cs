namespace LeadPulse.Application.DTOs;

public class ProspectResponse
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
    public int? IntentScore { get; set; }
    public string? Sentiment { get; set; }
    public string Urgency { get; set; } = string.Empty;
    public string? Category { get; set; }
    public string? Platform { get; set; }
    public string? SignalSnippet { get; set; }
    public string? PostUrl { get; set; }
    public string EnrichmentStatus { get; set; } = string.Empty;
    public string Status { get; set; } = string.Empty;
    public int? AssignedToUserId { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime? UpdatedAt { get; set; }
}

public class ProspectFilterRequest
{
    public string? Category { get; set; }
    public string? Urgency { get; set; }
    public int? MinScore { get; set; }
    public int? MaxScore { get; set; }
    public string? Platform { get; set; }
    public string? City { get; set; }
    public string? State { get; set; }
    public string? Zip { get; set; }
    public string? Status { get; set; }
    public DateTime? DateFrom { get; set; }
    public DateTime? DateTo { get; set; }
    public string? SortBy { get; set; }
    public bool SortDesc { get; set; } = true;
    public int Page { get; set; } = 1;
    public int PageSize { get; set; } = 20;
}

public class ProspectListResponse
{
    public List<ProspectResponse> Items { get; set; } = new();
    public int TotalCount { get; set; }
    public int Page { get; set; }
    public int PageSize { get; set; }
    public int TotalPages { get; set; }
}

public class UpdateProspectStatusRequest
{
    public string Status { get; set; } = string.Empty;
}

public class EnrichProspectRequest
{
    public string? Phone { get; set; }
    public string? Email { get; set; }
    public string? Address { get; set; }
    public string? City { get; set; }
    public string? State { get; set; }
    public string? Zip { get; set; }
    public string? Company { get; set; }
    public string? LinkedInUrl { get; set; }
}

public class EnrichmentSettingsRequest
{
    public string Provider { get; set; } = string.Empty; // "ContactOut" or "Apollo"
    public string? Username { get; set; }
    public string? Password { get; set; }
    public string? ApiKey { get; set; }
    public bool IsEnabled { get; set; }
}

public class TestConnectionRequest
{
    public string Provider { get; set; } = string.Empty;
}

public class EnrichmentSettingsResponse
{
    public string Provider { get; set; } = string.Empty;
    public string? Username { get; set; }
    public bool HasPassword { get; set; }
    public bool HasApiKey { get; set; }
    public bool IsEnabled { get; set; }
    public DateTime? UpdatedAt { get; set; }
}
