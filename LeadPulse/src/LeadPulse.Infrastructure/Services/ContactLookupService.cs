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

    public async Task<ContactLookupResult> LookupAsync(int tenantId, string prospectName, string? platform, string? postUrl)
    {
        // Find the first enabled enrichment provider
        var settings = await _tenantDb.EnrichmentSettings
            .Where(s => s.IsEnabled)
            .OrderBy(s => s.Provider)
            .FirstOrDefaultAsync();

        if (settings == null)
            return new ContactLookupResult { Success = false, Error = "No enrichment provider is enabled. Configure one in Account Config > Contact Data Config." };

        if (string.IsNullOrEmpty(settings.EncryptedApiKey) && string.IsNullOrEmpty(settings.EncryptedPassword))
            return new ContactLookupResult { Success = false, Error = $"{settings.Provider} has no credentials configured. Update in Account Config > Contact Data Config." };

        try
        {
            var apiKey = !string.IsNullOrEmpty(settings.EncryptedApiKey)
                ? _encryptionService.Decrypt(settings.EncryptedApiKey, tenantId)
                : null;

            return settings.Provider switch
            {
                "ContactOut" => await LookupContactOut(apiKey, prospectName, platform, postUrl),
                "Apollo" => await LookupApollo(apiKey, prospectName, platform, postUrl),
                _ => new ContactLookupResult { Success = false, Error = $"Unknown provider: {settings.Provider}" }
            };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Contact lookup failed for {Provider}", settings.Provider);
            return new ContactLookupResult { Success = false, Error = $"{settings.Provider} lookup failed: {ex.Message}" };
        }
    }

    private async Task<ContactLookupResult> LookupContactOut(string? apiKey, string name, string? platform, string? postUrl)
    {
        if (string.IsNullOrEmpty(apiKey))
            return new ContactLookupResult { Success = false, Error = "ContactOut API key not configured" };

        var client = _httpClientFactory.CreateClient();
        client.DefaultRequestHeaders.Add("Authorization", $"Bearer {apiKey}");

        // ContactOut People Search API
        var searchUrl = $"https://api.contactout.com/v1/people/search?name={Uri.EscapeDataString(name)}&limit=1";
        if (!string.IsNullOrEmpty(platform) && platform.Equals("LinkedIn", StringComparison.OrdinalIgnoreCase) && !string.IsNullOrEmpty(postUrl))
        {
            searchUrl = $"https://api.contactout.com/v1/people/linkedin?profile_url={Uri.EscapeDataString(postUrl)}";
        }

        var response = await client.GetAsync(searchUrl);

        if (!response.IsSuccessStatusCode)
        {
            var errorBody = await response.Content.ReadAsStringAsync();
            _logger.LogWarning("ContactOut API returned {Status}: {Body}", response.StatusCode, errorBody);
            return new ContactLookupResult { Success = false, Error = $"ContactOut API error: {response.StatusCode}", Provider = "ContactOut" };
        }

        var json = await response.Content.ReadAsStringAsync();
        var doc = System.Text.Json.JsonDocument.Parse(json);
        var root = doc.RootElement;

        string? email = null, phone = null, company = null, linkedIn = null;

        if (root.TryGetProperty("profiles", out var profiles) && profiles.GetArrayLength() > 0)
        {
            var profile = profiles[0];
            if (profile.TryGetProperty("emails", out var emails) && emails.GetArrayLength() > 0)
                email = emails[0].GetString();
            if (profile.TryGetProperty("phones", out var phones) && phones.GetArrayLength() > 0)
                phone = phones[0].GetString();
            if (profile.TryGetProperty("company", out var comp))
                company = comp.GetString();
            if (profile.TryGetProperty("linkedin_url", out var li))
                linkedIn = li.GetString();
        }
        else if (root.TryGetProperty("email", out var singleEmail))
        {
            email = singleEmail.GetString();
            if (root.TryGetProperty("phone", out var singlePhone))
                phone = singlePhone.GetString();
        }

        if (email == null && phone == null)
            return new ContactLookupResult { Success = false, Error = "ContactOut found no contact data for this prospect", Provider = "ContactOut" };

        return new ContactLookupResult { Success = true, Email = email, Phone = phone, Company = company, LinkedInUrl = linkedIn, Provider = "ContactOut" };
    }

    private async Task<ContactLookupResult> LookupApollo(string? apiKey, string name, string? platform, string? postUrl)
    {
        if (string.IsNullOrEmpty(apiKey))
            return new ContactLookupResult { Success = false, Error = "Apollo API key not configured" };

        var client = _httpClientFactory.CreateClient();

        // Apollo People Search API
        var parts = name.Split(' ', 2);
        var firstName = parts[0];
        var lastName = parts.Length > 1 ? parts[1] : "";

        var requestBody = new
        {
            api_key = apiKey,
            first_name = firstName,
            last_name = lastName,
            page = 1,
            per_page = 1
        };

        var content = new StringContent(
            System.Text.Json.JsonSerializer.Serialize(requestBody),
            System.Text.Encoding.UTF8, "application/json");

        var response = await client.PostAsync("https://api.apollo.io/api/v1/mixed_people/search", content);

        if (!response.IsSuccessStatusCode)
        {
            var errorBody = await response.Content.ReadAsStringAsync();
            _logger.LogWarning("Apollo API returned {Status}: {Body}", response.StatusCode, errorBody);
            return new ContactLookupResult { Success = false, Error = $"Apollo API error: {response.StatusCode}", Provider = "Apollo" };
        }

        var json = await response.Content.ReadAsStringAsync();
        var doc = System.Text.Json.JsonDocument.Parse(json);
        var root = doc.RootElement;

        string? email = null, phone = null, company = null, linkedIn = null;

        if (root.TryGetProperty("people", out var people) && people.GetArrayLength() > 0)
        {
            var person = people[0];
            if (person.TryGetProperty("email", out var em))
                email = em.GetString();
            if (person.TryGetProperty("phone_numbers", out var phones) && phones.GetArrayLength() > 0)
            {
                var phoneObj = phones[0];
                if (phoneObj.TryGetProperty("sanitized_number", out var num))
                    phone = num.GetString();
                else if (phoneObj.TryGetProperty("raw_number", out var raw))
                    phone = raw.GetString();
            }
            if (person.TryGetProperty("organization", out var org) && org.TryGetProperty("name", out var orgName))
                company = orgName.GetString();
            if (person.TryGetProperty("linkedin_url", out var li))
                linkedIn = li.GetString();
        }

        if (email == null && phone == null)
            return new ContactLookupResult { Success = false, Error = "Apollo found no contact data for this prospect", Provider = "Apollo" };

        return new ContactLookupResult { Success = true, Email = email, Phone = phone, Company = company, LinkedInUrl = linkedIn, Provider = "Apollo" };
    }
}
