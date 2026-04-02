using LeadPulse.Application.DTOs;
using LeadPulse.Application.Interfaces;
using LeadPulse.Domain.Authorization;
using LeadPulse.Domain.Entities.Tenant;
using LeadPulse.Infrastructure.Authorization;
using LeadPulse.Infrastructure.Data;
using LeadPulse.Infrastructure.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace LeadPulse.Api.Controllers;

[ApiController]
[Route("api/signals")]
[Authorize]
[HasPermission(Permissions.ViewProspects)]
public class SignalsController : ControllerBase
{
    private readonly TenantDbContext _tenantDb;
    private readonly ITenantContext _tenantContext;
    private readonly ISignalProcessor _signalProcessor;
    private readonly IntentAnalyzerFactory _analyzerFactory;
    private readonly IEncryptionService _encryptionService;

    public SignalsController(
        TenantDbContext tenantDb,
        ITenantContext tenantContext,
        ISignalProcessor signalProcessor,
        IntentAnalyzerFactory analyzerFactory,
        IEncryptionService encryptionService)
    {
        _tenantDb = tenantDb;
        _tenantContext = tenantContext;
        _signalProcessor = signalProcessor;
        _analyzerFactory = analyzerFactory;
        _encryptionService = encryptionService;
    }

    [HttpGet]
    public async Task<IActionResult> GetAll(
        [FromQuery] int page = 1,
        [FromQuery] int pageSize = 50,
        [FromQuery] string? platform = null,
        [FromQuery] bool? matched = null,
        [FromQuery] bool? analyzed = null,
        [FromQuery] string sortBy = "detectedAt",
        [FromQuery] string sortDir = "desc")
    {
        var query = _tenantDb.Signals
            .Include(s => s.KeywordMatches)
            .AsQueryable();

        if (!string.IsNullOrEmpty(platform))
            query = query.Where(s => s.Platform == platform);

        if (matched == true)
            query = query.Where(s => s.KeywordMatches.Any());
        else if (matched == false)
            query = query.Where(s => !s.KeywordMatches.Any());

        if (analyzed == true)
            query = query.Where(s => s.AnalyzedAt != null);
        else if (analyzed == false)
            query = query.Where(s => s.AnalyzedAt == null);

        var total = await query.CountAsync();

        var desc = sortDir.Equals("desc", StringComparison.OrdinalIgnoreCase);
        query = sortBy.ToLower() switch
        {
            "id" => desc ? query.OrderByDescending(s => s.Id) : query.OrderBy(s => s.Id),
            "author" or "authorname" => desc ? query.OrderByDescending(s => s.AuthorName) : query.OrderBy(s => s.AuthorName),
            "platform" => desc ? query.OrderByDescending(s => s.Platform) : query.OrderBy(s => s.Platform),
            "postdate" => desc ? query.OrderByDescending(s => s.PostDate) : query.OrderBy(s => s.PostDate),
            "intentscore" => desc ? query.OrderByDescending(s => s.IntentScore) : query.OrderBy(s => s.IntentScore),
            "intentcategory" or "category" => desc ? query.OrderByDescending(s => s.IntentCategory) : query.OrderBy(s => s.IntentCategory),
            "sentiment" => desc ? query.OrderByDescending(s => s.Sentiment) : query.OrderBy(s => s.Sentiment),
            "analyzedat" => desc ? query.OrderByDescending(s => s.AnalyzedAt) : query.OrderBy(s => s.AnalyzedAt),
            _ => desc ? query.OrderByDescending(s => s.DetectedAt) : query.OrderBy(s => s.DetectedAt),
        };

        var signals = await query
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .Select(s => new
            {
                s.Id,
                s.SocialAccountId,
                s.Platform,
                s.AuthorName,
                s.AuthorProfileUrl,
                PostContent = s.PostContent.Length > 500 ? s.PostContent.Substring(0, 500) + "..." : s.PostContent,
                FullContent = s.PostContent,
                s.PostUrl,
                s.PostDate,
                s.DetectedAt,
                MatchCount = s.KeywordMatches.Count,
                Matches = s.KeywordMatches.Select(m => new
                {
                    m.KeywordRuleId,
                    m.MatchScore,
                    m.MatchedText
                }).ToList(),
                // AI fields
                s.IntentScore,
                s.IntentCategory,
                s.Sentiment,
                s.AiSummary,
                s.AiProvider,
                s.AnalyzedAt
            })
            .ToListAsync();

        return Ok(new { total, page, pageSize, data = signals });
    }

    [HttpGet("stats")]
    public async Task<IActionResult> GetStats()
    {
        var totalSignals = await _tenantDb.Signals.CountAsync();
        var matchedSignals = await _tenantDb.Signals.CountAsync(s => s.KeywordMatches.Any());
        var unmatchedSignals = totalSignals - matchedSignals;
        var totalProspects = await _tenantDb.Prospects.CountAsync();
        var activeKeywordRules = await _tenantDb.KeywordRules.CountAsync(k => k.IsActive);
        var aiAnalyzed = await _tenantDb.Signals.CountAsync(s => s.AnalyzedAt != null);

        var platformBreakdown = await _tenantDb.Signals
            .GroupBy(s => s.Platform)
            .Select(g => new { Platform = g.Key, Count = g.Count() })
            .ToListAsync();

        return Ok(new
        {
            totalSignals,
            matchedSignals,
            unmatchedSignals,
            totalProspects,
            activeKeywordRules,
            aiAnalyzed,
            platformBreakdown
        });
    }

    [HttpPost("reprocess")]
    public async Task<IActionResult> Reprocess()
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        // Step 1: Deduplicate existing signals and merge duplicate prospects
        var (dupSignals, dupProspects) = await _signalProcessor.DeduplicateExistingAsync(_tenantContext.TenantId.Value);

        // Step 2: Fix generic author names (e.g. "Nextdoor Neighbor") on existing signals
        var fixedNames = await _signalProcessor.FixGenericAuthorNamesAsync(_tenantContext.TenantId.Value);

        // Step 3: Process signals (with built-in dedup)
        await _signalProcessor.ProcessSignalsAsync(_tenantContext.TenantId.Value);

        // Step 4: Backfill location data from Nextdoor posts to prospects
        var fixedLocations = await _signalProcessor.BackfillProspectLocationsAsync(_tenantContext.TenantId.Value);

        var matchCount = await _tenantDb.SignalKeywordMatches.CountAsync();
        var prospectCount = await _tenantDb.Prospects.CountAsync();

        return Ok(new
        {
            message = "Signal reprocessing complete",
            keywordMatches = matchCount,
            prospects = prospectCount,
            authorNamesFixed = fixedNames,
            locationsFixed = fixedLocations,
            duplicateSignalsRemoved = dupSignals,
            duplicateProspectsMerged = dupProspects
        });
    }

    [HttpPost("deduplicate")]
    public async Task<IActionResult> Deduplicate()
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var (dupSignals, dupProspects) = await _signalProcessor.DeduplicateExistingAsync(_tenantContext.TenantId.Value);

        return Ok(new
        {
            message = "Deduplication complete",
            duplicateSignalsRemoved = dupSignals,
            duplicateProspectsMerged = dupProspects
        });
    }

    [HttpPost("{id}/analyze")]
    public async Task<IActionResult> AnalyzeSingle(long id)
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var signal = await _tenantDb.Signals.FindAsync(id);
        if (signal == null)
            return NotFound(new { error = "Signal not found" });

        var settings = await _tenantDb.AiSettings.FirstOrDefaultAsync();

        IntentAnalysisResult result;
        try
        {
            var analyzer = _analyzerFactory.Create(settings, _tenantContext.TenantId.Value);
            result = await analyzer.AnalyzeAsync(signal.PostContent, signal.Platform);
        }
        catch (HttpRequestException ex)
        {
            return BadRequest(new { error = ex.Message });
        }
        catch (InvalidOperationException ex)
        {
            return BadRequest(new { error = ex.Message });
        }

        signal.IntentScore = result.IntentScore;
        signal.IntentCategory = result.IntentCategory;
        signal.Sentiment = result.Sentiment;
        signal.AiSummary = result.Summary;
        signal.AiProvider = settings?.AiProvider ?? "Local";
        signal.AnalyzedAt = DateTime.UtcNow;

        // Propagate phone/email to linked prospect if AI found them
        if (!string.IsNullOrEmpty(result.Phone) || !string.IsNullOrEmpty(result.Email))
        {
            var prospectSignal = await _tenantDb.ProspectSignals
                .Include(ps => ps.Prospect)
                .FirstOrDefaultAsync(ps => ps.SignalId == signal.Id);

            if (prospectSignal?.Prospect != null)
            {
                if (!string.IsNullOrEmpty(result.Phone) && string.IsNullOrEmpty(prospectSignal.Prospect.Phone))
                    prospectSignal.Prospect.Phone = result.Phone;
                if (!string.IsNullOrEmpty(result.Email) && string.IsNullOrEmpty(prospectSignal.Prospect.Email))
                    prospectSignal.Prospect.Email = result.Email;
                prospectSignal.Prospect.UpdatedAt = DateTime.UtcNow;
            }
        }

        await _tenantDb.SaveChangesAsync();

        return Ok(new
        {
            signal.Id,
            signal.IntentScore,
            signal.IntentCategory,
            signal.Sentiment,
            signal.AiSummary,
            signal.AiProvider,
            signal.AnalyzedAt,
            result.Phone,
            result.Email
        });
    }

    [HttpPost("analyze-all")]
    public async Task<IActionResult> AnalyzeAll()
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var settings = await _tenantDb.AiSettings.FirstOrDefaultAsync();
        var analyzer = _analyzerFactory.Create(settings, _tenantContext.TenantId.Value);
        var providerName = settings?.AiProvider ?? "Local";

        var unanalyzed = await _tenantDb.Signals
            .Where(s => s.AnalyzedAt == null)
            .Take(500)
            .ToListAsync();

        // Pre-load signal-to-prospect mappings for phone/email propagation
        var signalIds = unanalyzed.Select(s => s.Id).ToList();
        var prospectSignals = await _tenantDb.ProspectSignals
            .Include(ps => ps.Prospect)
            .Where(ps => signalIds.Contains(ps.SignalId))
            .ToListAsync();
        var signalProspectMap = prospectSignals
            .GroupBy(ps => ps.SignalId)
            .ToDictionary(g => g.Key, g => g.First().Prospect);

        int analyzed = 0;
        foreach (var signal in unanalyzed)
        {
            try
            {
                var result = await analyzer.AnalyzeAsync(signal.PostContent, signal.Platform);
                signal.IntentScore = result.IntentScore;
                signal.IntentCategory = result.IntentCategory;
                signal.Sentiment = result.Sentiment;
                signal.AiSummary = result.Summary;
                signal.AiProvider = providerName;
                signal.AnalyzedAt = DateTime.UtcNow;
                analyzed++;

                // Propagate phone/email to linked prospect
                if ((!string.IsNullOrEmpty(result.Phone) || !string.IsNullOrEmpty(result.Email))
                    && signalProspectMap.TryGetValue(signal.Id, out var prospect))
                {
                    if (!string.IsNullOrEmpty(result.Phone) && string.IsNullOrEmpty(prospect.Phone))
                        prospect.Phone = result.Phone;
                    if (!string.IsNullOrEmpty(result.Email) && string.IsNullOrEmpty(prospect.Email))
                        prospect.Email = result.Email;
                    prospect.UpdatedAt = DateTime.UtcNow;
                }
            }
            catch
            {
                // Skip failed signals, continue with rest
            }
        }

        await _tenantDb.SaveChangesAsync();

        return Ok(new
        {
            message = $"AI analysis complete — {analyzed} signals analyzed",
            analyzed,
            total = unanalyzed.Count,
            provider = providerName
        });
    }

    [HttpGet("ai-settings")]
    public async Task<IActionResult> GetAiSettings()
    {
        var settings = await _tenantDb.AiSettings.FirstOrDefaultAsync();

        return Ok(new AiSettingsResponse
        {
            AiProvider = settings?.AiProvider ?? "Local",
            HasApiKey = !string.IsNullOrEmpty(settings?.EncryptedApiKey),
            AiModel = settings?.AiModel,
            UpdatedAt = settings?.UpdatedAt
        });
    }

    [HttpPut("ai-settings")]
    public async Task<IActionResult> UpdateAiSettings([FromBody] AiSettingsRequest request)
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var settings = await _tenantDb.AiSettings.FirstOrDefaultAsync();
        if (settings == null)
        {
            settings = new AiSettings();
            _tenantDb.AiSettings.Add(settings);
        }

        settings.AiProvider = request.AiProvider;
        settings.AiModel = request.AiModel;
        settings.UpdatedAt = DateTime.UtcNow;

        if (!string.IsNullOrEmpty(request.ApiKey))
        {
            settings.EncryptedApiKey = _encryptionService.Encrypt(request.ApiKey, _tenantContext.TenantId.Value);
        }

        await _tenantDb.SaveChangesAsync();

        return Ok(new AiSettingsResponse
        {
            AiProvider = settings.AiProvider,
            HasApiKey = !string.IsNullOrEmpty(settings.EncryptedApiKey),
            AiModel = settings.AiModel,
            UpdatedAt = settings.UpdatedAt
        });
    }

    [HttpPost("ai-settings/test")]
    public async Task<IActionResult> TestAiKey()
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var settings = await _tenantDb.AiSettings.FirstOrDefaultAsync();
        if (settings == null || string.IsNullOrEmpty(settings.EncryptedApiKey))
            return BadRequest(new { success = false, error = "No API key configured. Save your settings first." });

        try
        {
            var analyzer = _analyzerFactory.Create(settings, _tenantContext.TenantId.Value);
            var result = await analyzer.AnalyzeAsync("I just had a fender bender and need to file a claim on my auto insurance.", "Test");
            return Ok(new { success = true, message = $"Key is valid. Test analysis returned: {result.IntentCategory} (score: {result.IntentScore})" });
        }
        catch (HttpRequestException ex)
        {
            return Ok(new { success = false, error = $"{ex.Message}" });
        }
        catch (InvalidOperationException ex)
        {
            return Ok(new { success = false, error = ex.Message });
        }
        catch (Exception ex)
        {
            return Ok(new { success = false, error = $"Test failed: {ex.Message}" });
        }
    }
}
