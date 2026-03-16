using System.Text.Json;
using LeadPulse.Application.Interfaces;
using Microsoft.Extensions.Logging;
using Microsoft.Playwright;

namespace LeadPulse.Infrastructure.PlatformAdapters;

public class NextdoorAdapter : BasePlatformAdapter
{
    private readonly ILogger<NextdoorAdapter> _logger;

    public NextdoorAdapter(ILogger<NextdoorAdapter> logger) : base(logger)
    {
        _logger = logger;
    }

    public override string Platform => "Nextdoor";

    public override async Task<LoginResult> TestLoginAsync(string username, string password, string? mfaSecret)
    {
        IPlaywright? playwright = null;
        IBrowser? browser = null;

        try
        {
            playwright = await Playwright.CreateAsync();
            browser = await playwright.Chromium.LaunchAsync(new BrowserTypeLaunchOptions
            {
                Headless = true,
                Args = new[] { "--no-sandbox", "--disable-dev-shm-usage" }
            });

            var context = await browser.NewContextAsync(new BrowserNewContextOptions
            {
                UserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            });

            var page = await context.NewPageAsync();
            _logger.LogInformation("Testing Nextdoor login for {Username}", username);

            await page.GotoAsync("https://nextdoor.com/login/", new PageGotoOptions
            {
                WaitUntil = WaitUntilState.NetworkIdle,
                Timeout = 30000
            });

            // Fill login form
            await FillLoginForm(page, username, password);

            // Check if login succeeded
            try
            {
                await page.WaitForURLAsync(url => !url.Contains("/login"), new PageWaitForURLOptions { Timeout = 15000 });
                _logger.LogInformation("Nextdoor login successful for {Username}", username);
                return new LoginResult { Success = true };
            }
            catch (TimeoutException)
            {
                var errorText = await GetPageErrorText(page);
                _logger.LogWarning("Nextdoor login failed for {Username}: {Error}", username, errorText);
                return new LoginResult { Success = false, ErrorMessage = errorText };
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Nextdoor login test failed for {Username}", username);
            return new LoginResult { Success = false, ErrorMessage = ex.Message };
        }
        finally
        {
            if (browser != null) await browser.CloseAsync();
            playwright?.Dispose();
        }
    }

    public override async Task<ScrapeResult> ScrapePostsAsync(
        string username, string password, string? mfaSecret, int maxPosts, string scrapeDepth, List<string>? targetUrls = null)
    {
        IPlaywright? playwright = null;
        IBrowser? browser = null;

        try
        {
            playwright = await Playwright.CreateAsync();
            browser = await playwright.Chromium.LaunchAsync(new BrowserTypeLaunchOptions
            {
                Headless = true,
                Args = new[] { "--no-sandbox", "--disable-dev-shm-usage" }
            });

            var context = await browser.NewContextAsync(new BrowserNewContextOptions
            {
                UserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                ViewportSize = new ViewportSize { Width = 1920, Height = 1080 },
                Locale = "en-US",
                TimezoneId = "America/New_York"
            });

            var page = await context.NewPageAsync();

            // Make headless browser less detectable
            await page.AddInitScriptAsync(@"
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            ");

            _logger.LogInformation("Starting Nextdoor scrape for {Username}, max {MaxPosts} posts", username, maxPosts);

            // Step 1: Login
            await page.GotoAsync("https://nextdoor.com/login/", new PageGotoOptions
            {
                WaitUntil = WaitUntilState.NetworkIdle,
                Timeout = 30000
            });

            await FillLoginForm(page, username, password);

            try
            {
                await page.WaitForURLAsync(url => !url.Contains("/login"), new PageWaitForURLOptions { Timeout = 15000 });
            }
            catch (TimeoutException)
            {
                return new ScrapeResult { Success = false, ErrorMessage = "Login failed — could not authenticate" };
            }

            _logger.LogInformation("Nextdoor login successful, current URL: {Url}", page.Url);

            // Save debug screenshot after login
            try
            {
                var debugDir = Path.Combine(AppContext.BaseDirectory, "debug");
                Directory.CreateDirectory(debugDir);
                var screenshotPath = Path.Combine(debugDir, $"nextdoor_afterlogin_{DateTime.UtcNow:yyyyMMdd_HHmmss}.png");
                await page.ScreenshotAsync(new PageScreenshotOptions { Path = screenshotPath, FullPage = true });
                _logger.LogInformation("Debug screenshot saved to {Path}", screenshotPath);
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Failed to save debug screenshot");
            }

            var posts = new List<ScrapedPost>();
            var seenContent = new HashSet<string>();

            // Build the list of URLs to scrape
            var urlsToScrape = new List<(string Url, string Label)>();

            if (targetUrls != null && targetUrls.Count > 0)
            {
                // Use user-configured target URLs
                foreach (var url in targetUrls)
                {
                    urlsToScrape.Add((url, url));
                }
                _logger.LogInformation("Using {Count} user-configured target URLs", targetUrls.Count);
            }
            else
            {
                // Fallback: default URLs
                urlsToScrape.Add(("https://nextdoor.com/news_feed/", "Main Feed"));
                urlsToScrape.Add(("https://nextdoor.com/search/posts/?query=insurance", "Search: insurance"));
                urlsToScrape.Add(("https://nextdoor.com/search/posts/?query=insurance+agent", "Search: insurance agent"));
                urlsToScrape.Add(("https://nextdoor.com/search/posts/?query=home+insurance", "Search: home insurance"));
                urlsToScrape.Add(("https://nextdoor.com/search/posts/?query=car+insurance", "Search: car insurance"));
                _logger.LogInformation("No target URLs configured, using defaults");
            }

            // Step 2: Scrape each target URL
            foreach (var (url, label) in urlsToScrape)
            {
                if (posts.Count >= maxPosts) break;

                try
                {
                    _logger.LogInformation("Navigating to: {Label} ({Url})", label, url);

                    await page.GotoAsync(url, new PageGotoOptions
                    {
                        WaitUntil = WaitUntilState.NetworkIdle,
                        Timeout = 30000
                    });
                    await Task.Delay(3000); // Wait for JS rendering

                    var pageTitle = await page.TitleAsync();
                    _logger.LogInformation("Page loaded — Title: {Title}, URL: {Url}", pageTitle, page.Url);

                    var remaining = maxPosts - posts.Count;
                    var pagePosts = await ScrapeCurrentPage(page, remaining, seenContent);
                    posts.AddRange(pagePosts);
                    _logger.LogInformation("Scraped {Count} posts from: {Label}", pagePosts.Count, label);

                    await Task.Delay(2000);
                }
                catch (Exception ex)
                {
                    _logger.LogWarning(ex, "Failed to scrape: {Label}", label);
                }
            }

            _logger.LogInformation("Nextdoor scrape complete: {Count} total posts", posts.Count);

            return new ScrapeResult { Success = true, Posts = posts };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Nextdoor scrape failed for {Username}", username);
            return new ScrapeResult { Success = false, ErrorMessage = ex.Message };
        }
        finally
        {
            if (browser != null) await browser.CloseAsync();
            playwright?.Dispose();
        }
    }

    private async Task FillLoginForm(IPage page, string username, string password)
    {
        // Wait for any input to appear
        await page.WaitForSelectorAsync("input", new PageWaitForSelectorOptions { Timeout = 10000 });
        await Task.Delay(1000);

        // Try multiple selector strategies for email
        var emailSelectors = new[]
        {
            "input[id='email']", "input[name='email']", "input[type='email']",
            "input[autocomplete='email']", "input[autocomplete='username']",
            "#id_email", "input[data-testid='email-input']"
        };

        foreach (var sel in emailSelectors)
        {
            var el = await page.QuerySelectorAsync(sel);
            if (el != null)
            {
                await el.FillAsync(username);
                _logger.LogInformation("Filled email using selector: {Selector}", sel);
                break;
            }
        }

        // Try multiple selector strategies for password
        var passwordSelectors = new[]
        {
            "input[id='password']", "input[name='password']", "input[type='password']",
            "#id_password", "input[data-testid='password-input']"
        };

        foreach (var sel in passwordSelectors)
        {
            var el = await page.QuerySelectorAsync(sel);
            if (el != null)
            {
                await el.FillAsync(password);
                _logger.LogInformation("Filled password using selector: {Selector}", sel);
                break;
            }
        }

        // Click submit
        var submitSelectors = new[]
        {
            "button[type='submit']", "button[data-testid='login-button']",
            "button[data-testid='submit-button']", "#signin_button",
            "button:has-text('Sign in')", "button:has-text('Log in')"
        };

        foreach (var sel in submitSelectors)
        {
            try
            {
                var el = await page.QuerySelectorAsync(sel);
                if (el != null)
                {
                    await el.ClickAsync();
                    _logger.LogInformation("Clicked submit using selector: {Selector}", sel);
                    break;
                }
            }
            catch { /* try next selector */ }
        }
    }

    private async Task<List<ScrapedPost>> ScrapeCurrentPage(IPage page, int maxPosts, HashSet<string> seenContent)
    {
        var posts = new List<ScrapedPost>();

        // Save debug snapshot of the page HTML on first scroll to help diagnose selector issues
        try
        {
            var debugDir = Path.Combine(AppContext.BaseDirectory, "debug");
            Directory.CreateDirectory(debugDir);
            var html = await page.ContentAsync();
            var debugFile = Path.Combine(debugDir, $"nextdoor_{DateTime.UtcNow:yyyyMMdd_HHmmss}.html");
            await File.WriteAllTextAsync(debugFile, html);
            _logger.LogInformation("Debug HTML snapshot saved to {File} ({Length} chars)", debugFile, html.Length);

            // Also log what selectors match
            var selectorDebug = await page.EvaluateAsync<string>(@"() => {
                const selectors = [
                    'article', '[role=""article""]', '[data-testid*=""post""]',
                    '[class*=""post""]', '[class*=""Post""]', '[class*=""story""]',
                    '[class*=""feed""]', '[class*=""Feed""]', '[class*=""card""]',
                    '[class*=""Card""]', '[class*=""content""]', '[class*=""Content""]',
                    'main', '[role=""main""]', '[id*=""feed""]', '[id*=""content""]',
                    '[class*=""Subheader""]', '[class*=""Body""]', '[class*=""body""]',
                    'a[href*=""/p/""]', 'a[href*=""/post/""]', 'a[href*=""/news_feed/""]'
                ];
                const results = [];
                for (const sel of selectors) {
                    try {
                        const count = document.querySelectorAll(sel).length;
                        if (count > 0) results.push(sel + ': ' + count);
                    } catch {}
                }
                return results.join(' | ') || 'NO SELECTORS MATCHED';
            }");
            _logger.LogInformation("Nextdoor selector debug: {Selectors}", selectorDebug);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to save debug snapshot");
        }

        for (var scroll = 0; scroll < 8 && posts.Count < maxPosts; scroll++)
        {
            // Return JSON string to avoid Playwright deserialization issues with null values
            var jsonStr = await page.EvaluateAsync<string>(@"() => {
                const results = [];
                const seen = new Set();

                function cleanPostContent(el) {
                    // Clone and remove comment/reply sections, nav, buttons, timestamps
                    const clone = el.cloneNode(true);
                    clone.querySelectorAll('[data-testid*=""comment""], [data-testid*=""reply""], [class*=""comment""], [class*=""Comment""], [class*=""reply""], [class*=""Reply""], [class*=""reaction""], [class*=""Reaction""], nav, header, footer, button, [role=""button""], [class*=""action""], [class*=""Action""], [class*=""toolbar""], [class*=""Toolbar""], form').forEach(n => n.remove());
                    // Get remaining text — this should be the original post body
                    const text = clone.innerText ? clone.innerText.trim() : '';
                    // Remove common UI artifacts
                    return text.replace(/^(Like|Comment|Share|Reply|Report|See more|See less|\d+ likes?|\d+ comments?|\d+ shares?)\s*/gim, '').trim();
                }

                function add(author, content, postUrl, dateStr) {
                    if (!content || content.length < 30) return;
                    const key = content.substring(0, 100);
                    if (seen.has(key)) return;
                    seen.add(key);
                    results.push({
                        author: author || 'Nextdoor Neighbor',
                        content: content,
                        postUrl: postUrl || '',
                        dateStr: dateStr || ''
                    });
                }

                function getAuthor(el) {
                    const a = el.querySelector('a[href*=""/profile/""], a[href*=""/neighbor/""], a[href*=""/member/""]');
                    return a ? a.textContent.trim() : 'Nextdoor Neighbor';
                }

                function getPostUrl(el) {
                    const a = el.querySelector('a[href*=""/p/""]');
                    return a ? a.href : '';
                }

                function getDate(el) {
                    const t = el.querySelector('time, [datetime], abbr[title]');
                    if (!t) return '';
                    return t.getAttribute('datetime') || t.getAttribute('title') || t.textContent.trim();
                }

                // Strategy 1: Nextdoor uses data-testid='dwell-tracker-searchFeedItem:...' for search results
                document.querySelectorAll('[data-testid^=""dwell-tracker""]').forEach(el => {
                    add(getAuthor(el), cleanPostContent(el), getPostUrl(el), getDate(el));
                });

                // Strategy 2: article elements
                document.querySelectorAll('article, [role=""article""]').forEach(el => {
                    add(getAuthor(el), cleanPostContent(el), getPostUrl(el), getDate(el));
                });

                // Strategy 3: Walk up from /p/ links to find post containers
                if (results.length === 0) {
                    document.querySelectorAll('a[href*=""/p/""]').forEach(link => {
                        let el = link.parentElement;
                        for (let i = 0; i < 6 && el; i++) {
                            const cleaned = cleanPostContent(el);
                            if (cleaned.length >= 40 && cleaned.length < 5000) {
                                add(getAuthor(el), cleaned, link.href, getDate(el));
                                break;
                            }
                            el = el.parentElement;
                        }
                    });
                }

                // Strategy 4: Broadest fallback — text blocks in body
                if (results.length === 0) {
                    const root = document.querySelector('[data-testid=""feed-container""], main, body');
                    if (root) {
                        root.querySelectorAll('div').forEach(div => {
                            const cleaned = cleanPostContent(div);
                            if (cleaned.length < 50 || cleaned.length > 3000) return;
                            if (div.querySelectorAll('div').length > 15) return;
                            if (div.closest('nav, header, footer')) return;
                            const lines = cleaned.split('\n').filter(l => l.trim());
                            if (lines.length < 2) return;
                            add('Nextdoor Neighbor', cleaned, getPostUrl(div), getDate(div));
                        });
                    }
                }

                return JSON.stringify(results);
            }");

            if (!string.IsNullOrEmpty(jsonStr))
            {
                var extracted = JsonSerializer.Deserialize<List<RawPost>>(jsonStr, new JsonSerializerOptions
                {
                    PropertyNameCaseInsensitive = true
                });

                if (extracted != null)
                {
                    _logger.LogInformation("Scroll {Scroll}: found {Count} raw elements on page", scroll, extracted.Count);

                    foreach (var raw in extracted)
                    {
                        if (posts.Count >= maxPosts) break;
                        if (string.IsNullOrWhiteSpace(raw.Content) || raw.Content.Length < 30) continue;

                        var contentKey = raw.Content.Length > 100 ? raw.Content[..100] : raw.Content;
                        if (!seenContent.Add(contentKey)) continue;

                        posts.Add(new ScrapedPost
                        {
                            AuthorName = raw.Author ?? "Nextdoor Neighbor",
                            AuthorProfileUrl = null,
                            Content = raw.Content,
                            PostUrl = !string.IsNullOrEmpty(raw.PostUrl) ? raw.PostUrl : null,
                            PostDate = TryParseDate(raw.DateStr)
                        });
                    }
                }
            }
            else
            {
                _logger.LogWarning("Scroll {Scroll}: JS evaluation returned empty", scroll);
            }

            // Scroll down
            await page.EvaluateAsync("window.scrollBy(0, window.innerHeight * 2)");
            await Task.Delay(2500);
        }

        return posts;
    }

    private static async Task<string> GetPageErrorText(IPage page)
    {
        var errorEl = await page.QuerySelectorAsync("[class*='error'], [class*='alert'], [data-testid*='error']");
        return errorEl != null
            ? await errorEl.TextContentAsync() ?? "Login timed out"
            : "Login timed out — check credentials";
    }

    private static DateTime? TryParseDate(string? dateStr)
    {
        if (string.IsNullOrWhiteSpace(dateStr)) return DateTime.UtcNow;

        if (DateTime.TryParse(dateStr, out var parsed))
            return parsed.ToUniversalTime();

        dateStr = dateStr.Trim().ToLower();
        if (dateStr.Contains("just now") || dateStr.Contains("moment"))
            return DateTime.UtcNow;

        // Extract number from start of string
        var numStr = new string(dateStr.TakeWhile(char.IsDigit).ToArray());
        if (int.TryParse(numStr, out var num))
        {
            if (dateStr.Contains("min") || dateStr.Contains("m ago")) return DateTime.UtcNow.AddMinutes(-num);
            if (dateStr.Contains("hr") || dateStr.Contains("h ago") || dateStr.Contains("hour")) return DateTime.UtcNow.AddHours(-num);
            if (dateStr.Contains("day") || dateStr.Contains("d ago")) return DateTime.UtcNow.AddDays(-num);
            if (dateStr.Contains("week") || dateStr.Contains("w ago")) return DateTime.UtcNow.AddDays(-num * 7);
        }

        return DateTime.UtcNow;
    }

    private class RawPost
    {
        public string? Author { get; set; }
        public string Content { get; set; } = "";
        public string? PostUrl { get; set; }
        public string? DateStr { get; set; }
    }
}
