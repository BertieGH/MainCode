using System.Collections.Concurrent;
using System.Text.Json;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace LeadPulse.Api.Controllers;

[ApiController]
[Route("api/geo")]
[Authorize]
public class GeoController : ControllerBase
{
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly ILogger<GeoController> _logger;

    private static readonly ConcurrentDictionary<string, List<string>> _countyZipCache = new();
    private static readonly ConcurrentDictionary<string, List<string>> _stateCountyCache = new();
    private static readonly SemaphoreSlim _loadLock = new(1, 1);
    private static bool _dataLoaded;

    public GeoController(IHttpClientFactory httpClientFactory, ILogger<GeoController> logger)
    {
        _httpClientFactory = httpClientFactory;
        _logger = logger;
    }

    [HttpGet("counties")]
    public async Task<IActionResult> GetCounties([FromQuery] string state)
    {
        if (string.IsNullOrEmpty(state)) return BadRequest(new { error = "state is required" });

        await EnsureDataLoaded();

        var key = state.ToUpper();
        if (_stateCountyCache.TryGetValue(key, out var counties))
            return Ok(counties);

        return Ok(Array.Empty<string>());
    }

    [HttpGet("zips")]
    public async Task<IActionResult> GetZipsForCounty([FromQuery] string state, [FromQuery] string county)
    {
        if (string.IsNullOrEmpty(state) || string.IsNullOrEmpty(county))
            return BadRequest(new { error = "state and county are required" });

        await EnsureDataLoaded();

        var key = $"{state.ToUpper()}:{county.ToLower().Trim()}";
        if (_countyZipCache.TryGetValue(key, out var zips))
            return Ok(zips);

        // Partial match
        var prefix = $"{state.ToUpper()}:";
        var countyLower = county.ToLower().Trim();
        var match = _countyZipCache.Keys
            .Where(k => k.StartsWith(prefix))
            .Where(k =>
            {
                var cname = k.Substring(prefix.Length);
                return cname.Contains(countyLower) || countyLower.Contains(cname);
            })
            .OrderByDescending(k => k.Length)
            .FirstOrDefault();

        if (match != null && _countyZipCache.TryGetValue(match, out zips))
            return Ok(zips);

        return Ok(Array.Empty<string>());
    }

    private async Task EnsureDataLoaded()
    {
        if (_dataLoaded) return;

        await _loadLock.WaitAsync();
        try
        {
            if (_dataLoaded) return;

            _logger.LogInformation("Loading US zip-county data...");

            using var handler = new HttpClientHandler
            {
                ServerCertificateCustomValidationCallback = (_, _, _, _) => true
            };
            using var client = new HttpClient(handler);
            client.Timeout = TimeSpan.FromSeconds(30);

            // Community-maintained US state-county-zip CSV
            var url = "https://raw.githubusercontent.com/scpike/us-state-county-zip/master/geo-data.csv";

            try
            {
                var csv = await client.GetStringAsync(url);
                ParseCsvData(csv);
                _logger.LogInformation("Loaded {ZipMappings} county-zip mappings, {Counties} state-county mappings",
                    _countyZipCache.Count, _stateCountyCache.Count);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to load zip-county data");

                // Fallback: check for local file
                var localPath = Path.Combine(AppContext.BaseDirectory, "Data", "geo-data.csv");
                if (System.IO.File.Exists(localPath))
                {
                    var csv = await System.IO.File.ReadAllTextAsync(localPath);
                    ParseCsvData(csv);
                    _logger.LogInformation("Loaded {Count} county-zip mappings from local file", _countyZipCache.Count);
                }
            }

            _dataLoaded = true;
        }
        finally
        {
            _loadLock.Release();
        }
    }

    private void ParseCsvData(string csv)
    {
        // Format: state_fips,state,state_abbr,zipcode,county,city
        var lines = csv.Split('\n');
        var countyZips = new Dictionary<string, HashSet<string>>();
        var stateCounties = new Dictionary<string, HashSet<string>>();

        for (int i = 1; i < lines.Length; i++)
        {
            var line = lines[i].Trim();
            if (string.IsNullOrEmpty(line)) continue;

            var cols = line.Split(',');
            if (cols.Length < 5) continue;

            var stateAbbr = cols[2].Trim().ToUpper();
            var zip = cols[3].Trim();
            var county = cols[4].Trim();

            if (string.IsNullOrEmpty(stateAbbr) || string.IsNullOrEmpty(zip) || string.IsNullOrEmpty(county))
                continue;

            // Skip non-numeric zip codes (Census group codes like "770HH", "945XX")
            if (!zip.All(char.IsDigit))
                continue;

            // County-zip mapping
            var czKey = $"{stateAbbr}:{county.ToLower()}";
            if (!countyZips.ContainsKey(czKey))
                countyZips[czKey] = new HashSet<string>();
            countyZips[czKey].Add(zip);

            // State-county mapping
            if (!stateCounties.ContainsKey(stateAbbr))
                stateCounties[stateAbbr] = new HashSet<string>();
            stateCounties[stateAbbr].Add(county);
        }

        foreach (var kvp in countyZips)
            _countyZipCache[kvp.Key] = kvp.Value.OrderBy(z => z).ToList();

        foreach (var kvp in stateCounties)
            _stateCountyCache[kvp.Key] = kvp.Value.OrderBy(c => c).ToList();
    }
}
