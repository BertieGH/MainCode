using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
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
    public string? CommentsJson { get; set; } // JSON array of comment texts
}

public class ScrapeResult
{
    public bool Success { get; set; }
    public string? Error { get; set; }
    public List<string> Warnings { get; set; } = new();
    public List<string> DebugLog { get; set; } = new();
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

        var result = new ScrapeResult();

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

        try
        {
            // Step 1: Navigate to profile and extract main data
            result.DebugLog.Add($"Navigating to profile: {linkedInUrl}");
            await page.GotoAsync(linkedInUrl, new PageGotoOptions { WaitUntil = WaitUntilState.Load, Timeout = 30000 });
            await page.WaitForTimeoutAsync(3000);

            var (screenshotBase64, pageText, pageTitle) = await CapturePageAsync(page);
            result.DebugLog.Add($"Profile page loaded ({screenshotBase64.Length / 1024}KB screenshot)");

            var isCompany = linkedInUrl.Contains("/company/");
            var profile = await ExtractProfileWithClaudeAsync(apiKey, model, screenshotBase64, pageText, pageTitle, isCompany);
            result.Profile = profile;
            result.DebugLog.Add($"Profile extracted: {profile.Name} ({profile.Type})");

            // Step 2: Try contact info overlay (only for individual profiles)
            if (!isCompany)
            {
                await TryExtractContactInfoOverlay(page, linkedInUrl, apiKey, model, profile, result);
            }

            result.Success = true;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "LinkedIn profile scrape failed for {Url}", linkedInUrl);
            result.Error = $"Scrape failed: {ex.Message}";
            result.DebugLog.Add($"ERROR: {ex.Message}");
            // If we got the profile before the error, still return it
            if (result.Profile != null)
                result.Success = true;
        }

        return result;
    }

    public async Task<ScrapeResult> ScrapePostsAsync(int tenantId, string linkedInUrl)
    {
        var (apiKey, model) = await GetClaudeApiKeyAsync(tenantId);
        if (apiKey == null)
            return new ScrapeResult { Success = false, Error = "Claude API key not configured. Set up AI settings first." };

        var result = new ScrapeResult();

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

        try
        {
            var postsUrl = linkedInUrl.TrimEnd('/');
            if (!postsUrl.Contains("/recent-activity"))
                postsUrl += "/recent-activity/all/";

            // Step 1: Navigate to activity feed and scroll
            result.DebugLog.Add($"Navigating to activity feed: {postsUrl}");
            await page.GotoAsync(postsUrl, new PageGotoOptions { WaitUntil = WaitUntilState.Load, Timeout = 30000 });
            await page.WaitForTimeoutAsync(3000);

            // Scroll to load more posts
            for (int i = 0; i < 5; i++)
            {
                await page.EvaluateAsync("window.scrollTo(0, document.body.scrollHeight)");
                await page.WaitForTimeoutAsync(2000);
            }
            result.DebugLog.Add("Scrolled 5 times on activity feed");

            // Capture the feed page
            var (feedScreenshot, feedText, _) = await CapturePageAsync(page);

            // Step 2: Phase A — Try to extract post URLs and navigate to each
            var postUrls = ExtractPostUrlsFromText(feedText);
            result.DebugLog.Add($"Found {postUrls.Count} post URLs in feed text");

            bool individualPostsFailed = false;

            if (postUrls.Count > 0)
            {
                var maxPosts = Math.Min(postUrls.Count, 10);
                for (int i = 0; i < maxPosts; i++)
                {
                    try
                    {
                        var postUrl = postUrls[i];
                        result.DebugLog.Add($"Navigating to post {i + 1}/{maxPosts}: {postUrl}");

                        await page.GotoAsync(postUrl, new PageGotoOptions { WaitUntil = WaitUntilState.Load, Timeout = 30000 });
                        await page.WaitForTimeoutAsync(2500);

                        // Check if LinkedIn blocked us (login wall)
                        var currentUrl = page.Url;
                        if (currentUrl.Contains("/login") || currentUrl.Contains("/authwall") || currentUrl.Contains("/checkpoint"))
                        {
                            result.Warnings.Add($"LinkedIn requires login for individual posts. Falling back to feed screenshot.");
                            result.DebugLog.Add($"Login wall detected at: {currentUrl}");
                            individualPostsFailed = true;
                            break;
                        }

                        // Try to expand truncated post content
                        try
                        {
                            var seeMore = page.Locator("button:has-text('see more'), button:has-text('...more')").First;
                            if (await seeMore.CountAsync() > 0)
                            {
                                await seeMore.ClickAsync(new LocatorClickOptions { Timeout = 2000 });
                                await page.WaitForTimeoutAsync(500);
                            }
                        }
                        catch { /* ignore click failures */ }

                        var (postScreenshot, postText, _) = await CapturePageAsync(page);
                        var post = await ExtractSinglePostWithClaudeAsync(apiKey, model, postScreenshot, postText);
                        post.PostUrl = postUrl;
                        result.Posts.Add(post);
                        result.DebugLog.Add($"Post {i + 1} extracted: {post.Content.Length} chars, {post.Likes} likes, {post.Comments} comments");

                        // Random delay between posts
                        var delay = 1500 + Random.Shared.Next(500, 1500);
                        await page.WaitForTimeoutAsync(delay);
                    }
                    catch (Exception ex)
                    {
                        result.Warnings.Add($"Failed to scrape post {i + 1}: {ex.Message}");
                        result.DebugLog.Add($"Post {i + 1} ERROR: {ex.Message}");

                        // If it's a navigation error, assume LinkedIn is blocking — fall back
                        if (ex.Message.Contains("ERR_TOO_MANY_REDIRECTS") || ex.Message.Contains("net::"))
                        {
                            individualPostsFailed = true;
                            break;
                        }
                    }
                }
            }
            else
            {
                individualPostsFailed = true;
                result.DebugLog.Add("No post URLs found, will use feed screenshot");
            }

            // Step 3: Phase B — Fallback to feed screenshot extraction
            if (individualPostsFailed || result.Posts.Count == 0)
            {
                result.DebugLog.Add("Using feed screenshot fallback...");

                // If we left the feed page (navigated to posts), go back and re-scroll
                if (individualPostsFailed && postUrls.Count > 0)
                {
                    result.DebugLog.Add("Re-navigating to activity feed for fallback...");
                    await page.GotoAsync(postsUrl, new PageGotoOptions { WaitUntil = WaitUntilState.Load, Timeout = 30000 });
                    await page.WaitForTimeoutAsync(3000);

                    for (int i = 0; i < 10; i++)
                    {
                        await page.EvaluateAsync("window.scrollTo(0, document.body.scrollHeight)");
                        await page.WaitForTimeoutAsync(1500);
                    }
                    result.DebugLog.Add("Re-scrolled 10 times");

                    (feedScreenshot, feedText, _) = await CapturePageAsync(page);
                }

                var feedPosts = await ExtractPostsFromFeedAsync(apiKey, model, feedScreenshot, feedText);
                result.DebugLog.Add($"Feed screenshot extracted {feedPosts.Count} posts");

                // Merge: add feed posts that aren't duplicates of individually scraped ones
                foreach (var fp in feedPosts)
                {
                    var isDuplicate = result.Posts.Any(p =>
                        p.Content.Length > 20 && fp.Content.Length > 20 &&
                        p.Content[..Math.Min(50, p.Content.Length)] == fp.Content[..Math.Min(50, fp.Content.Length)]);
                    if (!isDuplicate)
                        result.Posts.Add(fp);
                }
            }

            result.Success = true;
            result.DebugLog.Add($"Total posts scraped: {result.Posts.Count}");
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "LinkedIn posts scrape failed for {Url}", linkedInUrl);
            result.Error = $"Posts scrape failed: {ex.Message}";
            result.DebugLog.Add($"ERROR: {ex.Message}");
            if (result.Posts.Count > 0)
                result.Success = true; // partial results
        }

        return result;
    }

    // ========== Contact Info Overlay ==========

    private async Task TryExtractContactInfoOverlay(
        IPage page, string linkedInUrl, string apiKey, string model, LinkedInProfileData profile, ScrapeResult result)
    {
        try
        {
            // Build overlay URL: /in/username/overlay/contact-info/
            var contactInfoUrl = linkedInUrl.TrimEnd('/') + "/overlay/contact-info/";
            result.DebugLog.Add($"Trying contact info overlay: {contactInfoUrl}");

            await page.GotoAsync(contactInfoUrl, new PageGotoOptions { WaitUntil = WaitUntilState.Load, Timeout = 15000 });
            await page.WaitForTimeoutAsync(2000);

            // Check if LinkedIn redirected to login
            var currentUrl = page.Url;
            if (currentUrl.Contains("/login") || currentUrl.Contains("/authwall") || currentUrl.Contains("/checkpoint"))
            {
                result.Warnings.Add("Contact info requires LinkedIn login — skipped.");
                result.DebugLog.Add($"Contact info overlay redirected to login: {currentUrl}");
                return;
            }

            var (screenshot, pageText, _) = await CapturePageAsync(page);
            result.DebugLog.Add($"Contact info page loaded ({screenshot.Length / 1024}KB)");

            var contactJson = await ExtractContactInfoWithClaudeAsync(apiKey, model, screenshot, pageText);
            result.DebugLog.Add($"Contact info extracted: {contactJson}");

            // Merge into profile — overlay contact info overrides page-level contact info
            if (!string.IsNullOrEmpty(contactJson) && contactJson != "{}" && contactJson != "null")
            {
                // Merge: combine page-level contactInfo with overlay contactInfo
                if (!string.IsNullOrEmpty(profile.ContactInfo))
                {
                    try
                    {
                        var existing = JsonDocument.Parse(profile.ContactInfo);
                        var overlay = JsonDocument.Parse(contactJson);
                        var merged = MergeContactInfo(existing.RootElement, overlay.RootElement);
                        profile.ContactInfo = merged;
                    }
                    catch
                    {
                        profile.ContactInfo = contactJson;
                    }
                }
                else
                {
                    profile.ContactInfo = contactJson;
                }
            }
        }
        catch (PlaywrightException ex) when (ex.Message.Contains("ERR_TOO_MANY_REDIRECTS"))
        {
            result.Warnings.Add("Contact info overlay caused redirect loop — skipped.");
            result.DebugLog.Add($"Contact info ERR_TOO_MANY_REDIRECTS");
        }
        catch (Exception ex)
        {
            result.Warnings.Add($"Contact info extraction failed: {ex.Message}");
            result.DebugLog.Add($"Contact info ERROR: {ex.Message}");
        }
    }

    private static string MergeContactInfo(JsonElement existing, JsonElement overlay)
    {
        var merged = new Dictionary<string, string?>();

        // Collect existing fields
        if (existing.ValueKind == JsonValueKind.Object)
        {
            foreach (var prop in existing.EnumerateObject())
            {
                var val = prop.Value.ValueKind == JsonValueKind.String ? prop.Value.GetString() : null;
                if (!string.IsNullOrEmpty(val))
                    merged[prop.Name] = val;
            }
        }

        // Overlay fields override (non-null only)
        if (overlay.ValueKind == JsonValueKind.Object)
        {
            foreach (var prop in overlay.EnumerateObject())
            {
                var val = prop.Value.ValueKind == JsonValueKind.String ? prop.Value.GetString() : null;
                if (!string.IsNullOrEmpty(val))
                    merged[prop.Name] = val;
            }
        }

        return JsonSerializer.Serialize(merged);
    }

    // ========== Page Capture ==========

    private static async Task<(string screenshotBase64, string pageText, string pageTitle)> CapturePageAsync(IPage page)
    {
        var screenshot = await page.ScreenshotAsync(new PageScreenshotOptions { FullPage = true });
        var screenshotBase64 = Convert.ToBase64String(screenshot);
        var pageText = await page.InnerTextAsync("body");
        var pageTitle = await page.TitleAsync();
        return (screenshotBase64, pageText, pageTitle);
    }

    // ========== Post URL Extraction ==========

    private static List<string> ExtractPostUrlsFromText(string pageText)
    {
        var urls = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        // Match LinkedIn post URLs in text
        // Patterns: /feed/update/urn:li:activity:XXXX  or /posts/username_XXXX
        var patterns = new[]
        {
            @"https?://(?:www\.)?linkedin\.com/feed/update/urn:li:(?:activity|ugcPost):\d+",
            @"https?://(?:www\.)?linkedin\.com/posts/[a-zA-Z0-9_-]+_[a-zA-Z0-9_-]+"
        };

        foreach (var pattern in patterns)
        {
            foreach (Match m in Regex.Matches(pageText, pattern))
            {
                var url = m.Value.Split('?')[0]; // strip query params
                urls.Add(url);
            }
        }

        return urls.Take(10).ToList();
    }

    // ========== Claude Extraction Methods ==========

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

    private async Task<string> ExtractContactInfoWithClaudeAsync(
        string apiKey, string model, string screenshotBase64, string pageText)
    {
        var truncatedText = pageText.Length > 3000 ? pageText[..3000] : pageText;

        var prompt = @"Extract contact information from this LinkedIn contact info page/overlay. Return ONLY valid JSON, no other text:
{
  ""email"": ""email address or null"",
  ""phone"": ""phone number or null"",
  ""website"": ""website URL or null"",
  ""twitter"": ""twitter/X handle or null"",
  ""birthday"": ""birthday or null"",
  ""address"": ""address or null"",
  ""location"": ""location or null""
}
If a field is not visible, use null.

Page text:
" + truncatedText;

        return await CallClaudeVisionAsync(apiKey, model, screenshotBase64, prompt, 512);
    }

    private async Task<LinkedInPostData> ExtractSinglePostWithClaudeAsync(
        string apiKey, string model, string screenshotBase64, string pageText)
    {
        var truncatedText = pageText.Length > 6000 ? pageText[..6000] : pageText;

        var prompt = @"Extract this LinkedIn post's details. Return ONLY valid JSON, no other text:
{
  ""content"": ""full post text content"",
  ""postDate"": ""date string if visible, or null"",
  ""likes"": 0,
  ""comments"": 0,
  ""commentTexts"": [""first comment text"", ""second comment text""]
}

'likes' = total reaction count. 'comments' = total comment count.
'commentTexts' = array of visible comment texts (up to 5). Empty array if none visible.

Page text:
" + truncatedText;

        var responseText = await CallClaudeVisionAsync(apiKey, model, screenshotBase64, prompt, 2048);

        using var parsed = JsonDocument.Parse(responseText);
        var root = parsed.RootElement;

        var post = new LinkedInPostData
        {
            Content = GetString(root, "content") ?? "",
            Likes = root.TryGetProperty("likes", out var l) && l.ValueKind == JsonValueKind.Number ? l.GetInt32() : 0,
            Comments = root.TryGetProperty("comments", out var c) && c.ValueKind == JsonValueKind.Number ? c.GetInt32() : 0
        };

        if (root.TryGetProperty("postDate", out var d) && d.ValueKind == JsonValueKind.String)
        {
            if (DateTime.TryParse(d.GetString(), out var dt))
                post.PostDate = dt;
        }

        // Extract comment texts
        if (root.TryGetProperty("commentTexts", out var ct) && ct.ValueKind == JsonValueKind.Array)
        {
            var commentTexts = new List<string>();
            foreach (var item in ct.EnumerateArray())
            {
                if (item.ValueKind == JsonValueKind.String)
                    commentTexts.Add(item.GetString() ?? "");
            }
            if (commentTexts.Count > 0)
                post.CommentsJson = JsonSerializer.Serialize(commentTexts);
        }

        return post;
    }

    private async Task<List<LinkedInPostData>> ExtractPostsFromFeedAsync(
        string apiKey, string model, string screenshotBase64, string pageText)
    {
        var truncatedText = pageText.Length > 8000 ? pageText[..8000] : pageText;

        var prompt = @"Extract LinkedIn posts from this activity page. Return ONLY a valid JSON array, no other text.
Each post should be:
{
  ""content"": ""the full post text content"",
  ""postDate"": ""date string if visible, or null"",
  ""likes"": number of likes/reactions (0 if not visible),
  ""comments"": number of comments (0 if not visible)
}

Extract ALL visible posts. Include the complete text for each post. Return up to 15 most recent posts. If no posts found, return [].

Page text:
" + truncatedText;

        var responseText = await CallClaudeVisionAsync(apiKey, model, screenshotBase64, prompt, 4096);

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

    // ========== Claude Vision API ==========

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

    // ========== Config ==========

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
