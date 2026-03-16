using System.Net.Http.Json;
using System.Text.Json;
using LeadPulse.Application.Interfaces;
using Microsoft.Extensions.Logging;

namespace LeadPulse.Infrastructure.PlatformAdapters;

public class RedditAdapter : ISocialPlatformAdapter
{
    private readonly HttpClient _httpClient;
    private readonly ILogger<RedditAdapter> _logger;

    public RedditAdapter(HttpClient httpClient, ILogger<RedditAdapter> logger)
    {
        _httpClient = httpClient;
        _logger = logger;
    }

    public string Platform => "Reddit";

    public Task<LoginResult> TestLoginAsync(string username, string password, string? mfaSecret)
    {
        // Reddit public API doesn't require login — always passes
        return Task.FromResult(new LoginResult { Success = true });
    }

    public async Task<ScrapeResult> ScrapePostsAsync(
        string username, string password, string? mfaSecret, int maxPosts, string scrapeDepth, List<string>? targetUrls = null)
    {
        try
        {
            // Username is treated as the subreddit or search context
            // Password field is used as additional search keywords (optional)
            var subreddit = username.Trim().TrimStart('/').Replace("r/", "");
            var additionalKeywords = password; // Repurpose password as search keywords for Reddit

            var posts = new List<ScrapedPost>();

            // Search insurance-related subreddits
            var searchTerms = new[]
            {
                "insurance",
                "car insurance",
                "home insurance",
                "life insurance",
                "health insurance",
                "need insurance agent",
                "looking for insurance",
                "insurance recommendations"
            };

            // If additional keywords provided, add them
            if (!string.IsNullOrWhiteSpace(additionalKeywords) && additionalKeywords != "N/A")
            {
                searchTerms = searchTerms.Concat(additionalKeywords.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)).ToArray();
            }

            // Parse scrape depth (e.g., "48h", "7d")
            var depthHours = ParseDepthToHours(scrapeDepth);
            var cutoffDate = DateTime.UtcNow.AddHours(-depthHours);

            // Search Reddit using public JSON API
            foreach (var term in searchTerms.Take(5)) // Limit to 5 searches to respect rate limits
            {
                if (posts.Count >= maxPosts) break;

                try
                {
                    var remaining = maxPosts - posts.Count;
                    var limit = Math.Min(remaining, 25);
                    var url = string.IsNullOrEmpty(subreddit) || subreddit.Equals("all", StringComparison.OrdinalIgnoreCase)
                        ? $"https://www.reddit.com/search.json?q={Uri.EscapeDataString(term)}&sort=new&limit={limit}&t=week"
                        : $"https://www.reddit.com/r/{Uri.EscapeDataString(subreddit)}/search.json?q={Uri.EscapeDataString(term)}&sort=new&limit={limit}&restrict_sr=on&t=week";

                    _logger.LogInformation("Fetching Reddit posts: {Url}", url);

                    var response = await _httpClient.GetAsync(url);

                    if (!response.IsSuccessStatusCode)
                    {
                        _logger.LogWarning("Reddit API returned {StatusCode} for search: {Term}", response.StatusCode, term);
                        continue;
                    }

                    var json = await response.Content.ReadAsStringAsync();
                    var doc = JsonDocument.Parse(json);

                    var children = doc.RootElement
                        .GetProperty("data")
                        .GetProperty("children");

                    foreach (var child in children.EnumerateArray())
                    {
                        if (posts.Count >= maxPosts) break;

                        var data = child.GetProperty("data");

                        // Skip removed/deleted posts
                        var selftext = data.TryGetProperty("selftext", out var st) ? st.GetString() ?? "" : "";
                        var title = data.TryGetProperty("title", out var t) ? t.GetString() ?? "" : "";

                        if (selftext == "[removed]" || selftext == "[deleted]") continue;
                        if (string.IsNullOrWhiteSpace(title) && string.IsNullOrWhiteSpace(selftext)) continue;

                        // Parse post date
                        var createdUtc = data.TryGetProperty("created_utc", out var cu) ? cu.GetDouble() : 0;
                        var postDate = DateTimeOffset.FromUnixTimeSeconds((long)createdUtc).UtcDateTime;

                        if (postDate < cutoffDate) continue;

                        var author = data.TryGetProperty("author", out var a) ? a.GetString() ?? "unknown" : "unknown";
                        if (author == "[deleted]") continue;

                        var permalink = data.TryGetProperty("permalink", out var pl) ? pl.GetString() ?? "" : "";
                        var subredditName = data.TryGetProperty("subreddit", out var sr) ? sr.GetString() ?? "" : "";

                        var content = !string.IsNullOrWhiteSpace(selftext)
                            ? $"{title}\n\n{selftext}"
                            : title;

                        // Deduplicate by URL
                        var postUrl = $"https://www.reddit.com{permalink}";
                        if (posts.Any(p => p.PostUrl == postUrl)) continue;

                        posts.Add(new ScrapedPost
                        {
                            AuthorName = $"u/{author}",
                            AuthorProfileUrl = $"https://www.reddit.com/user/{author}",
                            Content = content,
                            PostUrl = postUrl,
                            PostDate = postDate
                        });
                    }

                    // Rate limit: Reddit allows ~60 req/min without auth
                    await Task.Delay(1500);
                }
                catch (Exception ex)
                {
                    _logger.LogWarning(ex, "Failed to fetch Reddit posts for search term: {Term}", term);
                }
            }

            _logger.LogInformation("Reddit scrape complete: {Count} posts found", posts.Count);

            return new ScrapeResult
            {
                Success = true,
                Posts = posts
            };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Reddit scrape failed");
            return new ScrapeResult
            {
                Success = false,
                ErrorMessage = ex.Message
            };
        }
    }

    private static int ParseDepthToHours(string scrapeDepth)
    {
        if (string.IsNullOrWhiteSpace(scrapeDepth)) return 48;

        scrapeDepth = scrapeDepth.Trim().ToLower();

        if (scrapeDepth.EndsWith("h") && int.TryParse(scrapeDepth[..^1], out var hours))
            return hours;
        if (scrapeDepth.EndsWith("d") && int.TryParse(scrapeDepth[..^1], out var days))
            return days * 24;

        return 48; // Default
    }
}
