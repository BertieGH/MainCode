using System.ComponentModel.DataAnnotations;

namespace LeadPulse.Application.DTOs;

public class CreateSocialAccountRequest
{
    [Required]
    public string Platform { get; set; } = string.Empty;

    [Required]
    public string Username { get; set; } = string.Empty;

    public string? Password { get; set; }

    public string? MfaSecret { get; set; }
}

public class UpdateSyncConfigRequest
{
    [Range(60, 2880)]
    public int SyncFrequencyMinutes { get; set; } = 360;

    public string? SyncWindowStart { get; set; }
    public string? SyncWindowEnd { get; set; }

    [Range(10, 5000)]
    public int MaxPostsPerSync { get; set; } = 500;

    public string ScrapeDepth { get; set; } = "48h";

    [Range(0, 10)]
    public int AutoRetryMax { get; set; } = 3;
}

public class UpdateCredentialsRequest
{
    [Required]
    public string Username { get; set; } = string.Empty;

    [Required]
    public string Password { get; set; } = string.Empty;

    public string? MfaSecret { get; set; }
}

public class SocialAccountResponse
{
    public int Id { get; set; }
    public string Platform { get; set; } = string.Empty;
    public string Username { get; set; } = string.Empty;
    // Password is NEVER returned
    public int SyncFrequencyMinutes { get; set; }
    public string? SyncWindowStart { get; set; }
    public string? SyncWindowEnd { get; set; }
    public int MaxPostsPerSync { get; set; }
    public string ScrapeDepth { get; set; } = string.Empty;
    public int AutoRetryMax { get; set; }
    public string Status { get; set; } = string.Empty;
    public DateTime? LastLoginAt { get; set; }
    public DateTime? LastSyncAt { get; set; }
    public int TotalPostsScraped { get; set; }
    public DateTime CreatedAt { get; set; }
}

public class MonitoredGroupRequest
{
    [Required]
    public string GroupUrl { get; set; } = string.Empty;

    public string? GroupName { get; set; }
}

public class MonitoredGroupResponse
{
    public int Id { get; set; }
    public int SocialAccountId { get; set; }
    public string Platform { get; set; } = string.Empty;
    public string GroupUrl { get; set; } = string.Empty;
    public string? GroupName { get; set; }
    public bool IsActive { get; set; }
}

public class SyncJobResponse
{
    public int Id { get; set; }
    public int SocialAccountId { get; set; }
    public string Status { get; set; } = string.Empty;
    public int PostsFound { get; set; }
    public int SignalsGenerated { get; set; }
    public DateTime? StartedAt { get; set; }
    public DateTime? CompletedAt { get; set; }
    public int? DurationSeconds { get; set; }
    public string? ErrorMessage { get; set; }
    public int RetryCount { get; set; }
    public DateTime CreatedAt { get; set; }
}
