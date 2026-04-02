using LeadPulse.Application.Interfaces;
using LeadPulse.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace LeadPulse.Infrastructure.Services;

public class ContactLookupResult
{
    public bool Success { get; set; }
    public string? Phone { get; set; }
    public string? Email { get; set; }
    public string? Company { get; set; }
    public string? LinkedInUrl { get; set; }
    public string? Error { get; set; }
    public string Provider { get; set; } = string.Empty;
}

public class ContactLookupService
{
    private readonly TenantDbContext _tenantDb;
    private readonly IEncryptionService _encryptionService;
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly ILogger<ContactLookupService> _logger;

    public ContactLookupService(
        TenantDbContext tenantDb,
        IEncryptionService encryptionService,
        IHttpClientFactory httpClientFactory,
        ILogger<ContactLookupService> logger)
    {
        _tenantDb = tenantDb;
        _encryptionService = encryptionService;
        _httpClientFactory = httpClientFactory;
        _logger = logger;
    }

    public async Task<ContactLookupResult> LookupAsync(int tenantId, string prospectName, string? platform, string? postUrl, string? city = null, string? state = null, string? company = null)
    {
        // Get all enabled providers, ordered so we can waterfall
        var allSettings = await _tenantDb.EnrichmentSettings
            .Where(s => s.IsEnabled && (!string.IsNullOrEmpty(s.EncryptedApiKey) || !string.IsNullOrEmpty(s.EncryptedPassword)))
            .OrderBy(s => s.Provider)
            .ToListAsync();

        _logger.LogInformation("Enrichment waterfall: {Count} enabled providers found: {Providers}",
            allSettings.Count, string.Join(", ", allSettings.Select(s => $"{s.Provider}(key={!string.IsNullOrEmpty(s.EncryptedApiKey)},pwd={!string.IsNullOrEmpty(s.EncryptedPassword)})")));

        if (allSettings.Count == 0)
            return new ContactLookupResult { Success = false, Error = "No enrichment provider is enabled with credentials. Configure one in Account Config > Contact Data Config." };

        // Waterfall: try each provider until one returns contact data
        var errors = new List<string>();
        foreach (var settings in allSettings)
        {
            try
            {
                var apiKey = !string.IsNullOrEmpty(settings.EncryptedApiKey)
                    ? _encryptionService.Decrypt(settings.EncryptedApiKey, tenantId)
                    : null;

                var result = settings.Provider switch
                {
                    "ContactOut" => await LookupContactOut(apiKey, prospectName, platform, postUrl, city, state, company),
                    "Apollo" => await LookupApollo(apiKey, prospectName, platform, postUrl, city, state, company),
                    _ => new ContactLookupResult { Success = false, Error = $"Unknown provider: {settings.Provider}" }
                };

                if (result.Success)
                {
                    _logger.LogInformation("Enrichment succeeded via {Provider} for {Name}", settings.Provider, prospectName);
                    return result;
                }

                _logger.LogInformation("Enrichment via {Provider} returned no data for {Name}: {Error}", settings.Provider, prospectName, result.Error);
                errors.Add($"{settings.Provider}: {result.Error}");
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Contact lookup failed for {Provider}", settings.Provider);
                errors.Add($"{settings.Provider}: {ex.Message}");
            }
        }

        return new ContactLookupResult
        {
            Success = false,
            Error = $"No provider returned contact data. {string.Join(" | ", errors)}",
            Provider = string.Join(", ", allSettings.Select(s => s.Provider))
        };
    }

    public async Task<ContactLookupResult> TestConnectionAsync(int tenantId, string provider)
    {
        var settings = await _tenantDb.EnrichmentSettings
            .FirstOrDefaultAsync(s => s.Provider == provider);

        if (settings == null)
            return new ContactLookupResult { Success = false, Error = $"{provider} is not configured.", Provider = provider };

        var hasApiKey = !string.IsNullOrEmpty(settings.EncryptedApiKey);
        var hasPassword = !string.IsNullOrEmpty(settings.EncryptedPassword);
        var hasUsername = !string.IsNullOrEmpty(settings.Username);

        if (!hasApiKey && !hasPassword)
            return new ContactLookupResult { Success = false, Error = $"{provider} has no credentials configured.", Provider = provider };

        try
        {
            var apiKey = hasApiKey ? _encryptionService.Decrypt(settings.EncryptedApiKey!, tenantId) : null;
            var password = hasPassword ? _encryptionService.Decrypt(settings.EncryptedPassword!, tenantId) : null;
            var client = _httpClientFactory.CreateClient();

            if (provider == "ContactOut")
            {
                // If API key is set, test it against ContactOut API
                if (!string.IsNullOrEmpty(apiKey))
                {
                    client.DefaultRequestHeaders.Add("token", apiKey);
                    var testBody = new StringContent(
                        System.Text.Json.JsonSerializer.Serialize(new { name = "test", page_size = 1 }),
                        System.Text.Encoding.UTF8, "application/json");
                    var response = await client.PostAsync("https://api.contactout.com/v1/people/search", testBody);
                    if (response.IsSuccessStatusCode)
                        return new ContactLookupResult { Success = true, Provider = provider };
                    // 422, 404, or 400 with valid auth still means the key works
                    if (response.StatusCode == System.Net.HttpStatusCode.UnprocessableEntity ||
                        response.StatusCode == System.Net.HttpStatusCode.NotFound ||
                        response.StatusCode == System.Net.HttpStatusCode.BadRequest)
                        return new ContactLookupResult { Success = true, Provider = provider };
                    var body = await response.Content.ReadAsStringAsync();
                    _logger.LogWarning("ContactOut test returned {Status}: {Body}", response.StatusCode, body);
                    return new ContactLookupResult { Success = false, Error = $"ContactOut API key invalid — returned {response.StatusCode}", Provider = provider };
                }

                // Username/password — credentials are saved but enrichment requires an API key
                if (hasUsername && !string.IsNullOrEmpty(password))
                    return new ContactLookupResult { Success = true, Error = "Credentials saved, but an API key is needed for enrichment lookups.", Provider = provider };

                return new ContactLookupResult { Success = false, Error = "ContactOut requires an API key for enrichment.", Provider = provider };
            }
            else if (provider == "Apollo")
            {
                if (!string.IsNullOrEmpty(apiKey))
                {
                    // Use /v1/auth/health to validate the API key without needing endpoint access
                    client.DefaultRequestHeaders.Add("X-Api-Key", apiKey);
                    var response = await client.GetAsync("https://api.apollo.io/v1/auth/health");
                    _logger.LogInformation("Apollo health check returned {Status}", response.StatusCode);
                    var body = await response.Content.ReadAsStringAsync();
                    _logger.LogInformation("Apollo health response: {Body}", body);
                    if (response.IsSuccessStatusCode)
                        return new ContactLookupResult { Success = true, Provider = provider };
                    if (response.StatusCode == System.Net.HttpStatusCode.Unauthorized || response.StatusCode == System.Net.HttpStatusCode.Forbidden)
                        return new ContactLookupResult { Success = false, Error = $"Apollo API key rejected — {response.StatusCode}. Verify at app.apollo.io > Settings > API Keys.", Provider = provider };
                    // Any other response with valid auth means the key works
                    return new ContactLookupResult { Success = true, Provider = provider };
                }

                if (hasUsername && !string.IsNullOrEmpty(password))
                    return new ContactLookupResult { Success = true, Error = "Credentials saved, but an API key is needed for enrichment lookups.", Provider = provider };

                return new ContactLookupResult { Success = false, Error = "Apollo requires an API key for enrichment.", Provider = provider };
            }

            return new ContactLookupResult { Success = false, Error = $"Unknown provider: {provider}", Provider = provider };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Test connection failed for {Provider}", provider);
            return new ContactLookupResult { Success = false, Error = $"Connection test failed: {ex.Message}", Provider = provider };
        }
    }

    private async Task<ContactLookupResult> LookupContactOut(string? apiKey, string name, string? platform, string? postUrl, string? city = null, string? state = null, string? companyName = null)
    {
        if (string.IsNullOrEmpty(apiKey))
            return new ContactLookupResult { Success = false, Error = "ContactOut API key is required for enrichment lookups. Username/password alone cannot be used for API searches — add an API key in Account Config > Contact Data Config.", Provider = "ContactOut" };

        var client = _httpClientFactory.CreateClient();
        client.DefaultRequestHeaders.Add("token", apiKey);
        client.DefaultRequestHeaders.Add("Accept", "application/json");

        // Use People Enrich API — POST /v1/people/enrich
        var enrichDict = new Dictionary<string, object>
        {
            ["full_name"] = name,
            ["include"] = new[] { "work_email", "personal_email", "phone" }
        };

        // Add location if available
        if (!string.IsNullOrEmpty(city) && !string.IsNullOrEmpty(state))
            enrichDict["location"] = $"{city}, {state}";
        else if (!string.IsNullOrEmpty(state))
            enrichDict["location"] = state;
        else if (!string.IsNullOrEmpty(city))
            enrichDict["location"] = city;

        // Add company only if available
        if (!string.IsNullOrEmpty(companyName))
            enrichDict["company"] = new[] { companyName };

        // If we have a LinkedIn URL, use it as primary identifier
        if (!string.IsNullOrEmpty(platform) && platform.Equals("LinkedIn", StringComparison.OrdinalIgnoreCase) && !string.IsNullOrEmpty(postUrl))
            enrichDict["linkedin_url"] = postUrl;

        var requestJson = System.Text.Json.JsonSerializer.Serialize(enrichDict);
        _logger.LogInformation("ContactOut enrich request: {Request}", requestJson);

        var content = new StringContent(requestJson, System.Text.Encoding.UTF8, "application/json");
        var response = await client.PostAsync("https://api.contactout.com/v1/people/enrich", content);

        if (!response.IsSuccessStatusCode)
        {
            var errorBody = await response.Content.ReadAsStringAsync();
            _logger.LogWarning("ContactOut enrich API returned {Status}: {Body}", response.StatusCode, errorBody);
            return new ContactLookupResult { Success = false, Error = $"ContactOut API error: {response.StatusCode}", Provider = "ContactOut" };
        }

        var json = await response.Content.ReadAsStringAsync();
        _logger.LogInformation("ContactOut enrich response: {Json}", json.Length > 1000 ? json[..1000] : json);
        var doc = System.Text.Json.JsonDocument.Parse(json);
        var root = doc.RootElement;

        string? email = null, phone = null, company = null, linkedIn = null;

        // Enrich API returns { profile: { email: [...], work_email: [...], phone: [...], company: { name: "..." } } }
        if (root.TryGetProperty("profile", out var profile))
        {
            // Emails — try personal_email, email, work_email arrays
            foreach (var emailField in new[] { "personal_email", "email", "work_email" })
            {
                if (email != null) break;
                if (profile.TryGetProperty(emailField, out var emails) && emails.ValueKind == System.Text.Json.JsonValueKind.Array && emails.GetArrayLength() > 0)
                    email = emails[0].GetString();
            }

            // Phone
            if (profile.TryGetProperty("phone", out var phones) && phones.ValueKind == System.Text.Json.JsonValueKind.Array && phones.GetArrayLength() > 0)
                phone = phones[0].GetString();

            // Company
            if (profile.TryGetProperty("company", out var comp))
            {
                if (comp.ValueKind == System.Text.Json.JsonValueKind.String)
                    company = comp.GetString();
                else if (comp.ValueKind == System.Text.Json.JsonValueKind.Object && comp.TryGetProperty("name", out var compN))
                    company = compN.GetString();
            }

            // LinkedIn
            if (profile.TryGetProperty("linkedin_url", out var li))
                linkedIn = li.GetString();
        }

        if (email == null && phone == null)
            return new ContactLookupResult { Success = false, Error = "ContactOut found no contact data for this prospect", Provider = "ContactOut" };

        return new ContactLookupResult { Success = true, Email = email, Phone = phone, Company = company, LinkedInUrl = linkedIn, Provider = "ContactOut" };
    }

    private async Task<ContactLookupResult> LookupApollo(string? apiKey, string name, string? platform, string? postUrl, string? city = null, string? state = null, string? companyName = null)
    {
        if (string.IsNullOrEmpty(apiKey))
            return new ContactLookupResult { Success = false, Error = "Apollo API key is required for enrichment lookups. Add an API key in Account Config > Contact Data Config.", Provider = "Apollo" };

        var client = _httpClientFactory.CreateClient();
        client.DefaultRequestHeaders.Add("X-Api-Key", apiKey);

        // Apollo People Search API
        var parts = name.Split(' ', 2);
        var firstName = parts[0];
        var lastName = parts.Length > 1 ? parts[1] : "";

        // Try /v1/people/match first, fall back to /v1/people/search
        // Build match body with optional location and company for better matching
        var matchDict = new Dictionary<string, object>
        {
            ["first_name"] = firstName,
            ["last_name"] = lastName,
            ["reveal_personal_emails"] = true
        };
        if (!string.IsNullOrEmpty(companyName))
            matchDict["organization_name"] = companyName;
        if (!string.IsNullOrEmpty(city))
            matchDict["city"] = city;
        if (!string.IsNullOrEmpty(state))
            matchDict["state"] = state;
        var matchBody = matchDict;

        var content = new StringContent(
            System.Text.Json.JsonSerializer.Serialize(matchBody),
            System.Text.Encoding.UTF8, "application/json");

        var response = await client.PostAsync("https://api.apollo.io/v1/people/match", content);

        // If /v1/people/match is forbidden, try /v1/people/search
        if (response.StatusCode == System.Net.HttpStatusCode.Forbidden)
        {
            _logger.LogInformation("Apollo /v1/people/match forbidden, trying /v1/people/search");
            var searchBody = new
            {
                person_titles = Array.Empty<string>(),
                q_keywords = name,
                page = 1,
                per_page = 1,
                reveal_personal_emails = true
            };
            content = new StringContent(
                System.Text.Json.JsonSerializer.Serialize(searchBody),
                System.Text.Encoding.UTF8, "application/json");
            response = await client.PostAsync("https://api.apollo.io/v1/people/search", content);
        }

        if (!response.IsSuccessStatusCode)
        {
            var errorBody = await response.Content.ReadAsStringAsync();
            _logger.LogWarning("Apollo API returned {Status}: {Body}", response.StatusCode, errorBody);
            return new ContactLookupResult { Success = false, Error = $"Apollo API error: {response.StatusCode}", Provider = "Apollo" };
        }

        var json = await response.Content.ReadAsStringAsync();
        _logger.LogInformation("Apollo response: {Json}", json.Length > 500 ? json[..500] : json);
        var doc = System.Text.Json.JsonDocument.Parse(json);
        var root = doc.RootElement;

        string? email = null, phone = null, company = null, linkedIn = null;

        // /v1/people/match returns { person: {...} }, search returns { people: [...] }
        System.Text.Json.JsonElement? person = null;
        if (root.TryGetProperty("person", out var singlePerson) && singlePerson.ValueKind == System.Text.Json.JsonValueKind.Object)
        {
            person = singlePerson;
        }
        else if (root.TryGetProperty("people", out var people) && people.ValueKind == System.Text.Json.JsonValueKind.Array && people.GetArrayLength() > 0)
        {
            person = people[0];
        }

        if (person.HasValue)
        {
            var p = person.Value;
            if (p.TryGetProperty("email", out var em))
                email = em.GetString();
            if (email == null && p.TryGetProperty("personal_emails", out var personalEmails) && personalEmails.ValueKind == System.Text.Json.JsonValueKind.Array && personalEmails.GetArrayLength() > 0)
                email = personalEmails[0].GetString();
            if (p.TryGetProperty("phone_numbers", out var phones) && phones.ValueKind == System.Text.Json.JsonValueKind.Array && phones.GetArrayLength() > 0)
            {
                var phoneObj = phones[0];
                if (phoneObj.TryGetProperty("sanitized_number", out var num))
                    phone = num.GetString();
                else if (phoneObj.TryGetProperty("raw_number", out var raw))
                    phone = raw.GetString();
            }
            if (p.TryGetProperty("organization", out var org) && org.TryGetProperty("name", out var orgName))
                company = orgName.GetString();
            if (company == null && p.TryGetProperty("organization_name", out var orgN))
                company = orgN.GetString();
            if (p.TryGetProperty("linkedin_url", out var li))
                linkedIn = li.GetString();
        }

        if (email == null && phone == null)
            return new ContactLookupResult { Success = false, Error = "Apollo found no contact data for this prospect", Provider = "Apollo" };

        return new ContactLookupResult { Success = true, Email = email, Phone = phone, Company = company, LinkedInUrl = linkedIn, Provider = "Apollo" };
    }
}
