namespace LeadPulse.Application.Interfaces;

public interface ISocialPlatformAdapter
{
    string Platform { get; }
    Task<LoginResult> TestLoginAsync(string username, string password, string? mfaSecret);
    Task<ScrapeResult> ScrapePostsAsync(string username, string password, string? mfaSecret, int maxPosts, string scrapeDepth, List<string>? targetUrls = null);
}

public class LoginResult
{
    public bool Success { get; set; }
    public string? ErrorMessage { get; set; }
}

public class ScrapeResult
{
    public bool Success { get; set; }
    public List<ScrapedPost> Posts { get; set; } = new();
    public string? ErrorMessage { get; set; }
}

public class ScrapedPost
{
    public string AuthorName { get; set; } = string.Empty;
    public string? AuthorProfileUrl { get; set; }
    public string Content { get; set; } = string.Empty;
    public string? PostUrl { get; set; }
    public DateTime? PostDate { get; set; }
}
