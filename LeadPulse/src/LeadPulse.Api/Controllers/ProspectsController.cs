using System.Text;
using LeadPulse.Application.DTOs;
using LeadPulse.Application.Interfaces;
using LeadPulse.Domain.Authorization;
using LeadPulse.Domain.Entities.Tenant;
using LeadPulse.Domain.Enums;
using LeadPulse.Infrastructure.Authorization;
using LeadPulse.Infrastructure.Data;
using LeadPulse.Infrastructure.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace LeadPulse.Api.Controllers;

[ApiController]
[Route("api/prospects")]
[Authorize]
[HasPermission(Permissions.ViewProspects)]
public class ProspectsController : ControllerBase
{
    private readonly TenantDbContext _tenantDb;
    private readonly ITenantContext _tenantContext;
    private readonly IEncryptionService _encryptionService;
    private readonly ContactLookupService _contactLookupService;
    private readonly LinkedInSearchService _linkedInSearchService;
    private readonly LinkedInScraperService _linkedInScraperService;
    private readonly ISignalProcessor _signalProcessor;
    private readonly IntentAnalyzerFactory _analyzerFactory;

    public ProspectsController(
        TenantDbContext tenantDb,
        ITenantContext tenantContext,
        IEncryptionService encryptionService,
        ContactLookupService contactLookupService,
        LinkedInSearchService linkedInSearchService,
        LinkedInScraperService linkedInScraperService,
        ISignalProcessor signalProcessor,
        IntentAnalyzerFactory analyzerFactory)
    {
        _tenantDb = tenantDb;
        _tenantContext = tenantContext;
        _encryptionService = encryptionService;
        _contactLookupService = contactLookupService;
        _linkedInSearchService = linkedInSearchService;
        _linkedInScraperService = linkedInScraperService;
        _signalProcessor = signalProcessor;
        _analyzerFactory = analyzerFactory;
    }

    [HttpGet]
    public async Task<IActionResult> GetAll([FromQuery] ProspectFilterRequest filter)
    {
        var query = _tenantDb.Prospects.AsQueryable();

        // Apply filters
        if (!string.IsNullOrEmpty(filter.Search))
            query = query.Where(p => p.Name.Contains(filter.Search) || (p.Company != null && p.Company.Contains(filter.Search)) || (p.Email != null && p.Email.Contains(filter.Search)));
        if (!string.IsNullOrEmpty(filter.Category))
            query = query.Where(p => p.Category == filter.Category);
        if (!string.IsNullOrEmpty(filter.Urgency) && Enum.TryParse<Urgency>(filter.Urgency, true, out var urgency))
            query = query.Where(p => p.Urgency == urgency);
        if (filter.MinScore.HasValue)
            query = query.Where(p => p.CompositeScore >= filter.MinScore.Value);
        if (filter.MaxScore.HasValue)
            query = query.Where(p => p.CompositeScore <= filter.MaxScore.Value);
        if (!string.IsNullOrEmpty(filter.Platform))
            query = query.Where(p => p.Platform == filter.Platform);
        if (!string.IsNullOrEmpty(filter.City))
            query = query.Where(p => p.City == filter.City);
        if (!string.IsNullOrEmpty(filter.State))
            query = query.Where(p => p.State == filter.State);
        if (!string.IsNullOrEmpty(filter.Zip))
            query = query.Where(p => p.Zip == filter.Zip);
        if (!string.IsNullOrEmpty(filter.Status) && Enum.TryParse<ProspectStatus>(filter.Status, true, out var status))
            query = query.Where(p => p.Status == status);
        if (filter.DateFrom.HasValue)
            query = query.Where(p => p.CreatedAt >= filter.DateFrom.Value);
        if (filter.DateTo.HasValue)
            query = query.Where(p => p.CreatedAt <= filter.DateTo.Value);

        var totalCount = await query.CountAsync();

        // Sorting
        query = filter.SortBy?.ToLowerInvariant() switch
        {
            "score" => filter.SortDesc ? query.OrderByDescending(p => p.CompositeScore) : query.OrderBy(p => p.CompositeScore),
            "intentscore" => filter.SortDesc
                ? query.OrderByDescending(p => p.ProspectSignals.Max(ps => ps.Signal!.IntentScore))
                : query.OrderBy(p => p.ProspectSignals.Max(ps => ps.Signal!.IntentScore)),
            "urgency" => filter.SortDesc ? query.OrderByDescending(p => p.Urgency) : query.OrderBy(p => p.Urgency),
            "name" => filter.SortDesc ? query.OrderByDescending(p => p.Name) : query.OrderBy(p => p.Name),
            "date" => filter.SortDesc ? query.OrderByDescending(p => p.CreatedAt) : query.OrderBy(p => p.CreatedAt),
            "intentcategory" => filter.SortDesc
                ? query.OrderByDescending(p => p.ProspectSignals.Select(ps => ps.Signal!.IntentCategory).FirstOrDefault())
                : query.OrderBy(p => p.ProspectSignals.Select(ps => ps.Signal!.IntentCategory).FirstOrDefault()),
            "sentiment" => filter.SortDesc
                ? query.OrderByDescending(p => p.ProspectSignals.Select(ps => ps.Signal!.Sentiment).FirstOrDefault())
                : query.OrderBy(p => p.ProspectSignals.Select(ps => ps.Signal!.Sentiment).FirstOrDefault()),
            "city" => filter.SortDesc ? query.OrderByDescending(p => p.City) : query.OrderBy(p => p.City),
            "postdate" => filter.SortDesc
                ? query.OrderByDescending(p => p.ProspectSignals.Select(ps => ps.Signal!.PostDate).FirstOrDefault())
                : query.OrderBy(p => p.ProspectSignals.Select(ps => ps.Signal!.PostDate).FirstOrDefault()),
            _ => query.OrderByDescending(p => p.CompositeScore)
        };

        // Pagination
        var page = Math.Max(1, filter.Page);
        var pageSize = Math.Clamp(filter.PageSize, 1, 100);
        var items = await query
            .Include(p => p.ProspectSignals)
                .ThenInclude(ps => ps.Signal)
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .ToListAsync();

        return Ok(new ProspectListResponse
        {
            Items = items.Select(MapToResponse).ToList(),
            TotalCount = totalCount,
            Page = page,
            PageSize = pageSize,
            TotalPages = (int)Math.Ceiling((double)totalCount / pageSize)
        });
    }

    [HttpPost("enrichment-settings/test")]
    public async Task<IActionResult> TestConnection([FromBody] TestConnectionRequest request)
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var result = await _contactLookupService.TestConnectionAsync(_tenantContext.TenantId.Value, request.Provider);
        var message = result.Success ? $"{request.Provider} connection successful" : null;
        var warning = result.Success && !string.IsNullOrEmpty(result.Error) ? result.Error : null;
        return Ok(new { success = result.Success, message, warning, error = result.Success ? null : result.Error, provider = result.Provider });
    }

    [HttpGet("{id:int}")]
    public async Task<IActionResult> GetById(int id)
    {
        var prospect = await _tenantDb.Prospects
            .Include(p => p.ProspectSignals)
                .ThenInclude(ps => ps.Signal)
            .Include(p => p.CallLogs)
            .FirstOrDefaultAsync(p => p.Id == id);

        if (prospect == null) return NotFound();
        return Ok(MapToResponse(prospect));
    }

    [HttpPut("{id:int}/status")]
    public async Task<IActionResult> UpdateStatus(int id, [FromBody] UpdateProspectStatusRequest request)
    {
        var prospect = await _tenantDb.Prospects.FindAsync(id);
        if (prospect == null) return NotFound();

        if (!Enum.TryParse<ProspectStatus>(request.Status, true, out var newStatus))
            return BadRequest(new { error = $"Invalid status: {request.Status}" });

        prospect.Status = newStatus;
        prospect.UpdatedAt = DateTime.UtcNow;
        await _tenantDb.SaveChangesAsync();

        return Ok(MapToResponse(prospect));
    }

    [HttpPut("{id:int}/enrich")]
    public async Task<IActionResult> Enrich(int id, [FromBody] EnrichProspectRequest request)
    {
        var prospect = await _tenantDb.Prospects.FindAsync(id);
        if (prospect == null) return NotFound();

        if (request.Phone != null) prospect.Phone = request.Phone;
        if (request.Email != null) prospect.Email = request.Email;
        if (request.Address != null) prospect.Address = request.Address;
        if (request.City != null) prospect.City = request.City;
        if (request.State != null) prospect.State = request.State;
        if (request.Zip != null) prospect.Zip = request.Zip;
        if (request.Company != null) prospect.Company = request.Company;
        if (request.LinkedInUrl != null) prospect.LinkedInUrl = request.LinkedInUrl;

        prospect.EnrichmentStatus = EnrichmentStatus.Verified;
        prospect.UpdatedAt = DateTime.UtcNow;

        await _tenantDb.SaveChangesAsync();
        return Ok(MapToResponse(prospect));
    }

    [HttpPost("{id:int}/lookup")]
    public async Task<IActionResult> LookupContact(int id)
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var prospect = await _tenantDb.Prospects
            .Include(p => p.ProspectSignals!)
            .ThenInclude(ps => ps.Signal)
            .FirstOrDefaultAsync(p => p.Id == id);
        if (prospect == null) return NotFound();

        var postUrl = prospect.ProspectSignals?.Select(ps => ps.Signal?.PostUrl).FirstOrDefault(u => u != null);

        var result = await _contactLookupService.LookupAsync(
            _tenantContext.TenantId.Value, prospect.Name, prospect.Platform, postUrl,
            prospect.City, prospect.State, prospect.Company, prospect.LinkedInUrl, prospect.Email);

        if (!result.Success)
            return Ok(new { success = false, error = result.Error, provider = result.Provider });

        if (result.Phone != null) prospect.Phone = result.Phone;
        if (result.Email != null) prospect.Email = result.Email;
        if (result.Company != null) prospect.Company = result.Company;
        if (result.LinkedInUrl != null) prospect.LinkedInUrl = result.LinkedInUrl;

        prospect.EnrichmentStatus = EnrichmentStatus.Verified;
        prospect.UpdatedAt = DateTime.UtcNow;

        await _tenantDb.SaveChangesAsync();

        return Ok(new
        {
            success = true,
            provider = result.Provider,
            prospect = MapToResponse(prospect)
        });
    }

    [HttpPost("{id:int}/search-linkedin")]
    public async Task<IActionResult> SearchLinkedIn(int id)
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var prospect = await _tenantDb.Prospects.FindAsync(id);
        if (prospect == null) return NotFound();

        // If already has LinkedIn URL, return it directly
        if (!string.IsNullOrEmpty(prospect.LinkedInUrl))
            return Ok(new { success = true, alreadyHasUrl = true, linkedInUrl = prospect.LinkedInUrl });

        var result = await _linkedInSearchService.SearchAsync(
            _tenantContext.TenantId.Value, prospect.Name, prospect.City, prospect.State, prospect.Email);

        if (!result.Success)
            return Ok(new { success = false, error = result.Error });

        return Ok(new
        {
            success = true,
            candidates = result.Candidates.Select(c => new
            {
                c.Url,
                c.Name,
                c.Headline,
                c.Snippet
            })
        });
    }

    [HttpPut("{id:int}/linkedin")]
    public async Task<IActionResult> SaveLinkedIn(int id, [FromBody] SaveLinkedInRequest request)
    {
        var prospect = await _tenantDb.Prospects.FindAsync(id);
        if (prospect == null) return NotFound();

        prospect.LinkedInUrl = request.LinkedInUrl;
        prospect.UpdatedAt = DateTime.UtcNow;
        await _tenantDb.SaveChangesAsync();

        return Ok(new { success = true, prospect = MapToResponse(prospect) });
    }

    [HttpPost("{id:int}/scrub-linkedin-profile")]
    public async Task<IActionResult> ScrubLinkedInProfile(int id)
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var prospect = await _tenantDb.Prospects.FindAsync(id);
        if (prospect == null) return NotFound();

        if (string.IsNullOrEmpty(prospect.LinkedInUrl))
            return BadRequest(new { error = "No LinkedIn URL set for this prospect. Search and link a profile first." });

        var result = await _linkedInScraperService.ScrapeProfileAsync(_tenantContext.TenantId.Value, prospect.LinkedInUrl);

        if (!result.Success)
            return Ok(new { success = false, error = result.Error });

        // Save profile data to prospect
        var profile = result.Profile!;
        prospect.LinkedInType = profile.Type;
        if (!string.IsNullOrEmpty(profile.Name) && profile.Name != prospect.Name)
            prospect.LinkedInHeadline = profile.Headline; // Keep original prospect name
        prospect.LinkedInHeadline = profile.Headline;
        prospect.LinkedInAbout = profile.About;
        prospect.LinkedInContactInfo = profile.ContactInfo;
        prospect.LinkedInPhotoUrl = profile.PhotoUrl;
        prospect.LinkedInScrapedAt = DateTime.UtcNow;
        prospect.UpdatedAt = DateTime.UtcNow;

        await _tenantDb.SaveChangesAsync();

        return Ok(new
        {
            success = true,
            profile = new
            {
                prospect.LinkedInType,
                prospect.LinkedInHeadline,
                prospect.LinkedInAbout,
                prospect.LinkedInContactInfo,
                prospect.LinkedInPhotoUrl,
                prospect.LinkedInScrapedAt
            }
        });
    }

    [HttpPost("{id:int}/scrub-linkedin-posts")]
    public async Task<IActionResult> ScrubLinkedInPosts(int id)
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var prospect = await _tenantDb.Prospects.FindAsync(id);
        if (prospect == null) return NotFound();

        if (string.IsNullOrEmpty(prospect.LinkedInUrl))
            return BadRequest(new { error = "No LinkedIn URL set for this prospect." });

        var result = await _linkedInScraperService.ScrapePostsAsync(_tenantContext.TenantId.Value, prospect.LinkedInUrl);

        if (!result.Success)
            return Ok(new { success = false, error = result.Error });

        // Save posts - remove existing posts first to avoid duplicates
        var existingPosts = await _tenantDb.LinkedInPosts.Where(p => p.ProspectId == id).ToListAsync();
        _tenantDb.LinkedInPosts.RemoveRange(existingPosts);

        foreach (var postData in result.Posts)
        {
            _tenantDb.LinkedInPosts.Add(new Domain.Entities.Tenant.LinkedInPost
            {
                ProspectId = id,
                Content = postData.Content,
                PostUrl = postData.PostUrl,
                PostDate = postData.PostDate,
                Likes = postData.Likes,
                Comments = postData.Comments,
                ScrapedAt = DateTime.UtcNow
            });
        }

        prospect.UpdatedAt = DateTime.UtcNow;
        await _tenantDb.SaveChangesAsync();

        return Ok(new
        {
            success = true,
            postsCount = result.Posts.Count,
            posts = result.Posts.Select(p => new { p.Content, p.PostDate, p.Likes, p.Comments })
        });
    }

    [HttpGet("{id:int}/linkedin-posts")]
    public async Task<IActionResult> GetLinkedInPosts(int id)
    {
        var posts = await _tenantDb.LinkedInPosts
            .Where(p => p.ProspectId == id)
            .OrderByDescending(p => p.PostDate ?? p.ScrapedAt)
            .ToListAsync();

        return Ok(posts.Select(p => new
        {
            p.Id,
            p.Content,
            p.PostUrl,
            p.PostDate,
            p.Likes,
            p.Comments,
            p.ScrapedAt
        }));
    }

    [HttpGet("{id:int}/full-data")]
    public async Task<IActionResult> GetFullData(int id)
    {
        var prospect = await _tenantDb.Prospects
            .Include(p => p.ProspectSignals)
                .ThenInclude(ps => ps.Signal)
            .FirstOrDefaultAsync(p => p.Id == id);

        if (prospect == null) return NotFound();

        var linkedInPosts = await _tenantDb.LinkedInPosts
            .Where(p => p.ProspectId == id)
            .OrderByDescending(p => p.PostDate ?? p.ScrapedAt)
            .ToListAsync();

        var signals = prospect.ProspectSignals?
            .Where(ps => ps.Signal != null)
            .Select(ps => new SignalDto
            {
                Id = ps.Signal!.Id,
                Platform = ps.Signal.Platform,
                AuthorName = ps.Signal.AuthorName,
                AuthorProfileUrl = ps.Signal.AuthorProfileUrl,
                PostContent = ps.Signal.PostContent,
                PostUrl = ps.Signal.PostUrl,
                PostDate = ps.Signal.PostDate,
                DetectedAt = ps.Signal.DetectedAt,
                IntentScore = ps.Signal.IntentScore,
                IntentCategory = ps.Signal.IntentCategory,
                Sentiment = ps.Signal.Sentiment,
                AiSummary = ps.Signal.AiSummary,
                AiProvider = ps.Signal.AiProvider,
                AnalyzedAt = ps.Signal.AnalyzedAt
            }).ToList() ?? new List<SignalDto>();

        var posts = linkedInPosts.Select(p => new LinkedInPostDto
        {
            Id = p.Id,
            Content = p.Content,
            PostUrl = p.PostUrl,
            PostDate = p.PostDate,
            Likes = p.Likes,
            Comments = p.Comments,
            ScrapedAt = p.ScrapedAt
        }).ToList();

        return Ok(new ProspectFullDataResponse
        {
            Prospect = MapToResponse(prospect),
            Signals = signals,
            LinkedInPosts = posts
        });
    }

    [HttpPut("{id:int}/dismiss")]
    public async Task<IActionResult> Dismiss(int id)
    {
        var prospect = await _tenantDb.Prospects.FindAsync(id);
        if (prospect == null) return NotFound();

        prospect.Status = ProspectStatus.Dismissed;
        prospect.UpdatedAt = DateTime.UtcNow;
        await _tenantDb.SaveChangesAsync();

        return Ok(MapToResponse(prospect));
    }

    [HttpGet("export")]
    [HasPermission(Permissions.ExportData)]
    public async Task<IActionResult> ExportCsv([FromQuery] ProspectFilterRequest filter)
    {
        var query = _tenantDb.Prospects.AsQueryable();

        if (!string.IsNullOrEmpty(filter.Category))
            query = query.Where(p => p.Category == filter.Category);
        if (!string.IsNullOrEmpty(filter.Urgency) && Enum.TryParse<Urgency>(filter.Urgency, true, out var urgency))
            query = query.Where(p => p.Urgency == urgency);
        if (filter.MinScore.HasValue)
            query = query.Where(p => p.CompositeScore >= filter.MinScore.Value);
        if (filter.MaxScore.HasValue)
            query = query.Where(p => p.CompositeScore <= filter.MaxScore.Value);

        var prospects = await query.OrderByDescending(p => p.CompositeScore).ToListAsync();

        var sb = new StringBuilder();
        sb.AppendLine("Name,Score,Urgency,Category,Platform,Phone,Email,City,State,Zip,Company,Status,Created");

        foreach (var p in prospects)
        {
            sb.AppendLine($"\"{Esc(p.Name)}\",{p.CompositeScore},{p.Urgency},\"{Esc(p.Category ?? "")}\",\"{Esc(p.Platform ?? "")}\",\"{Esc(p.Phone ?? "")}\",\"{Esc(p.Email ?? "")}\",\"{Esc(p.City ?? "")}\",\"{Esc(p.State ?? "")}\",\"{Esc(p.Zip ?? "")}\",\"{Esc(p.Company ?? "")}\",{p.Status},{p.CreatedAt:yyyy-MM-dd}");
        }

        return File(Encoding.UTF8.GetBytes(sb.ToString()), "text/csv", "prospects.csv");
    }

    /// <summary>
    /// Valid status transitions:
    /// New → Viewed, Contacted, Dismissed
    /// Viewed → Contacted, Dismissed
    /// Contacted → Converted, Dismissed
    /// Converted → (terminal)
    /// Dismissed → (terminal)
    /// </summary>
    public static bool IsValidTransition(ProspectStatus current, ProspectStatus next)
    {
        if (current == next) return true;

        return current switch
        {
            ProspectStatus.New => next is ProspectStatus.Viewed or ProspectStatus.Contacted or ProspectStatus.Dismissed,
            ProspectStatus.Viewed => next is ProspectStatus.Contacted or ProspectStatus.Dismissed,
            ProspectStatus.Contacted => next is ProspectStatus.Converted or ProspectStatus.Dismissed,
            _ => false // Converted and Dismissed are terminal
        };
    }

    [HttpPost("reprocess")]
    public async Task<IActionResult> Reprocess()
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var tenantId = _tenantContext.TenantId.Value;
        var (dupSignals, dupProspects) = await _signalProcessor.DeduplicateExistingAsync(tenantId);
        var fixedSignalNames = await _signalProcessor.FixGenericAuthorNamesAsync(tenantId);
        var fixedProspectNames = await _signalProcessor.FixProspectNamesAsync(tenantId);
        await _signalProcessor.ProcessSignalsAsync(tenantId);
        var fixedLocations = await _signalProcessor.BackfillProspectLocationsAsync(tenantId);

        var matchCount = await _tenantDb.SignalKeywordMatches.CountAsync();
        var prospectCount = await _tenantDb.Prospects.CountAsync();

        return Ok(new
        {
            message = "Reprocessing complete",
            keywordMatches = matchCount,
            prospects = prospectCount,
            signalNamesFixed = fixedSignalNames,
            prospectNamesFixed = fixedProspectNames,
            locationsFixed = fixedLocations,
            duplicateSignalsRemoved = dupSignals,
            duplicateProspectsMerged = dupProspects
        });
    }

    [HttpPost("{id}/analyze")]
    public async Task<IActionResult> AnalyzeProspect(int id)
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var prospect = await _tenantDb.Prospects
            .Include(p => p.ProspectSignals)
                .ThenInclude(ps => ps.Signal)
            .FirstOrDefaultAsync(p => p.Id == id);

        if (prospect == null)
            return NotFound(new { error = "Prospect not found" });

        var settings = await _tenantDb.AiSettings.FirstOrDefaultAsync();
        var providerName = settings?.AiProvider ?? "Local";

        try
        {
            var analyzer = _analyzerFactory.Create(settings, _tenantContext.TenantId.Value);
            int analyzed = 0;

            foreach (var ps in prospect.ProspectSignals)
            {
                var signal = ps.Signal;
                if (signal == null || signal.AnalyzedAt != null) continue;

                var result = await analyzer.AnalyzeAsync(signal.PostContent, signal.Platform);
                signal.IntentScore = result.IntentScore;
                signal.IntentCategory = result.IntentCategory;
                signal.Sentiment = result.Sentiment;
                signal.AiSummary = result.Summary;
                signal.AiProvider = providerName;
                signal.AnalyzedAt = DateTime.UtcNow;

                if (!string.IsNullOrEmpty(result.Phone) && string.IsNullOrEmpty(prospect.Phone))
                    prospect.Phone = result.Phone;
                if (!string.IsNullOrEmpty(result.Email) && string.IsNullOrEmpty(prospect.Email))
                    prospect.Email = result.Email;

                analyzed++;
            }

            prospect.UpdatedAt = DateTime.UtcNow;
            await _tenantDb.SaveChangesAsync();

            return Ok(new { success = true, analyzed, prospect = MapToResponse(prospect) });
        }
        catch (HttpRequestException ex)
        {
            return BadRequest(new { error = ex.Message });
        }
        catch (InvalidOperationException ex)
        {
            return BadRequest(new { error = ex.Message });
        }
    }

    [HttpPost("analyze-all")]
    public async Task<IActionResult> AnalyzeAll()
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var settings = await _tenantDb.AiSettings.FirstOrDefaultAsync();
        var providerName = settings?.AiProvider ?? "Local";

        try
        {
            var analyzer = _analyzerFactory.Create(settings, _tenantContext.TenantId.Value);

            var unanalyzed = await _tenantDb.Signals
                .Where(s => s.AnalyzedAt == null)
                .Take(500)
                .ToListAsync();

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
                catch { /* Skip failed signals */ }
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
        catch (HttpRequestException ex)
        {
            return BadRequest(new { error = ex.Message });
        }
        catch (InvalidOperationException ex)
        {
            return BadRequest(new { error = ex.Message });
        }
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
            settings.EncryptedApiKey = _encryptionService.Encrypt(request.ApiKey, _tenantContext.TenantId.Value);

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
            return Ok(new { success = true, message = $"Key is valid. Test: {result.IntentCategory} (score: {result.IntentScore})" });
        }
        catch (HttpRequestException ex)
        {
            return Ok(new { success = false, error = ex.Message });
        }
        catch (Exception ex)
        {
            return Ok(new { success = false, error = $"Test failed: {ex.Message}" });
        }
    }

    // === LinkedIn Scraper Settings ===

    [HttpGet("scraper-settings")]
    public async Task<IActionResult> GetScraperSettings()
    {
        var settings = await _tenantDb.LinkedInScraperSettings.FirstOrDefaultAsync();
        return Ok(new ScraperSettingsResponse
        {
            HasApiKey = !string.IsNullOrEmpty(settings?.EncryptedApiKey),
            AiModel = settings?.AiModel ?? "claude-sonnet-4-6",
            UpdatedAt = settings?.UpdatedAt
        });
    }

    [HttpPut("scraper-settings")]
    public async Task<IActionResult> UpdateScraperSettings([FromBody] ScraperSettingsRequest request)
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var settings = await _tenantDb.LinkedInScraperSettings.FirstOrDefaultAsync();
        if (settings == null)
        {
            settings = new LinkedInScraperSettings();
            _tenantDb.LinkedInScraperSettings.Add(settings);
        }

        if (!string.IsNullOrEmpty(request.AiModel))
            settings.AiModel = request.AiModel;
        settings.UpdatedAt = DateTime.UtcNow;

        if (!string.IsNullOrEmpty(request.ApiKey))
            settings.EncryptedApiKey = _encryptionService.Encrypt(request.ApiKey, _tenantContext.TenantId.Value);

        await _tenantDb.SaveChangesAsync();

        return Ok(new ScraperSettingsResponse
        {
            HasApiKey = !string.IsNullOrEmpty(settings.EncryptedApiKey),
            AiModel = settings.AiModel,
            UpdatedAt = settings.UpdatedAt
        });
    }

    [HttpPost("scraper-settings/test")]
    public async Task<IActionResult> TestScraperKey()
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var settings = await _tenantDb.LinkedInScraperSettings.FirstOrDefaultAsync();
        if (settings == null || string.IsNullOrEmpty(settings.EncryptedApiKey))
            return Ok(new { success = false, error = "No Claude API key configured. Save your settings first." });

        try
        {
            var apiKey = _encryptionService.Decrypt(settings.EncryptedApiKey, _tenantContext.TenantId.Value);
            using var httpClient = new HttpClient();
            httpClient.DefaultRequestHeaders.Add("x-api-key", apiKey);
            httpClient.DefaultRequestHeaders.Add("anthropic-version", "2023-06-01");

            var testBody = new
            {
                model = settings.AiModel ?? "claude-sonnet-4-6",
                max_tokens = 10,
                messages = new[] { new { role = "user", content = "Say OK" } }
            };
            var response = await httpClient.PostAsJsonAsync("https://api.anthropic.com/v1/messages", testBody);

            if (response.IsSuccessStatusCode)
                return Ok(new { success = true, message = $"Claude API key is valid. Model: {settings.AiModel}" });

            var errorBody = await response.Content.ReadAsStringAsync();
            return Ok(new { success = false, error = $"Claude API returned {response.StatusCode}: {errorBody}" });
        }
        catch (Exception ex)
        {
            return Ok(new { success = false, error = $"Test failed: {ex.Message}" });
        }
    }

    private static ProspectResponse MapToResponse(Prospect p)
    {
        return new ProspectResponse
        {
            Id = p.Id,
            Name = p.Name,
            Phone = p.Phone,
            Email = p.Email,
            Address = p.Address,
            City = p.City,
            State = p.State,
            Zip = p.Zip,
            Company = p.Company,
            LinkedInUrl = p.LinkedInUrl,
            LinkedInType = p.LinkedInType,
            LinkedInHeadline = p.LinkedInHeadline,
            LinkedInAbout = p.LinkedInAbout,
            LinkedInContactInfo = p.LinkedInContactInfo,
            LinkedInPhotoUrl = p.LinkedInPhotoUrl,
            LinkedInScrapedAt = p.LinkedInScrapedAt,
            CompositeScore = p.CompositeScore,
            IntentScore = p.ProspectSignals?.Select(ps => ps.Signal?.IntentScore).Where(s => s.HasValue).Max(),
            IntentCategory = p.ProspectSignals?.Select(ps => ps.Signal?.IntentCategory).FirstOrDefault(s => s != null),
            Sentiment = p.ProspectSignals?.Select(ps => ps.Signal?.Sentiment).FirstOrDefault(s => s != null),
            AiSummary = p.ProspectSignals?.Select(ps => ps.Signal?.AiSummary).FirstOrDefault(s => s != null),
            AiProvider = p.ProspectSignals?.Select(ps => ps.Signal?.AiProvider).FirstOrDefault(s => s != null),
            AnalyzedAt = p.ProspectSignals?.Select(ps => ps.Signal?.AnalyzedAt).Where(d => d.HasValue).Max(),
            Urgency = p.Urgency.ToString(),
            Category = p.Category,
            Platform = p.Platform,
            SignalSnippet = p.SignalSnippet,
            PostUrl = p.ProspectSignals?.Select(ps => ps.Signal?.PostUrl).FirstOrDefault(u => u != null),
            PostDate = p.ProspectSignals?.Select(ps => ps.Signal?.PostDate).FirstOrDefault(d => d.HasValue),
            EnrichmentStatus = p.EnrichmentStatus.ToString(),
            Status = p.Status.ToString(),
            AssignedToUserId = p.AssignedToUserId,
            CreatedAt = p.CreatedAt,
            UpdatedAt = p.UpdatedAt
        };
    }

    private static string Esc(string v) => v.Replace("\"", "\"\"");

    [HttpGet("enrichment-settings")]
    public async Task<IActionResult> GetEnrichmentSettings()
    {
        var settings = await _tenantDb.EnrichmentSettings.ToListAsync();

        var result = new[] { "ContactOut", "Apollo" }.Select(provider =>
        {
            var s = settings.FirstOrDefault(x => x.Provider == provider);
            return new EnrichmentSettingsResponse
            {
                Provider = provider,
                Username = s?.Username,
                HasPassword = !string.IsNullOrEmpty(s?.EncryptedPassword),
                HasApiKey = !string.IsNullOrEmpty(s?.EncryptedApiKey),
                IsEnabled = s?.IsEnabled ?? false,
                UpdatedAt = s?.UpdatedAt
            };
        });

        return Ok(result);
    }

    [HttpPut("enrichment-settings")]
    public async Task<IActionResult> UpdateEnrichmentSettings([FromBody] EnrichmentSettingsRequest request)
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        if (request.Provider != "ContactOut" && request.Provider != "Apollo" && request.Provider != "SerpApi")
            return BadRequest(new { error = "Provider must be 'ContactOut', 'Apollo', or 'SerpApi'" });

        var settings = await _tenantDb.EnrichmentSettings
            .FirstOrDefaultAsync(s => s.Provider == request.Provider);

        if (settings == null)
        {
            settings = new EnrichmentSettings { Provider = request.Provider };
            _tenantDb.EnrichmentSettings.Add(settings);
        }

        settings.Username = request.Username;
        settings.IsEnabled = request.IsEnabled;
        settings.UpdatedAt = DateTime.UtcNow;

        if (!string.IsNullOrEmpty(request.Password))
        {
            settings.EncryptedPassword = _encryptionService.Encrypt(request.Password, _tenantContext.TenantId.Value);
        }

        if (!string.IsNullOrEmpty(request.ApiKey))
        {
            settings.EncryptedApiKey = _encryptionService.Encrypt(request.ApiKey, _tenantContext.TenantId.Value);
        }

        await _tenantDb.SaveChangesAsync();

        return Ok(new EnrichmentSettingsResponse
        {
            Provider = settings.Provider,
            Username = settings.Username,
            HasPassword = !string.IsNullOrEmpty(settings.EncryptedPassword),
            HasApiKey = !string.IsNullOrEmpty(settings.EncryptedApiKey),
            IsEnabled = settings.IsEnabled,
            UpdatedAt = settings.UpdatedAt
        });
    }
}
