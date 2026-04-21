using System.Text;
using System.Text.Json;
using LeadPulse.Application.Interfaces;
using LeadPulse.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Microsoft.Playwright;

namespace LeadPulse.Infrastructure.Services;

public class EnhancedScrapeResult
{
    public bool Success { get; set; }
    public string? Error { get; set; }
    public List<string> Warnings { get; set; } = new();
    public LinkedInProfileData? Profile { get; set; }
    public string? ContactInfoJson { get; set; }
    public List<EnhancedPostData> Posts { get; set; } = new();
    public List<string> DebugLog { get; set; } = new();
}

public class EnhancedPostData
{
    public string Content { get; set; } = string.Empty;
    public string? PostUrl { get; set; }
    public DateTime? PostDate { get; set; }
    public int Likes { get; set; }
    public int Comments { get; set; }
    public List<string> CommentTexts { get; set; } = new();
}

public class EnhancedLinkedInScraperService
{
    private readonly TenantDbContext _tenantDb;
    private readonly IEncryptionService _encryptionService;
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly ILogger<EnhancedLinkedInScraperService> _logger;

    public EnhancedLinkedInScraperService(
        TenantDbContext tenantDb,
        IEncryptionService encryptionService,
        IHttpClientFactory httpClientFactory,
        ILogger<EnhancedLinkedInScraperService> logger)
    {
        _tenantDb = tenantDb;
        _encryptionService = encryptionService;
        _httpClientFactory = httpClientFactory;
        _logger = logger;
    }

    /// <summary>
    /// Enhanced profile scrape: main page + contact info modal click
    /// </summary>
    public async Task<EnhancedScrapeResult> ScrapeProfileAsync(int tenantId, string linkedInUrl)
    {
        var (apiKey, model) = await GetClaudeApiKeyAsync(tenantId);
        if (apiKey == null)
            return new EnhancedScrapeResult { Success = false, Error = "Claude API key not configured." };

        var cookie = await GetLinkedInCookieAsync(tenantId);
        var result = new EnhancedScrapeResult();

        IPlaywright? playwright = null;
        IBrowser? browser = null;
        try
        {
            (playwright, browser) = await LaunchBrowserAsync();
            var context = await CreateContextAsync(browser, cookie);
            var page = await context.NewPageAsync();
            await InjectAntiDetection(page);

            // Step 1: Warm up session then navigate to profile page
            var navResult = await NavigateWithWarmup(page, linkedInUrl, cookie, result);
            if (!navResult)
                return result;

            // Step 2: Screenshot main profile
            var screenshot = await page.ScreenshotAsync(new PageScreenshotOptions { FullPage = true });
            var screenshotBase64 = Convert.ToBase64String(screenshot);
            var pageText = await page.InnerTextAsync("body");
            var pageTitle = await page.TitleAsync();
            result.DebugLog.Add($"Profile screenshot taken ({screenshot.Length} bytes)");

            var isCompany = linkedInUrl.Contains("/company/");
            var profile = await ExtractProfileWithClaudeAsync(apiKey, model, screenshotBase64, pageText, pageTitle, isCompany);
            result.Profile = profile;
            result.DebugLog.Add($"Profile extracted: {profile.Name} ({profile.Type})");

            // Step 3: Try to click Contact Info
            if (!isCompany)
            {
                await TryExtractContactInfo(page, apiKey, model, result);
            }

            result.Success = true;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Enhanced profile scrape failed for {Url}", linkedInUrl);
            result.Error = $"Scrape failed: {ex.Message}";
            result.DebugLog.Add($"ERROR: {ex.Message}");
        }
        finally
        {
            if (browser != null) await browser.CloseAsync();
            playwright?.Dispose();
        }

        return result;
    }

    /// <summary>
    /// Enhanced post scrape: collect post URLs from feed, navigate to each individually
    /// </summary>
    public async Task<EnhancedScrapeResult> ScrapePostsAsync(int tenantId, string linkedInUrl)
    {
        var (apiKey, model) = await GetClaudeApiKeyAsync(tenantId);
        if (apiKey == null)
            return new EnhancedScrapeResult { Success = false, Error = "Claude API key not configured." };

        var cookie = await GetLinkedInCookieAsync(tenantId);
        var result = new EnhancedScrapeResult();

        IPlaywright? playwright = null;
        IBrowser? browser = null;
        try
        {
            (playwright, browser) = await LaunchBrowserAsync();
            var context = await CreateContextAsync(browser, cookie);
            var page = await context.NewPageAsync();
            await InjectAntiDetection(page);

            // Navigate to activity feed
            var postsUrl = linkedInUrl.TrimEnd('/');
            if (!postsUrl.Contains("/recent-activity"))
                postsUrl += "/recent-activity/all/";

            var navResult = await NavigateWithWarmup(page, postsUrl, cookie, result);
            if (!navResult)
                return result;

            // Scroll to load posts (5 scrolls for more content)
            for (int i = 0; i < 5; i++)
            {
                await page.EvaluateAsync("window.scrollTo(0, document.body.scrollHeight)");
                await page.WaitForTimeoutAsync(3000);
                result.DebugLog.Add($"Scroll {i + 1}/5 complete");
            }

            // Phase A: Extract post URLs from DOM
            var postUrls = await page.EvaluateAsync<string[]>(@"
                () => {
                    const links = document.querySelectorAll('a[href*=""/feed/update/""], a[href*=""/posts/""]');
                    const uniqueUrls = [...new Set(
                        Array.from(links)
                            .map(a => a.href)
                            .filter(href => href.includes('/feed/update/') || href.includes('/posts/'))
                            .map(href => href.split('?')[0])
                    )];
                    return uniqueUrls.slice(0, 10);
                }
            ");

            result.DebugLog.Add($"Found {postUrls.Length} post URLs from feed");

            if (postUrls.Length == 0)
            {
                // Fallback: take screenshot of feed and use Claude to extract (like current approach)
                result.DebugLog.Add("No post URLs found via DOM, falling back to screenshot extraction");
                var screenshot = await page.ScreenshotAsync(new PageScreenshotOptions { FullPage = true });
                var pageText = await page.InnerTextAsync("body");
                var fallbackPosts = await ExtractPostsFromFeedScreenshot(apiKey, model, Convert.ToBase64String(screenshot), pageText);
                foreach (var fp in fallbackPosts)
                    result.Posts.Add(fp);
                result.Success = true;
                return result;
            }

            // Phase B: Navigate to each post individually
            for (int i = 0; i < postUrls.Length; i++)
            {
                try
                {
                    var postUrl = postUrls[i];
                    result.DebugLog.Add($"Scraping post {i + 1}/{postUrls.Length}: {postUrl}");

                    await page.GotoAsync(postUrl, new PageGotoOptions { WaitUntil = WaitUntilState.NetworkIdle, Timeout = 30000 });
                    await page.WaitForTimeoutAsync(1500);

                    // Check for rate limiting
                    if (IsRateLimited(page.Url, await page.TitleAsync()))
                    {
                        result.Warnings.Add($"LinkedIn rate limit detected after {i} posts. Returning partial results.");
                        result.DebugLog.Add("Rate limit detected, stopping");
                        break;
                    }

                    // Click "see more" if truncated
                    try
                    {
                        var seeMore = page.Locator("button:has-text('see more'), button:has-text('...more')").First;
                        if (await seeMore.CountAsync() > 0)
                        {
                            await seeMore.ClickAsync(new LocatorClickOptions { Timeout = 2000 });
                            await page.WaitForTimeoutAsync(500);
                            result.DebugLog.Add("Clicked 'see more' on post");
                        }
                    }
                    catch { /* ignore */ }

                    var screenshot = await page.ScreenshotAsync(new PageScreenshotOptions { FullPage = true });
                    var screenshotBase64 = Convert.ToBase64String(screenshot);
                    var pageText = await page.InnerTextAsync("body");

                    var post = await ExtractSinglePostWithClaudeAsync(apiKey, model, screenshotBase64, pageText);
                    post.PostUrl = postUrl;
                    result.Posts.Add(post);
                    result.DebugLog.Add($"Post {i + 1} extracted: {post.Content.Length} chars, {post.Likes} likes, {post.Comments} comments, {post.CommentTexts.Count} comment texts");

                    // Random delay between posts
                    var delay = 1500 + Random.Shared.Next(500, 1500);
                    await page.WaitForTimeoutAsync(delay);
                }
                catch (Exception ex)
                {
                    result.Warnings.Add($"Failed to scrape post {i + 1}: {ex.Message}");
                    result.DebugLog.Add($"Post {i + 1} ERROR: {ex.Message}");
                }
            }

            result.Success = true;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Enhanced posts scrape failed for {Url}", linkedInUrl);
            result.Error = $"Posts scrape failed: {ex.Message}";
            result.DebugLog.Add($"ERROR: {ex.Message}");
        }
        finally
        {
            if (browser != null) await browser.CloseAsync();
            playwright?.Dispose();
        }

        return result;
    }

    // ========== Contact Info Modal ==========

    private async Task TryExtractContactInfo(IPage page, string apiKey, string model, EnhancedScrapeResult result)
    {
        try
        {
            result.DebugLog.Add("Looking for Contact Info link...");

            // Try multiple selectors for the contact info link
            ILocator? contactLink = null;
            string? selectorUsed = null;

            var selectors = new[]
            {
                ("a[href*='/overlay/contact-info/']", "href pattern"),
                ("#top-card-text-details-contact-info", "element ID"),
            };

            foreach (var (selector, name) in selectors)
            {
                var loc = page.Locator(selector).First;
                if (await loc.CountAsync() > 0)
                {
                    contactLink = loc;
                    selectorUsed = name;
                    break;
                }
            }

            // Text-based fallback
            if (contactLink == null)
            {
                var textLoc = page.GetByText("Contact info", new PageGetByTextOptions { Exact = false }).First;
                if (await textLoc.CountAsync() > 0)
                {
                    contactLink = textLoc;
                    selectorUsed = "text match";
                }
            }

            if (contactLink == null)
            {
                result.Warnings.Add("Contact Info link not found on profile. May require login or the profile layout is different.");
                result.DebugLog.Add("Contact Info link NOT found with any selector");
                return;
            }

            result.DebugLog.Add($"Found Contact Info link via: {selectorUsed}");
            await contactLink.ClickAsync(new LocatorClickOptions { Timeout = 3000 });
            result.DebugLog.Add("Clicked Contact Info link");

            // Wait for modal
            try
            {
                await page.WaitForSelectorAsync(
                    "div.artdeco-modal, div[role='dialog'], section.pv-contact-info",
                    new PageWaitForSelectorOptions { Timeout = 5000 });
                await page.WaitForTimeoutAsync(1000);
                result.DebugLog.Add("Contact Info modal appeared");
            }
            catch
            {
                result.Warnings.Add("Contact Info modal did not appear after clicking.");
                result.DebugLog.Add("Modal wait timed out");
                return;
            }

            // Try to screenshot just the modal
            byte[] modalScreenshot;
            var modalLocator = page.Locator("div.artdeco-modal, div[role='dialog']").First;
            if (await modalLocator.CountAsync() > 0)
            {
                modalScreenshot = await modalLocator.ScreenshotAsync();
                result.DebugLog.Add("Captured modal-only screenshot");
            }
            else
            {
                modalScreenshot = await page.ScreenshotAsync(new PageScreenshotOptions { FullPage = true });
                result.DebugLog.Add("Captured full-page screenshot (modal locator not found)");
            }

            var modalBase64 = Convert.ToBase64String(modalScreenshot);
            var modalText = await page.InnerTextAsync("body");

            // Extract contact info with Claude
            var contactPrompt = @"Extract contact information from this LinkedIn contact info modal/overlay. Return ONLY valid JSON, no other text:
{
  ""email"": ""email address or null"",
  ""phone"": ""phone number or null"",
  ""website"": ""website URL or null"",
  ""twitter"": ""twitter/X handle or null"",
  ""birthday"": ""birthday or null"",
  ""connected"": ""connection date or null"",
  ""address"": ""address or null"",
  ""location"": ""location or null""
}
If a field is not visible, use null.

Page text:
" + (modalText.Length > 3000 ? modalText[..3000] : modalText);

            var contactJson = await CallClaudeVisionAsync(apiKey, model, modalBase64, contactPrompt, 512);
            result.ContactInfoJson = contactJson;
            result.DebugLog.Add($"Contact info extracted: {contactJson}");

            // Close modal
            try
            {
                var closeBtn = page.Locator("button[aria-label='Dismiss'], button.artdeco-modal__dismiss").First;
                if (await closeBtn.CountAsync() > 0)
                    await closeBtn.ClickAsync(new LocatorClickOptions { Timeout = 2000 });
            }
            catch { /* ignore */ }
        }
        catch (Exception ex)
        {
            result.Warnings.Add($"Contact info extraction failed: {ex.Message}");
            result.DebugLog.Add($"Contact info ERROR: {ex.Message}");
        }
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

    private async Task<EnhancedPostData> ExtractSinglePostWithClaudeAsync(
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

        var post = new EnhancedPostData
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

        if (root.TryGetProperty("commentTexts", out var ct) && ct.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in ct.EnumerateArray())
            {
                if (item.ValueKind == JsonValueKind.String)
                    post.CommentTexts.Add(item.GetString() ?? "");
            }
        }

        return post;
    }

    private async Task<List<EnhancedPostData>> ExtractPostsFromFeedScreenshot(
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
        var posts = new List<EnhancedPostData>();

        using var parsed = JsonDocument.Parse(responseText);
        if (parsed.RootElement.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in parsed.RootElement.EnumerateArray())
            {
                var post = new EnhancedPostData
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

    // ========== Browser Helpers ==========

    private async Task<(IPlaywright playwright, IBrowser browser)> LaunchBrowserAsync()
    {
        var playwright = await Playwright.CreateAsync();
        var browser = await playwright.Chromium.LaunchAsync(new BrowserTypeLaunchOptions
        {
            Headless = true,
            Args = new[]
            {
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox"
            }
        });
        return (playwright, browser);
    }

    private async Task<IBrowserContext> CreateContextAsync(IBrowser browser, string? linkedInCookie)
    {
        var context = await browser.NewContextAsync(new BrowserNewContextOptions
        {
            UserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            ViewportSize = new ViewportSize
            {
                Width = 1280 + Random.Shared.Next(-20, 20),
                Height = 900 + Random.Shared.Next(-20, 20)
            },
            Locale = "en-US",
            TimezoneId = "America/New_York"
        });

        if (!string.IsNullOrEmpty(linkedInCookie))
        {
            await context.AddCookiesAsync(new[]
            {
                new Cookie
                {
                    Name = "li_at",
                    Value = linkedInCookie,
                    Domain = ".linkedin.com",
                    Path = "/",
                    HttpOnly = true,
                    Secure = true
                },
                // JSESSIONID is required to prevent redirect loops
                new Cookie
                {
                    Name = "JSESSIONID",
                    Value = $"\"ajax:{Guid.NewGuid():N}\"",
                    Domain = ".www.linkedin.com",
                    Path = "/",
                    HttpOnly = false,
                    Secure = true
                }
            });
        }

        return context;
    }

    /// <summary>
    /// Navigate to a LinkedIn URL with warmup to avoid redirect loops.
    /// First visits linkedin.com to establish session, then navigates to target.
    /// </summary>
    private async Task<bool> NavigateWithWarmup(IPage page, string targetUrl, string? cookie, EnhancedScrapeResult result)
    {
        // Step 1: Warm up by visiting linkedin.com homepage first
        if (!string.IsNullOrEmpty(cookie))
        {
            result.DebugLog.Add("Warming up LinkedIn session...");
            try
            {
                await page.GotoAsync("https://www.linkedin.com/feed/", new PageGotoOptions { WaitUntil = WaitUntilState.Load, Timeout = 15000 });
                await page.WaitForTimeoutAsync(2000);
                result.DebugLog.Add($"Warmup done, current URL: {page.Url}");
            }
            catch (Exception ex)
            {
                result.DebugLog.Add($"Warmup navigation: {ex.Message} (continuing anyway)");
            }
        }

        // Step 2: Navigate to target URL
        result.DebugLog.Add($"Navigating to: {targetUrl}");
        try
        {
            await page.GotoAsync(targetUrl, new PageGotoOptions { WaitUntil = WaitUntilState.Load, Timeout = 30000 });
        }
        catch (PlaywrightException ex) when (ex.Message.Contains("ERR_TOO_MANY_REDIRECTS"))
        {
            result.Success = false;
            result.Error = "LinkedIn redirect loop detected. This usually means the session cookie is invalid or expired. Please update your li_at cookie.";
            result.DebugLog.Add($"ERR_TOO_MANY_REDIRECTS: {ex.Message}");
            return false;
        }

        await page.WaitForTimeoutAsync(3000);

        // Step 3: Check if we landed on login page
        if (IsLoginPage(page.Url))
        {
            result.Success = false;
            result.Error = "LinkedIn requires login. Please save your LinkedIn cookie in the Scraper Test page.";
            if (string.IsNullOrEmpty(cookie))
                result.Error += " No cookie is currently saved.";
            else
                result.Error += " Your saved cookie may have expired — get a fresh li_at from your browser.";
            result.DebugLog.Add($"Redirected to login: {page.Url}");
            return false;
        }

        result.DebugLog.Add($"Page loaded: {page.Url}");
        return true;
    }

    private static async Task InjectAntiDetection(IPage page)
    {
        await page.AddInitScriptAsync(@"
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        ");
    }

    private static bool IsLoginPage(string url)
    {
        return url.Contains("/login") || url.Contains("/authwall") || url.Contains("/checkpoint/challengesV2/");
    }

    private static bool IsRateLimited(string url, string title)
    {
        return url.Contains("/checkpoint/") || title.Contains("Security Verification");
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

        textContent = textContent.Trim();
        if (textContent.StartsWith("```json")) textContent = textContent[7..];
        if (textContent.StartsWith("```")) textContent = textContent[3..];
        if (textContent.EndsWith("```")) textContent = textContent[..^3];
        return textContent.Trim();
    }

    // ========== Config Helpers ==========

    private async Task<(string? apiKey, string model)> GetClaudeApiKeyAsync(int tenantId)
    {
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

    private async Task<string?> GetLinkedInCookieAsync(int tenantId)
    {
        var settings = await _tenantDb.LinkedInScraperSettings.FirstOrDefaultAsync();
        if (settings?.EncryptedLinkedInCookie == null) return null;

        // Check expiry
        if (settings.LinkedInCookieExpiresAt.HasValue && settings.LinkedInCookieExpiresAt.Value < DateTime.UtcNow)
            return null;

        try
        {
            return _encryptionService.Decrypt(settings.EncryptedLinkedInCookie, tenantId);
        }
        catch { return null; }
    }

    private static string? GetString(JsonElement element, string property)
    {
        if (element.TryGetProperty(property, out var prop) && prop.ValueKind == JsonValueKind.String)
            return prop.GetString();
        return null;
    }
}
