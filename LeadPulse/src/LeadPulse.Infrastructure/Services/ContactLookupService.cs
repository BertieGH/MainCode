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

    public async Task<ContactLookupResult> LookupAsync(int tenantId, string prospectName, string? platform, string? postUrl, string? city = null, string? state = null, string? company = null, string? linkedInUrl = null, string? existingEmail = null)
    {
        // Get all enabled enrichment providers (exclude SerpApi — it's for LinkedIn search only)
        var enrichmentProviders = new[] { "Apollo", "ContactOut" };
        var allSettings = await _tenantDb.EnrichmentSettings
            .Where(s => s.IsEnabled && enrichmentProviders.Contains(s.Provider) && (!string.IsNullOrEmpty(s.EncryptedApiKey) || !string.IsNullOrEmpty(s.EncryptedPassword)))
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
                    "ContactOut" => await LookupContactOut(apiKey, prospectName, platform, postUrl, city, state, company, linkedInUrl),
                    "Apollo" => await LookupApollo(apiKey, prospectName, platform, postUrl, city, state, company, linkedInUrl, existingEmail),
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

    private async Task<ContactLookupResult> LookupContactOut(string? apiKey, string name, string? platform, string? postUrl, string? city = null, string? state = null, string? companyName = null, string? linkedInUrl = null)
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

        // If we have a LinkedIn URL, use it as primary identifier (best match)
        if (!string.IsNullOrEmpty(linkedInUrl))
            enrichDict["linkedin_url"] = linkedInUrl;
        else if (!string.IsNullOrEmpty(platform) && platform.Equals("LinkedIn", StringComparison.OrdinalIgnoreCase) && !string.IsNullOrEmpty(postUrl))
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

        // Detect sample/demo responses — ContactOut returns these when API key lacks full access
        if (root.TryGetProperty("message", out var msg))
        {
            var message = msg.GetString() ?? "";
            if (message.Contains("sample response", StringComparison.OrdinalIgnoreCase) ||
                message.Contains("book a call", StringComparison.OrdinalIgnoreCase) ||
                message.Contains("unlock full access", StringComparison.OrdinalIgnoreCase))
            {
                _logger.LogWarning("ContactOut returned sample/demo data — API key lacks full access: {Message}", message);
                return new ContactLookupResult { Success = false, Error = "ContactOut API key lacks full access — returned sample data only. Upgrade your ContactOut plan.", Provider = "ContactOut" };
            }
        }

        // Also check if profile contains known sample indicators
        if (root.TryGetProperty("profile", out var profileCheck))
        {
            var profileUrl = profileCheck.TryGetProperty("url", out var pUrl) ? pUrl.GetString() ?? "" : "";
            var fullName = profileCheck.TryGetProperty("full_name", out var fn) ? fn.GetString() ?? "" : "";
            if (profileUrl.Contains("example-person") || fullName == "Example Person")
            {
                _logger.LogWarning("ContactOut returned sample profile data (Example Person)");
                return new ContactLookupResult { Success = false, Error = "ContactOut returned sample/demo data — not real contact info.", Provider = "ContactOut" };
            }
        }

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

        // Filter out sample/placeholder data
        if (email != null && (email.Contains("@example.com") || email == "email1@example.com" || email == "email2@gmail.com"))
        {
            _logger.LogWarning("ContactOut returned sample email: {Email} — discarding", email);
            email = null;
        }
        if (phone != null && (phone == "+1234567891" || phone == "1234567891"))
        {
            _logger.LogWarning("ContactOut returned sample phone: {Phone} — discarding", phone);
            phone = null;
        }
        if (company != null && company == "Legros, Smitham and Kessler")
        {
            _logger.LogWarning("ContactOut returned sample company — discarding");
            company = null;
        }
        if (linkedIn != null && linkedIn.Contains("example-person"))
        {
            _logger.LogWarning("ContactOut returned sample LinkedIn — discarding");
            linkedIn = null;
        }

        if (email == null && phone == null)
            return new ContactLookupResult { Success = false, Error = "ContactOut found no contact data for this prospect", Provider = "ContactOut" };

        return new ContactLookupResult { Success = true, Email = email, Phone = phone, Company = company, LinkedInUrl = linkedIn, Provider = "ContactOut" };
    }

    private async Task<ContactLookupResult> LookupApollo(string? apiKey, string name, string? platform, string? postUrl, string? city = null, string? state = null, string? companyName = null, string? linkedInUrl = null, string? existingEmail = null)
    {
        if (string.IsNullOrEmpty(apiKey))
            return new ContactLookupResult { Success = false, Error = "Apollo API key is required for enrichment lookups. Add an API key in Account Config > Contact Data Config.", Provider = "Apollo" };

        var client = _httpClientFactory.CreateClient();

        var parts = name.Split(' ', 2);
        var firstName = parts[0];
        var lastName = parts.Length > 1 ? parts[1] : "";

        // Strategy 1: If we have a LinkedIn URL, use /v1/people/match with it (highest accuracy)
        if (!string.IsNullOrEmpty(linkedInUrl))
        {
            _logger.LogInformation("Apollo: trying /v1/people/match with LinkedIn URL for {Name}", name);
            var matchDict = new Dictionary<string, object>
            {
                ["linkedin_url"] = linkedInUrl,
                ["reveal_personal_emails"] = true,
                ["reveal_phone_number"] = true
            };
            var (email, phone, company, linkedIn) = await CallApolloEndpoint(client, apiKey, "https://api.apollo.io/v1/people/match", matchDict);
            if (email != null || phone != null)
                return new ContactLookupResult { Success = true, Email = email, Phone = phone, Company = company, LinkedInUrl = linkedIn ?? linkedInUrl, Provider = "Apollo" };
        }

        // Strategy 2: If we have an email, use /v1/people/match with it
        if (!string.IsNullOrEmpty(existingEmail) && !existingEmail.Contains("@example.com"))
        {
            _logger.LogInformation("Apollo: trying /v1/people/match with email for {Name}", name);
            var matchDict = new Dictionary<string, object>
            {
                ["email"] = existingEmail,
                ["first_name"] = firstName,
                ["last_name"] = lastName,
                ["reveal_personal_emails"] = true,
                ["reveal_phone_number"] = true
            };
            var (email, phone, company, linkedIn) = await CallApolloEndpoint(client, apiKey, "https://api.apollo.io/v1/people/match", matchDict);
            if (email != null || phone != null)
                return new ContactLookupResult { Success = true, Email = email, Phone = phone, Company = company, LinkedInUrl = linkedIn, Provider = "Apollo" };
        }

        // Strategy 3: Name + location + company match
        {
            _logger.LogInformation("Apollo: trying /v1/people/match with name+location for {Name}", name);
            var matchDict = new Dictionary<string, object>
            {
                ["first_name"] = firstName,
                ["last_name"] = lastName,
                ["reveal_personal_emails"] = true,
                ["reveal_phone_number"] = true
            };
            if (!string.IsNullOrEmpty(companyName))
                matchDict["organization_name"] = companyName;
            if (!string.IsNullOrEmpty(city))
                matchDict["city"] = city;
            if (!string.IsNullOrEmpty(state))
                matchDict["state"] = state;

            var (email, phone, company, linkedIn) = await CallApolloEndpoint(client, apiKey, "https://api.apollo.io/v1/people/match", matchDict);
            if (email != null || phone != null)
                return new ContactLookupResult { Success = true, Email = email, Phone = phone, Company = company, LinkedInUrl = linkedIn, Provider = "Apollo" };
        }

        // Strategy 4: Broader search with /v1/people/search
        {
            _logger.LogInformation("Apollo: trying /v1/people/search fallback for {Name}", name);
            var (email, phone, company, linkedIn) = await ApolloSearchFallback(client, apiKey, name, firstName, lastName, city, state, companyName);
            if (email != null || phone != null)
                return new ContactLookupResult { Success = true, Email = email, Phone = phone, Company = company, LinkedInUrl = linkedIn, Provider = "Apollo" };
        }

        return new ContactLookupResult { Success = false, Error = "Apollo found no contact data for this prospect", Provider = "Apollo" };
    }

    private async Task<(string? email, string? phone, string? company, string? linkedIn)> CallApolloEndpoint(
        HttpClient client, string apiKey, string url, Dictionary<string, object> body)
    {
        // Create a new client for each call to avoid duplicate headers
        var req = new HttpRequestMessage(HttpMethod.Post, url);
        req.Headers.Add("X-Api-Key", apiKey);
        req.Content = new StringContent(
            System.Text.Json.JsonSerializer.Serialize(body),
            System.Text.Encoding.UTF8, "application/json");

        _logger.LogInformation("Apollo request to {Url}: {Body}",
            url, System.Text.Json.JsonSerializer.Serialize(body).Length > 300
                ? System.Text.Json.JsonSerializer.Serialize(body)[..300]
                : System.Text.Json.JsonSerializer.Serialize(body));

        var response = await client.SendAsync(req);

        if (!response.IsSuccessStatusCode)
        {
            var errorBody = await response.Content.ReadAsStringAsync();
            _logger.LogWarning("Apollo {Url} returned {Status}: {Body}", url, response.StatusCode, errorBody.Length > 300 ? errorBody[..300] : errorBody);
            return (null, null, null, null);
        }

        var json = await response.Content.ReadAsStringAsync();
        _logger.LogInformation("Apollo response ({Len} chars): {Json}", json.Length, json.Length > 500 ? json[..500] : json);

        return ParseApolloJson(json);
    }

    private async Task<(string? email, string? phone, string? company, string? linkedIn)> ApolloSearchFallback(
        HttpClient client, string apiKey, string name, string firstName, string lastName, string? city, string? state, string? companyName)
    {
        var searchDict = new Dictionary<string, object>
        {
            ["page"] = 1,
            ["per_page"] = 3,
            ["reveal_personal_emails"] = true,
            ["reveal_phone_number"] = true,
            ["person_titles"] = Array.Empty<string>()
        };

        // Use first/last name for better matching
        searchDict["q_person_name"] = name;

        // Add location filters
        if (!string.IsNullOrEmpty(city) && !string.IsNullOrEmpty(state))
            searchDict["person_locations"] = new[] { $"{city}, {state}" };
        else if (!string.IsNullOrEmpty(state))
            searchDict["person_locations"] = new[] { state };

        // Add company domain or name if available
        if (!string.IsNullOrEmpty(companyName))
            searchDict["q_organization_name"] = companyName;

        return await CallApolloEndpoint(client, apiKey, "https://api.apollo.io/v1/mixed_people/search", searchDict);
    }

    private (string? email, string? phone, string? company, string? linkedIn) ParseApolloJson(string json)
    {
        var doc = System.Text.Json.JsonDocument.Parse(json);
        var root = doc.RootElement;

        string? email = null, phone = null, company = null, linkedIn = null;

        System.Text.Json.JsonElement? person = null;
        if (root.TryGetProperty("person", out var singlePerson) && singlePerson.ValueKind == System.Text.Json.JsonValueKind.Object)
            person = singlePerson;
        else if (root.TryGetProperty("people", out var people) && people.ValueKind == System.Text.Json.JsonValueKind.Array && people.GetArrayLength() > 0)
            person = people[0];

        if (person.HasValue)
        {
            var p = person.Value;

            // Email: try email field, then personal_emails array, then revealed email
            if (p.TryGetProperty("email", out var em) && em.ValueKind == System.Text.Json.JsonValueKind.String)
                email = em.GetString();
            if (email == null && p.TryGetProperty("personal_emails", out var personalEmails) && personalEmails.ValueKind == System.Text.Json.JsonValueKind.Array && personalEmails.GetArrayLength() > 0)
                email = personalEmails[0].GetString();
            if (email == null && p.TryGetProperty("revealed_for_current_team", out var revealed) && revealed.GetBoolean())
            {
                // Check if there's a contact object with email
                if (p.TryGetProperty("contact", out var contact) && contact.TryGetProperty("email", out var cEmail))
                    email = cEmail.GetString();
            }

            // Phone: try phone_numbers array, then direct_phone, then contact.phone
            if (p.TryGetProperty("phone_numbers", out var phones) && phones.ValueKind == System.Text.Json.JsonValueKind.Array && phones.GetArrayLength() > 0)
            {
                var phoneObj = phones[0];
                if (phoneObj.ValueKind == System.Text.Json.JsonValueKind.Object)
                {
                    if (phoneObj.TryGetProperty("sanitized_number", out var num))
                        phone = num.GetString();
                    else if (phoneObj.TryGetProperty("raw_number", out var raw))
                        phone = raw.GetString();
                    else if (phoneObj.TryGetProperty("number", out var n))
                        phone = n.GetString();
                }
                else if (phoneObj.ValueKind == System.Text.Json.JsonValueKind.String)
                {
                    phone = phoneObj.GetString();
                }
            }
            if (phone == null && p.TryGetProperty("sanitized_phone", out var sPhone) && sPhone.ValueKind == System.Text.Json.JsonValueKind.String)
                phone = sPhone.GetString();

            // Company
            if (p.TryGetProperty("organization", out var org) && org.TryGetProperty("name", out var orgName))
                company = orgName.GetString();
            if (company == null && p.TryGetProperty("organization_name", out var orgN))
                company = orgN.GetString();

            // LinkedIn
            if (p.TryGetProperty("linkedin_url", out var li) && li.ValueKind == System.Text.Json.JsonValueKind.String)
                linkedIn = li.GetString();
        }

        return (email, phone, company, linkedIn);
    }
}
