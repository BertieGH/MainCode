using System.Text;
using System.Text.Json;
using LeadPulse.Application.Interfaces;
using LeadPulse.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Microsoft.Playwright;

namespace LeadPulse.Infrastructure.Services;

public class LinkedInProfileData
{
    public string? Type { get; set; } // "Individual" or "Company"
    public string? Name { get; set; }
    public string? Headline { get; set; }
    public string? About { get; set; }
    public string? PhotoUrl { get; set; }
    public string? ContactInfo { get; set; } // JSON string
}

public class LinkedInPostData
{
    public string Content { get; set; } = string.Empty;
    public string? PostUrl { get; set; }
    public DateTime? PostDate { get; set; }
    public int Likes { get; set; }
    public int Comments { get; set; }
}

public class ScrapeResult
{
    public bool Success { get; set; }
    public string? Error { get; set; }
    public LinkedInProfileData? Profile { get; set; }
    public List<LinkedInPostData> Posts { get; set; } = new();
}

public class LinkedInScraperService
{
    private readonly TenantDbContext _tenantDb;
    private readonly IEncryptionService _encryptionService;
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly ILogger<LinkedInScraperService> _logger;

    public LinkedInScraperService(
        TenantDbContext tenantDb,
        IEncryptionService encryptionService,
        IHttpClientFactory httpClientFactory,
        ILogger<LinkedInScraperService> logger)
    {
        _tenantDb = tenantDb;
        _encryptionService = encryptionService;
        _httpClientFactory = httpClientFactory;
        _logger = logger;
    }

    public async Task<ScrapeResult> ScrapeProfileAsync(int tenantId, string linkedInUrl)
    {
        var (apiKey, model) = await GetClaudeApiKeyAsync(tenantId);
        if (apiKey == null)
            return new ScrapeResult { Success = false, Error = "Claude API key not configured. Set up AI settings first." };

        try
        {
            var (screenshotBase64, pageText, pageTitle) = await BrowsePageAsync(linkedInUrl);
            var isCompany = linkedInUrl.Contains("/company/");
            var profile = await ExtractProfileWithClaudeAsync(apiKey, model, screenshotBase64, pageText, pageTitle, isCompany);
            return new ScrapeResult { Success = true, Profile = profile };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "LinkedIn profile scrape failed for {Url}", linkedInUrl);
            return new ScrapeResult { Success = false, Error = $"Scrape failed: {ex.Message}" };
        }
    }

    public async Task<ScrapeResult> ScrapePostsAsync(int tenantId, string linkedInUrl)
    {
        var (apiKey, model) = await GetClaudeApiKeyAsync(tenantId);
        if (apiKey == null)
            return new ScrapeResult { Success = false, Error = "Claude API key not configured. Set up AI settings first." };

        try
        {
            var postsUrl = linkedInUrl.TrimEnd('/');
            if (!postsUrl.Contains("/recent-activity"))
                postsUrl += "/recent-activity/all/";

            var (screenshotBase64, pageText, _) = await BrowsePageAsync(postsUrl, scrollCount: 3);
            var posts = await ExtractPostsWithClaudeAsync(apiKey, model, screenshotBase64, pageText);
            return new ScrapeResult { Success = true, Posts = posts };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "LinkedIn posts scrape failed for {Url}", linkedInUrl);
            return new ScrapeResult { Success = false, Error = $"Posts scrape failed: {ex.Message}" };
        }
    }

    private async Task<(string screenshotBase64, string pageText, string pageTitle)> BrowsePageAsync(
        string url, int scrollCount = 0)
    {
        using var playwright = await Playwright.CreateAsync();
        await using var browser = await playwright.Chromium.LaunchAsync(new BrowserTypeLaunchOptions
        {
            Headless = true,
            Args = new[] { "--disable-blink-features=AutomationControlled" }
        });

        var context = await browser.NewContextAsync(new BrowserNewContextOptions
        {
            UserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            ViewportSize = new ViewportSize { Width = 1280, Height = 900 }
        });

        var page = await context.NewPageAsync();
        _logger.LogInformation("Navigating to: {Url}", url);
        await page.GotoAsync(url, new PageGotoOptions { WaitUntil = WaitUntilState.NetworkIdle, Timeout = 30000 });
        await page.WaitForTimeoutAsync(2000);

        for (int i = 0; i < scrollCount; i++)
        {
            await page.EvaluateAsync("window.scrollTo(0, document.body.scrollHeight)");
            await page.WaitForTimeoutAsync(1500);
        }

        var screenshot = await page.ScreenshotAsync(new PageScreenshotOptions { FullPage = true });
        var screenshotBase64 = Convert.ToBase64String(screenshot);
        var pageText = await page.InnerTextAsync("body");
        var pageTitle = await page.TitleAsync();

        await browser.CloseAsync();
        return (screenshotBase64, pageText, pageTitle);
    }

    private async Task<LinkedInProfileData> ExtractProfileWithClaudeAsync(
        string apiKey, string model, string screenshotBase64, string pageText, string pageTitle, bool isCompany)
    {
        var profileType = isCompany ? "Company" : "Individual";
        var truncatedText = pageText.Length > 5000 ? pageText[..5000] : pageText;

        var prompt = isCompany
            ? @"Extract the following from this LinkedIn COMPANY page. Return ONLY valid JSON, no other text:
{
  ""type"": ""Company"",
  ""name"": ""company name"",
  ""headline"": ""company tagline or industry"",
  ""about"": ""full about/overview section text"",
  ""contactInfo"": { ""website"": """", ""industry"": """", ""companySize"": """", ""headquarters"": """" }
}

Page title: " + pageTitle + "\nPage text:\n" + truncatedText
            : @"Extract the following from this LinkedIn INDIVIDUAL profile page. Return ONLY valid JSON, no other text:
{
  ""type"": ""Individual"",
  ""name"": ""full name"",
  ""headline"": ""professional headline"",
  ""about"": ""full about/summary section text"",
  ""contactInfo"": { ""email"": """", ""phone"": """", ""website"": """", ""location"": """" }
}

If a field is not visible, use null. Page title: " + pageTitle + "\nPage text:\n" + truncatedText;

        var responseText = await CallClaudeVisionAsync(apiKey, model, screenshotBase64, prompt, 1024);

        _logger.LogInformation("Claude profile extraction result: {Result}",
            responseText.Length > 200 ? responseText[..200] : responseText);

        using var parsed = JsonDocument.Parse(responseText);
        var root = parsed.RootElement;
        var contactInfoElement = root.TryGetProperty("contactInfo", out var ci) ? ci : default;

        return new LinkedInProfileData
        {
            Type = GetString(root, "type") ?? profileType,
            Name = GetString(root, "name"),
            Headline = GetString(root, "headline"),
            About = GetString(root, "about"),
            ContactInfo = contactInfoElement.ValueKind != JsonValueKind.Undefined ? contactInfoElement.GetRawText() : null
        };
    }

    private async Task<List<LinkedInPostData>> ExtractPostsWithClaudeAsync(
        string apiKey, string model, string screenshotBase64, string pageText)
    {
        var truncatedText = pageText.Length > 8000 ? pageText[..8000] : pageText;

        var prompt = @"Extract LinkedIn posts from this activity page. Return ONLY a valid JSON array, no other text.
Each post should be:
{
  ""content"": ""the post text content"",
  ""postDate"": ""date string if visible, or null"",
  ""likes"": number of likes/reactions (0 if not visible),
  ""comments"": number of comments (0 if not visible)
}

Return up to 10 most recent posts. If no posts found, return [].

Page text:
" + truncatedText;

        var responseText = await CallClaudeVisionAsync(apiKey, model, screenshotBase64, prompt, 2048);

        _logger.LogInformation("Claude posts extraction result length: {Len}", responseText.Length);

        var posts = new List<LinkedInPostData>();
        using var parsed = JsonDocument.Parse(responseText);

        if (parsed.RootElement.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in parsed.RootElement.EnumerateArray())
            {
                var post = new LinkedInPostData
                {
                    Content = GetString(item, "content") ?? "",
                    Likes = item.TryGetProperty("likes", out var l) && l.ValueKind == JsonValueKind.Number ? l.GetInt32() : 0,
                    Comments = item.TryGetProperty("comments", out var c) && c.ValueKind == JsonValueKind.Number ? c.GetInt32() : 0
                };

                if (item.TryGetProperty("postDate", out var d) && d.ValueKind == JsonValueKind.String)
                {
                    if (DateTime.TryParse(d.GetString(), out var dt))
                        post.PostDate = dt;
                }

                if (!string.IsNullOrWhiteSpace(post.Content))
                    posts.Add(post);
            }
        }

        return posts;
    }

    private async Task<string> CallClaudeVisionAsync(string apiKey, string model, string screenshotBase64, string prompt, int maxTokens)
    {
        var client = _httpClientFactory.CreateClient();
        var requestBody = new
        {
            model,
            max_tokens = maxTokens,
            messages = new object[]
            {
                new
                {
                    role = "user",
                    content = new object[]
                    {
                        new
                        {
                            type = "image",
                            source = new
                            {
                                type = "base64",
                                media_type = "image/png",
                                data = screenshotBase64
                            }
                        },
                        new
                        {
                            type = "text",
                            text = prompt
                        }
                    }
                }
            }
        };

        var request = new HttpRequestMessage(HttpMethod.Post, "https://api.anthropic.com/v1/messages");
        request.Headers.Add("x-api-key", apiKey);
        request.Headers.Add("anthropic-version", "2023-06-01");
        request.Content = new StringContent(JsonSerializer.Serialize(requestBody), Encoding.UTF8, "application/json");

        var response = await client.SendAsync(request);
        var responseJson = await response.Content.ReadAsStringAsync();

        if (!response.IsSuccessStatusCode)
        {
            _logger.LogError("Claude API error: {Status} {Body}", response.StatusCode, responseJson);
            throw new Exception($"Claude API error: {response.StatusCode}");
        }

        using var doc = JsonDocument.Parse(responseJson);
        var textContent = doc.RootElement.GetProperty("content")[0].GetProperty("text").GetString() ?? "{}";

        // Clean markdown code blocks
        textContent = textContent.Trim();
        if (textContent.StartsWith("```json")) textContent = textContent[7..];
        if (textContent.StartsWith("```")) textContent = textContent[3..];
        if (textContent.EndsWith("```")) textContent = textContent[..^3];
        return textContent.Trim();
    }

    private async Task<(string? apiKey, string model)> GetClaudeApiKeyAsync(int tenantId)
    {
        // First try dedicated LinkedIn Scraper settings
        var scraperSettings = await _tenantDb.LinkedInScraperSettings.FirstOrDefaultAsync();
        if (scraperSettings != null && !string.IsNullOrEmpty(scraperSettings.EncryptedApiKey))
        {
            try
            {
                var key = _encryptionService.Decrypt(scraperSettings.EncryptedApiKey, tenantId);
                return (key, scraperSettings.AiModel ?? "claude-sonnet-4-6");
            }
            catch { }
        }

        // Fallback to general AI settings (if provider is Claude)
        var aiSettings = await _tenantDb.AiSettings.FirstOrDefaultAsync();
        if (aiSettings != null && !string.IsNullOrEmpty(aiSettings.EncryptedApiKey)
            && aiSettings.AiProvider?.Equals("Claude", StringComparison.OrdinalIgnoreCase) == true)
        {
            try
            {
                var key = _encryptionService.Decrypt(aiSettings.EncryptedApiKey, tenantId);
                return (key, aiSettings.AiModel ?? "claude-sonnet-4-6");
            }
            catch { }
        }

        return (null, "claude-sonnet-4-6");
    }

    private static string? GetString(JsonElement element, string property)
    {
        if (element.TryGetProperty(property, out var prop) && prop.ValueKind == JsonValueKind.String)
            return prop.GetString();
        return null;
    }
}
