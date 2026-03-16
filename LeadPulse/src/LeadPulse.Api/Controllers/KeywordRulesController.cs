using System.Text;
using System.Text.Json;
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
[Route("api/keywords")]
[Authorize]
[HasPermission(Permissions.ManageKeywords)]
public class KeywordRulesController : ControllerBase
{
    private readonly TenantDbContext _tenantDb;
    private readonly AppDbContext _appDb;
    private readonly ITenantContext _tenantContext;
    private readonly TenantDbContextFactory _tenantDbFactory;

    public KeywordRulesController(
        TenantDbContext tenantDb,
        AppDbContext appDb,
        ITenantContext tenantContext,
        TenantDbContextFactory tenantDbFactory)
    {
        _tenantDb = tenantDb;
        _appDb = appDb;
        _tenantContext = tenantContext;
        _tenantDbFactory = tenantDbFactory;
    }

    [HttpGet]
    public async Task<IActionResult> GetAll([FromQuery] string? category = null, [FromQuery] bool? isActive = null)
    {
        var query = _tenantDb.KeywordRules.AsQueryable();

        if (!string.IsNullOrEmpty(category))
            query = query.Where(k => k.Category == category);
        if (isActive.HasValue)
            query = query.Where(k => k.IsActive == isActive.Value);

        var rules = await query.OrderBy(k => k.Keyword).ToListAsync();
        return Ok(rules.Select(MapToResponse));
    }

    [HttpGet("{id}")]
    public async Task<IActionResult> GetById(int id)
    {
        var rule = await _tenantDb.KeywordRules.FindAsync(id);
        if (rule == null) return NotFound();
        return Ok(MapToResponse(rule));
    }

    [HttpPost]
    public async Task<IActionResult> Create([FromBody] CreateKeywordRuleRequest request)
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var tenantId = _tenantContext.TenantId.Value;

        // Check plan limit
        var tenant = await _appDb.Tenants
            .Include(t => t.Plan)
            .FirstOrDefaultAsync(t => t.Id == tenantId);

        if (tenant != null)
        {
            var currentCount = await _tenantDb.KeywordRules.CountAsync();
            if (currentCount >= tenant.Plan.MaxKeywords)
                return BadRequest(new { error = "Keyword limit reached for your subscription plan" });
        }

        if (!Enum.TryParse<KeywordMatchType>(request.MatchType, true, out var matchType))
            return BadRequest(new { error = $"Invalid match type: {request.MatchType}" });

        var rule = new KeywordRule
        {
            Keyword = request.Keyword,
            MatchType = matchType,
            Category = request.Category,
            ScoreBoost = request.ScoreBoost,
            Synonyms = request.Synonyms != null ? JsonSerializer.Serialize(request.Synonyms) : null,
            SimilarityThreshold = request.SimilarityThreshold,
            NegativeKeywords = request.NegativeKeywords != null ? JsonSerializer.Serialize(request.NegativeKeywords) : null,
            Platforms = request.Platforms != null ? JsonSerializer.Serialize(request.Platforms) : null,
            CreatedAt = DateTime.UtcNow
        };

        _tenantDb.KeywordRules.Add(rule);
        await _tenantDb.SaveChangesAsync();

        return CreatedAtAction(nameof(GetById), new { id = rule.Id }, MapToResponse(rule));
    }

    [HttpPut("{id}")]
    public async Task<IActionResult> Update(int id, [FromBody] UpdateKeywordRuleRequest request)
    {
        var rule = await _tenantDb.KeywordRules.FindAsync(id);
        if (rule == null) return NotFound();

        if (!Enum.TryParse<KeywordMatchType>(request.MatchType, true, out var matchType))
            return BadRequest(new { error = $"Invalid match type: {request.MatchType}" });

        rule.Keyword = request.Keyword;
        rule.MatchType = matchType;
        rule.Category = request.Category;
        rule.ScoreBoost = request.ScoreBoost;
        rule.Synonyms = request.Synonyms != null ? JsonSerializer.Serialize(request.Synonyms) : null;
        rule.SimilarityThreshold = request.SimilarityThreshold;
        rule.NegativeKeywords = request.NegativeKeywords != null ? JsonSerializer.Serialize(request.NegativeKeywords) : null;
        rule.Platforms = request.Platforms != null ? JsonSerializer.Serialize(request.Platforms) : null;
        rule.IsActive = request.IsActive;
        rule.UpdatedAt = DateTime.UtcNow;

        await _tenantDb.SaveChangesAsync();
        return Ok(MapToResponse(rule));
    }

    [HttpDelete("{id}")]
    public async Task<IActionResult> Delete(int id)
    {
        var rule = await _tenantDb.KeywordRules.FindAsync(id);
        if (rule == null) return NotFound();

        _tenantDb.KeywordRules.Remove(rule);
        await _tenantDb.SaveChangesAsync();
        return Ok(new { message = "Keyword rule deleted" });
    }

    [HttpPost("{id}/toggle")]
    public async Task<IActionResult> Toggle(int id)
    {
        var rule = await _tenantDb.KeywordRules.FindAsync(id);
        if (rule == null) return NotFound();

        rule.IsActive = !rule.IsActive;
        rule.UpdatedAt = DateTime.UtcNow;
        await _tenantDb.SaveChangesAsync();

        return Ok(MapToResponse(rule));
    }

    [HttpGet("export")]
    public async Task<IActionResult> ExportCsv()
    {
        var rules = await _tenantDb.KeywordRules.OrderBy(k => k.Keyword).ToListAsync();

        var sb = new StringBuilder();
        sb.AppendLine("Keyword,MatchType,Category,ScoreBoost,Synonyms,SimilarityThreshold,NegativeKeywords,Platforms");

        foreach (var rule in rules)
        {
            sb.AppendLine($"\"{EscapeCsv(rule.Keyword)}\",\"{rule.MatchType}\",\"{EscapeCsv(rule.Category ?? "")}\",{rule.ScoreBoost},\"{EscapeCsv(rule.Synonyms ?? "")}\",{rule.SimilarityThreshold},\"{EscapeCsv(rule.NegativeKeywords ?? "")}\",\"{EscapeCsv(rule.Platforms ?? "")}\"");
        }

        return File(Encoding.UTF8.GetBytes(sb.ToString()), "text/csv", "keywords.csv");
    }

    [HttpPost("import")]
    public async Task<IActionResult> ImportCsv([FromBody] List<KeywordCsvRow> rows)
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var imported = 0;
        foreach (var row in rows)
        {
            if (!Enum.TryParse<KeywordMatchType>(row.MatchType, true, out var matchType))
                continue;

            var rule = new KeywordRule
            {
                Keyword = row.Keyword,
                MatchType = matchType,
                Category = row.Category,
                ScoreBoost = row.ScoreBoost,
                Synonyms = row.Synonyms,
                SimilarityThreshold = row.SimilarityThreshold,
                NegativeKeywords = row.NegativeKeywords,
                Platforms = row.Platforms,
                CreatedAt = DateTime.UtcNow
            };

            _tenantDb.KeywordRules.Add(rule);
            imported++;
        }

        await _tenantDb.SaveChangesAsync();
        return Ok(new { imported });
    }

    [HttpPost("copy")]
    public async Task<IActionResult> CopyBetweenTenants([FromBody] CopyKeywordsRequest request)
    {
        // Super Admin only — reads source tenant DB, writes to target tenant DB
        var userRole = User.FindFirst("role")?.Value;
        if (userRole != "SuperAdmin")
            return Forbid();

        await using var sourceDb = await _tenantDbFactory.CreateContextAsync(request.SourceTenantId);
        await using var targetDb = await _tenantDbFactory.CreateContextAsync(request.TargetTenantId);

        var sourceRules = await sourceDb.KeywordRules.Where(k => k.IsActive).ToListAsync();

        var copied = 0;
        foreach (var source in sourceRules)
        {
            var rule = new KeywordRule
            {
                Keyword = source.Keyword,
                MatchType = source.MatchType,
                Category = source.Category,
                ScoreBoost = source.ScoreBoost,
                Synonyms = source.Synonyms,
                SimilarityThreshold = source.SimilarityThreshold,
                NegativeKeywords = source.NegativeKeywords,
                Platforms = source.Platforms,
                CreatedAt = DateTime.UtcNow
            };

            targetDb.KeywordRules.Add(rule);
            copied++;
        }

        await targetDb.SaveChangesAsync();
        return Ok(new { copied });
    }

    private static KeywordRuleResponse MapToResponse(KeywordRule rule)
    {
        return new KeywordRuleResponse
        {
            Id = rule.Id,
            Keyword = rule.Keyword,
            MatchType = rule.MatchType.ToString(),
            Category = rule.Category,
            ScoreBoost = rule.ScoreBoost,
            Synonyms = DeserializeList(rule.Synonyms),
            SimilarityThreshold = rule.SimilarityThreshold,
            NegativeKeywords = DeserializeList(rule.NegativeKeywords),
            Platforms = DeserializeList(rule.Platforms),
            IsActive = rule.IsActive,
            HitCount30d = rule.HitCount30d,
            CreatedAt = rule.CreatedAt,
            UpdatedAt = rule.UpdatedAt
        };
    }

    private static List<string>? DeserializeList(string? json)
    {
        if (string.IsNullOrEmpty(json)) return null;
        try { return JsonSerializer.Deserialize<List<string>>(json); }
        catch { return null; }
    }

    private static string EscapeCsv(string value) => value.Replace("\"", "\"\"");
}
