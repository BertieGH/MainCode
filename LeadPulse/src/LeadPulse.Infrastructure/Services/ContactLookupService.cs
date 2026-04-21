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
        var enrichmentProviders = new[] { "Apollo", "ContactOut", "PeopleDataLabs" };
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
                    "PeopleDataLabs" => await LookupPeopleDataLabs(apiKey, prospectName, city, state, company, linkedInUrl, existingEmail),
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
                    var response = await client.GetAsync("https://api.apollo.io/api/v1/auth/health");
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
            else if (provider == "PeopleDataLabs")
            {
                if (!string.IsNullOrEmpty(apiKey))
                {
                    // Test with a minimal query to validate the API key
                    client.DefaultRequestHeaders.Add("X-Api-Key", apiKey);
                    var response = await client.GetAsync("https://api.peopledatalabs.com/v5/person/enrich?name=test&min_likelihood=10");
                    var body = await response.Content.ReadAsStringAsync();
                    _logger.LogInformation("PDL test returned {Status}: {Body}", response.StatusCode, body.Length > 200 ? body[..200] : body);
                    // 404/422/400 means key works but no match or bad params (expected for "test")
                    if (response.IsSuccessStatusCode ||
                        response.StatusCode == System.Net.HttpStatusCode.NotFound ||
                        response.StatusCode == System.Net.HttpStatusCode.BadRequest ||
                        response.StatusCode == System.Net.HttpStatusCode.UnprocessableEntity)
                        return new ContactLookupResult { Success = true, Provider = provider };
                    if (response.StatusCode == System.Net.HttpStatusCode.Unauthorized || response.StatusCode == System.Net.HttpStatusCode.Forbidden)
                        return new ContactLookupResult { Success = false, Error = "People Data Labs API key is invalid.", Provider = provider };
                    return new ContactLookupResult { Success = false, Error = $"People Data Labs returned {response.StatusCode}", Provider = provider };
                }
                return new ContactLookupResult { Success = false, Error = "People Data Labs requires an API key.", Provider = provider };
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

        // Strategy 1: LinkedIn URL (highest accuracy)
        if (!string.IsNullOrEmpty(linkedInUrl))
        {
            _logger.LogInformation("Apollo Strategy 1: match by LinkedIn URL for {Name}", name);
            var qp = new Dictionary<string, string>
            {
                ["linkedin_url"] = linkedInUrl,
                ["reveal_personal_emails"] = "true"
            };
            var (email, phone, company, linkedIn) = await CallApolloMatch(client, apiKey, qp);
            if (email != null || phone != null)
                return new ContactLookupResult { Success = true, Email = email, Phone = phone, Company = company, LinkedInUrl = linkedIn ?? linkedInUrl, Provider = "Apollo" };
        }

        // Strategy 2: Email (second strongest identifier)
        if (!string.IsNullOrEmpty(existingEmail) && !existingEmail.Contains("@example.com"))
        {
            _logger.LogInformation("Apollo Strategy 2: match by email for {Name}", name);
            var qp = new Dictionary<string, string>
            {
                ["email"] = existingEmail,
                ["reveal_personal_emails"] = "true"
            };
            var (email, phone, company, linkedIn) = await CallApolloMatch(client, apiKey, qp);
            if (email != null || phone != null)
                return new ContactLookupResult { Success = true, Email = email, Phone = phone, Company = company, LinkedInUrl = linkedIn, Provider = "Apollo" };
        }

        // Strategy 3: Name + company + domain
        {
            _logger.LogInformation("Apollo Strategy 3: match by name + org for {Name}", name);
            var qp = new Dictionary<string, string>
            {
                ["first_name"] = firstName,
                ["last_name"] = lastName,
                ["reveal_personal_emails"] = "true"
            };
            if (!string.IsNullOrEmpty(companyName))
                qp["organization_name"] = companyName;
            var (email, phone, company, linkedIn) = await CallApolloMatch(client, apiKey, qp);
            if (email != null || phone != null)
                return new ContactLookupResult { Success = true, Email = email, Phone = phone, Company = company, LinkedInUrl = linkedIn, Provider = "Apollo" };
        }

        // Strategy 4: Just name (broadest match)
        if (!string.IsNullOrEmpty(companyName))
        {
            _logger.LogInformation("Apollo Strategy 4: match by name only for {Name}", name);
            var qp = new Dictionary<string, string>
            {
                ["first_name"] = firstName,
                ["last_name"] = lastName,
                ["reveal_personal_emails"] = "true"
            };
            var (email, phone, company, linkedIn) = await CallApolloMatch(client, apiKey, qp);
            if (email != null || phone != null)
                return new ContactLookupResult { Success = true, Email = email, Phone = phone, Company = company, LinkedInUrl = linkedIn, Provider = "Apollo" };
        }

        return new ContactLookupResult { Success = false, Error = "Apollo found no contact data for this prospect across all strategies", Provider = "Apollo" };
    }

    /// <summary>
    /// Calls Apollo /api/v1/people/match with parameters as QUERY PARAMS (per Apollo docs).
    /// </summary>
    private async Task<(string? email, string? phone, string? company, string? linkedIn)> CallApolloMatch(
        HttpClient client, string apiKey, Dictionary<string, string> queryParams)
    {
        // Build URL with query parameters (Apollo docs: all params are query params for people/match)
        var queryString = string.Join("&", queryParams.Select(kvp =>
            $"{Uri.EscapeDataString(kvp.Key)}={Uri.EscapeDataString(kvp.Value)}"));
        var url = $"https://api.apollo.io/api/v1/people/match?{queryString}";

        var req = new HttpRequestMessage(HttpMethod.Post, url);
        req.Headers.Add("X-Api-Key", apiKey);
        req.Content = new StringContent("{}", System.Text.Encoding.UTF8, "application/json");

        _logger.LogInformation("Apollo match request: {Url}", url.Replace(apiKey, "***"));

        var response = await client.SendAsync(req);

        if (!response.IsSuccessStatusCode)
        {
            var errorBody = await response.Content.ReadAsStringAsync();
            _logger.LogWarning("Apollo match returned {Status}: {Body}", response.StatusCode, errorBody.Length > 500 ? errorBody[..500] : errorBody);
            return (null, null, null, null);
        }

        var json = await response.Content.ReadAsStringAsync();
        _logger.LogInformation("Apollo match response ({Len} chars): {Json}", json.Length, json.Length > 800 ? json[..800] : json);

        return ParseApolloJson(json);
    }

    private (string? email, string? phone, string? company, string? linkedIn) ParseApolloJson(string json)
    {
        var doc = System.Text.Json.JsonDocument.Parse(json);
        var root = doc.RootElement;

        // Find the person element — match returns {person:{}}, search returns {people:[]}
        System.Text.Json.JsonElement? person = null;
        if (root.TryGetProperty("person", out var singlePerson) && singlePerson.ValueKind == System.Text.Json.JsonValueKind.Object)
            person = singlePerson;
        else if (root.TryGetProperty("people", out var people) && people.ValueKind == System.Text.Json.JsonValueKind.Array && people.GetArrayLength() > 0)
            person = people[0];

        if (!person.HasValue) return (null, null, null, null);
        return ExtractApolloPersonData(person.Value);
    }

    private (string? email, string? phone, string? company, string? linkedIn) ExtractApolloPersonData(System.Text.Json.JsonElement p)
    {
        string? email = null, phone = null, company = null, linkedIn = null;

        // Email: work email > personal_emails > revealed email
        if (p.TryGetProperty("email", out var em) && em.ValueKind == System.Text.Json.JsonValueKind.String)
            email = em.GetString();
        if (email == null && p.TryGetProperty("personal_emails", out var personalEmails) && personalEmails.ValueKind == System.Text.Json.JsonValueKind.Array && personalEmails.GetArrayLength() > 0)
            email = personalEmails[0].GetString();
        if (email == null && p.TryGetProperty("contact_emails", out var contactEmails) && contactEmails.ValueKind == System.Text.Json.JsonValueKind.Array && contactEmails.GetArrayLength() > 0)
            email = contactEmails[0].GetString();

        // Phone: phone_numbers array > sanitized_phone > direct fields
        if (p.TryGetProperty("phone_numbers", out var phones) && phones.ValueKind == System.Text.Json.JsonValueKind.Array && phones.GetArrayLength() > 0)
        {
            var phoneObj = phones[0];
            if (phoneObj.ValueKind == System.Text.Json.JsonValueKind.Object)
            {
                phone = phoneObj.TryGetProperty("sanitized_number", out var sn) ? sn.GetString() : null;
                phone ??= phoneObj.TryGetProperty("raw_number", out var rn) ? rn.GetString() : null;
                phone ??= phoneObj.TryGetProperty("number", out var n) ? n.GetString() : null;
            }
            else if (phoneObj.ValueKind == System.Text.Json.JsonValueKind.String)
                phone = phoneObj.GetString();
        }
        if (phone == null && p.TryGetProperty("sanitized_phone", out var sPhone) && sPhone.ValueKind == System.Text.Json.JsonValueKind.String)
            phone = sPhone.GetString();
        if (phone == null && p.TryGetProperty("phone", out var directPhone) && directPhone.ValueKind == System.Text.Json.JsonValueKind.String)
            phone = directPhone.GetString();

        // Company
        if (p.TryGetProperty("organization", out var org) && org.TryGetProperty("name", out var orgName))
            company = orgName.GetString();
        if (company == null && p.TryGetProperty("organization_name", out var orgN))
            company = orgN.GetString();

        // LinkedIn
        if (p.TryGetProperty("linkedin_url", out var li) && li.ValueKind == System.Text.Json.JsonValueKind.String)
            linkedIn = li.GetString();

        return (email, phone, company, linkedIn);
    }

    // === People Data Labs ===

    private async Task<ContactLookupResult> LookupPeopleDataLabs(string? apiKey, string name, string? city, string? state, string? company, string? linkedInUrl, string? existingEmail)
    {
        if (string.IsNullOrEmpty(apiKey))
            return new ContactLookupResult { Success = false, Error = "People Data Labs API key is required. Add it in Account Config > Contact Data Config.", Provider = "PeopleDataLabs" };

        var client = _httpClientFactory.CreateClient();
        client.DefaultRequestHeaders.Add("X-Api-Key", apiKey);

        // Build query params per PDL docs:
        // Required: (first_name AND last_name OR name) AND (locality OR region OR company OR location)
        var qp = new List<string> { $"name={Uri.EscapeDataString(name)}", "titlecase=true" };

        if (!string.IsNullOrEmpty(city))
            qp.Add($"locality={Uri.EscapeDataString(city)}");
        if (!string.IsNullOrEmpty(state))
            qp.Add($"region={Uri.EscapeDataString(state)}");
        if (!string.IsNullOrEmpty(company))
            qp.Add($"company={Uri.EscapeDataString(company)}");
        if (!string.IsNullOrEmpty(linkedInUrl))
            qp.Add($"profile={Uri.EscapeDataString(linkedInUrl)}");
        if (!string.IsNullOrEmpty(existingEmail) && !existingEmail.Contains("@example.com"))
            qp.Add($"email={Uri.EscapeDataString(existingEmail)}");

        // min_likelihood=5 to avoid weak matches
        qp.Add("min_likelihood=5");

        var url = $"https://api.peopledatalabs.com/v5/person/enrich?{string.Join("&", qp)}";
        _logger.LogInformation("PDL enrich request: {Url}", url);

        try
        {
            var response = await client.GetAsync(url);
            var json = await response.Content.ReadAsStringAsync();
            _logger.LogInformation("PDL response {Status} ({Len} chars): {Json}", response.StatusCode, json.Length, json.Length > 800 ? json[..800] : json);

            // 404 = no match found
            if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
                return new ContactLookupResult { Success = false, Error = "People Data Labs found no match for this person", Provider = "PeopleDataLabs" };

            if (!response.IsSuccessStatusCode)
                return new ContactLookupResult { Success = false, Error = $"People Data Labs API error: {response.StatusCode}", Provider = "PeopleDataLabs" };

            var doc = System.Text.Json.JsonDocument.Parse(json);
            var root = doc.RootElement;

            string? email = null, phone = null, companyResult = null, linkedIn = null;

            if (root.TryGetProperty("data", out var data))
            {
                // NOTE: PDL free/standard tier returns boolean true/false for email/phone fields
                // to indicate data EXISTS but is not revealed. Only paid credits return actual values.
                // We must check ValueKind to avoid treating "true" as actual data.

                // Emails: work_email, personal_emails array, or recommended_personal_email
                if (data.TryGetProperty("work_email", out var workEmail) && workEmail.ValueKind == System.Text.Json.JsonValueKind.String)
                    email = workEmail.GetString();

                if (email == null && data.TryGetProperty("recommended_personal_email", out var recEmail) && recEmail.ValueKind == System.Text.Json.JsonValueKind.String)
                    email = recEmail.GetString();

                if (email == null && data.TryGetProperty("personal_emails", out var pEmails) && pEmails.ValueKind == System.Text.Json.JsonValueKind.Array && pEmails.GetArrayLength() > 0)
                {
                    var firstEmail = pEmails[0];
                    if (firstEmail.ValueKind == System.Text.Json.JsonValueKind.String)
                        email = firstEmail.GetString();
                }

                if (email == null && data.TryGetProperty("emails", out var emails) && emails.ValueKind == System.Text.Json.JsonValueKind.Array)
                {
                    foreach (var em in emails.EnumerateArray())
                    {
                        var addr = em.TryGetProperty("address", out var a) ? a.GetString() : null;
                        if (!string.IsNullOrEmpty(addr)) { email = addr; break; }
                    }
                }

                // Phone: mobile_phone, phone_numbers array
                if (data.TryGetProperty("mobile_phone", out var mobile) && mobile.ValueKind == System.Text.Json.JsonValueKind.String)
                    phone = mobile.GetString();

                if (phone == null && data.TryGetProperty("phone_numbers", out var phones) && phones.ValueKind == System.Text.Json.JsonValueKind.Array && phones.GetArrayLength() > 0)
                {
                    var firstPhone = phones[0];
                    if (firstPhone.ValueKind == System.Text.Json.JsonValueKind.String)
                        phone = firstPhone.GetString();
                }

                // Track what PDL says exists but won't reveal (boolean true fields)
                bool emailExists = email == null && (
                    (data.TryGetProperty("work_email", out var we2) && we2.ValueKind == System.Text.Json.JsonValueKind.True) ||
                    (data.TryGetProperty("recommended_personal_email", out var rpe2) && rpe2.ValueKind == System.Text.Json.JsonValueKind.True) ||
                    (data.TryGetProperty("personal_emails", out var pe2) && pe2.ValueKind == System.Text.Json.JsonValueKind.True));
                bool phoneExists = phone == null && (
                    (data.TryGetProperty("mobile_phone", out var mp2) && mp2.ValueKind == System.Text.Json.JsonValueKind.True));

                // Company: job_company_name
                if (data.TryGetProperty("job_company_name", out var jcn) && jcn.ValueKind == System.Text.Json.JsonValueKind.String)
                    companyResult = jcn.GetString();

                // LinkedIn
                if (data.TryGetProperty("linkedin_url", out var li) && li.ValueKind == System.Text.Json.JsonValueKind.String)
                    linkedIn = li.GetString();
                if (linkedIn == null && data.TryGetProperty("linkedin_username", out var liUser) && liUser.ValueKind == System.Text.Json.JsonValueKind.String)
                {
                    var username = liUser.GetString();
                    if (!string.IsNullOrEmpty(username))
                        linkedIn = $"https://www.linkedin.com/in/{username}";
                }

                // Also check profiles array for linkedin
                if (linkedIn == null && data.TryGetProperty("profiles", out var profiles) && profiles.ValueKind == System.Text.Json.JsonValueKind.Array)
                {
                    foreach (var prof in profiles.EnumerateArray())
                    {
                        var network = prof.TryGetProperty("network", out var n) ? n.GetString() : null;
                        var profUrl = prof.TryGetProperty("url", out var u) ? u.GetString() : null;
                        if (network == "linkedin" && !string.IsNullOrEmpty(profUrl)) { linkedIn = profUrl; break; }
                    }
                }

                // If PDL matched but only returned booleans (no actual data), report clearly
                if (email == null && phone == null && (emailExists || phoneExists))
                {
                    var hint = "PDL found a match and data exists";
                    if (emailExists) hint += " (email available)";
                    if (phoneExists) hint += " (phone available)";
                    hint += " — but your PDL plan does not include credits to reveal it. Upgrade at peopledatalabs.com to get actual contact data.";
                    // Still return LinkedIn/company if we got them
                    if (linkedIn != null || companyResult != null)
                        return new ContactLookupResult { Success = true, Email = null, Phone = null, Company = companyResult, LinkedInUrl = linkedIn, Provider = "PeopleDataLabs", Error = hint };
                    return new ContactLookupResult { Success = false, Error = hint, Provider = "PeopleDataLabs" };
                }
            }

            if (email == null && phone == null)
                return new ContactLookupResult { Success = false, Error = "People Data Labs matched but returned no contact data", Provider = "PeopleDataLabs" };

            return new ContactLookupResult { Success = true, Email = email, Phone = phone, Company = companyResult, LinkedInUrl = linkedIn, Provider = "PeopleDataLabs" };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "People Data Labs lookup failed");
            return new ContactLookupResult { Success = false, Error = $"PDL error: {ex.Message}", Provider = "PeopleDataLabs" };
        }
    }
}
