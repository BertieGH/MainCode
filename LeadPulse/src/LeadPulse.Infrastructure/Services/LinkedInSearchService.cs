using LeadPulse.Application.Interfaces;
using LeadPulse.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using System.Text.Json;

namespace LeadPulse.Infrastructure.Services;

public class LinkedInCandidate
{
    public string Url { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string Headline { get; set; } = string.Empty;
    public string Snippet { get; set; } = string.Empty;
}

public class LinkedInSearchResult
{
    public bool Success { get; set; }
    public List<LinkedInCandidate> Candidates { get; set; } = new();
    public string? Error { get; set; }
}

public class LinkedInSearchService
{
    private readonly TenantDbContext _tenantDb;
    private readonly IEncryptionService _encryptionService;
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly ILogger<LinkedInSearchService> _logger;

    public LinkedInSearchService(
        TenantDbContext tenantDb,
        IEncryptionService encryptionService,
        IHttpClientFactory httpClientFactory,
        ILogger<LinkedInSearchService> logger)
    {
        _tenantDb = tenantDb;
        _encryptionService = encryptionService;
        _httpClientFactory = httpClientFactory;
        _logger = logger;
    }

    public async Task<LinkedInSearchResult> SearchAsync(int tenantId, string name, string? city, string? state, string? email)
    {
        var settings = await _tenantDb.EnrichmentSettings
            .FirstOrDefaultAsync(s => s.Provider == "SerpApi" && s.IsEnabled && !string.IsNullOrEmpty(s.EncryptedApiKey));

        if (settings == null)
            return new LinkedInSearchResult { Success = false, Error = "SerpAPI is not configured. Add your SerpAPI key in Account Config > Contact Data Config." };

        var apiKey = _encryptionService.Decrypt(settings.EncryptedApiKey!, tenantId);

        // Build queries from most specific to broadest
        var queries = new List<string>();

        // Query 1: Name + City, State + email (most specific)
        var q1 = $"\"{name}\" site:linkedin.com/in";
        if (!string.IsNullOrEmpty(city) && !string.IsNullOrEmpty(state))
            q1 += $" \"{city}, {state}\"";
        else if (!string.IsNullOrEmpty(state))
            q1 += $" \"{state}\"";
        else if (!string.IsNullOrEmpty(city))
            q1 += $" \"{city}\"";
        if (!string.IsNullOrEmpty(email))
            q1 += $" OR \"{email}\"";
        queries.Add(q1);

        // Query 2: Name + State only (broader location)
        if (!string.IsNullOrEmpty(city) && !string.IsNullOrEmpty(state))
            queries.Add($"\"{name}\" site:linkedin.com/in \"{state}\"");

        // Query 3: Just name (broadest)
        queries.Add($"\"{name}\" site:linkedin.com/in");

        try
        {
            var client = _httpClientFactory.CreateClient();

            foreach (var query in queries)
            {
                _logger.LogInformation("LinkedIn search query: {Query}", query);
                var encodedQuery = Uri.EscapeDataString(query);
                var url = $"https://serpapi.com/search.json?engine=google&q={encodedQuery}&num=5&api_key={apiKey}";

                var response = await client.GetAsync(url);
                if (!response.IsSuccessStatusCode)
                {
                    var errorBody = await response.Content.ReadAsStringAsync();
                    _logger.LogWarning("SerpAPI returned {Status}: {Body}", response.StatusCode, errorBody);
                    continue;
                }

                var json = await response.Content.ReadAsStringAsync();
                _logger.LogInformation("SerpAPI response length: {Len}", json.Length);

                var doc = JsonDocument.Parse(json);
                var candidates = ParseCandidates(doc);

                if (candidates.Count > 0)
                    return new LinkedInSearchResult { Success = true, Candidates = candidates };

                _logger.LogInformation("No LinkedIn results for query, trying broader search...");
            }

            return new LinkedInSearchResult { Success = false, Error = "No LinkedIn profiles found after trying multiple searches" };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "LinkedIn search failed");
            return new LinkedInSearchResult { Success = false, Error = $"Search failed: {ex.Message}" };
        }
    }

    private static List<LinkedInCandidate> ParseCandidates(JsonDocument doc)
    {
        var candidates = new List<LinkedInCandidate>();

        if (doc.RootElement.TryGetProperty("organic_results", out var results) &&
            results.ValueKind == JsonValueKind.Array)
        {
            foreach (var result in results.EnumerateArray())
            {
                var link = result.TryGetProperty("link", out var l) ? l.GetString() ?? "" : "";
                if (!link.Contains("linkedin.com/in/")) continue;

                var title = result.TryGetProperty("title", out var t) ? t.GetString() ?? "" : "";
                var snippet = result.TryGetProperty("snippet", out var s) ? s.GetString() ?? "" : "";

                var parts = title.Split(" - ", StringSplitOptions.TrimEntries);
                var candidateName = parts.Length > 0 ? parts[0].Replace(" | LinkedIn", "").Trim() : title;
                var headline = parts.Length > 1 ? string.Join(" - ", parts.Skip(1)).Replace(" | LinkedIn", "").Trim() : "";

                candidates.Add(new LinkedInCandidate
                {
                    Url = link,
                    Name = candidateName,
                    Headline = headline,
                    Snippet = snippet.Length > 200 ? snippet[..200] + "..." : snippet
                });

                if (candidates.Count >= 3) break;
            }
        }

        return candidates;
    }
}
