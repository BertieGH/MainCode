using System.Text;
using LeadPulse.Application.DTOs;
using LeadPulse.Application.Interfaces;
using LeadPulse.Domain.Authorization;
using LeadPulse.Domain.Entities.Tenant;
using LeadPulse.Domain.Enums;
using LeadPulse.Infrastructure.Authorization;
using LeadPulse.Infrastructure.Data;
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

    public ProspectsController(TenantDbContext tenantDb, ITenantContext tenantContext, IEncryptionService encryptionService)
    {
        _tenantDb = tenantDb;
        _tenantContext = tenantContext;
        _encryptionService = encryptionService;
    }

    [HttpGet]
    public async Task<IActionResult> GetAll([FromQuery] ProspectFilterRequest filter)
    {
        var query = _tenantDb.Prospects.AsQueryable();

        // Apply filters
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

    [HttpGet("{id}")]
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

    [HttpPut("{id}/status")]
    public async Task<IActionResult> UpdateStatus(int id, [FromBody] UpdateProspectStatusRequest request)
    {
        var prospect = await _tenantDb.Prospects.FindAsync(id);
        if (prospect == null) return NotFound();

        if (!Enum.TryParse<ProspectStatus>(request.Status, true, out var newStatus))
            return BadRequest(new { error = $"Invalid status: {request.Status}" });

        // Validate status transitions
        if (!IsValidTransition(prospect.Status, newStatus))
            return BadRequest(new { error = $"Cannot transition from {prospect.Status} to {newStatus}" });

        prospect.Status = newStatus;
        prospect.UpdatedAt = DateTime.UtcNow;
        await _tenantDb.SaveChangesAsync();

        return Ok(MapToResponse(prospect));
    }

    [HttpPut("{id}/enrich")]
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

    [HttpPut("{id}/dismiss")]
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
            CompositeScore = p.CompositeScore,
            IntentScore = p.ProspectSignals?.Select(ps => ps.Signal?.IntentScore).Where(s => s.HasValue).Max(),
            Sentiment = p.ProspectSignals?.Select(ps => ps.Signal?.Sentiment).FirstOrDefault(s => s != null),
            Urgency = p.Urgency.ToString(),
            Category = p.Category,
            Platform = p.Platform,
            SignalSnippet = p.SignalSnippet,
            PostUrl = p.ProspectSignals?.Select(ps => ps.Signal?.PostUrl).FirstOrDefault(u => u != null),
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

        if (request.Provider != "ContactOut" && request.Provider != "Apollo")
            return BadRequest(new { error = "Provider must be 'ContactOut' or 'Apollo'" });

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
