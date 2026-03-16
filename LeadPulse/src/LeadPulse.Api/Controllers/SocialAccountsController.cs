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
[Route("api/social-accounts")]
[Authorize]
[HasPermission(Permissions.ManageSocialAccounts)]
public class SocialAccountsController : ControllerBase
{
    private readonly TenantDbContext _tenantDb;
    private readonly AppDbContext _appDb;
    private readonly ITenantContext _tenantContext;
    private readonly IEncryptionService _encryption;
    private readonly ISyncService _syncService;
    private readonly IEnumerable<ISocialPlatformAdapter> _adapters;

    public SocialAccountsController(
        TenantDbContext tenantDb,
        AppDbContext appDb,
        ITenantContext tenantContext,
        IEncryptionService encryption,
        ISyncService syncService,
        IEnumerable<ISocialPlatformAdapter> adapters)
    {
        _tenantDb = tenantDb;
        _appDb = appDb;
        _tenantContext = tenantContext;
        _encryption = encryption;
        _syncService = syncService;
        _adapters = adapters;
    }

    [HttpGet]
    public async Task<IActionResult> GetAll()
    {
        var accounts = await _tenantDb.SocialAccounts
            .OrderByDescending(a => a.CreatedAt)
            .ToListAsync();

        return Ok(accounts.Select(MapToResponse));
    }

    [HttpGet("{id}")]
    public async Task<IActionResult> GetById(int id)
    {
        var account = await _tenantDb.SocialAccounts.FindAsync(id);
        if (account == null) return NotFound();
        return Ok(MapToResponse(account));
    }

    [HttpPost]
    public async Task<IActionResult> Create([FromBody] CreateSocialAccountRequest request)
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
            var currentCount = await _tenantDb.SocialAccounts.CountAsync();
            if (currentCount >= tenant.Plan.MaxSocialAccounts)
                return BadRequest(new { error = "Social account limit reached for your subscription plan" });
        }

        // Password is optional for public-API platforms like Reddit
        var passwordValue = request.Password ?? "N/A";

        var account = new SocialAccount
        {
            Platform = request.Platform,
            Username = request.Username,
            EncryptedPassword = _encryption.Encrypt(passwordValue, tenantId),
            EncryptedMfaSecret = request.MfaSecret != null
                ? _encryption.Encrypt(request.MfaSecret, tenantId) : null,
            Status = SocialAccountStatus.Active,
            CreatedAt = DateTime.UtcNow
        };

        _tenantDb.SocialAccounts.Add(account);
        await _tenantDb.SaveChangesAsync();

        return CreatedAtAction(nameof(GetById), new { id = account.Id }, MapToResponse(account));
    }

    [HttpPut("{id}/credentials")]
    public async Task<IActionResult> UpdateCredentials(int id, [FromBody] UpdateCredentialsRequest request)
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var account = await _tenantDb.SocialAccounts.FindAsync(id);
        if (account == null) return NotFound();

        var tenantId = _tenantContext.TenantId.Value;
        account.Username = request.Username;
        account.EncryptedPassword = _encryption.Encrypt(request.Password, tenantId);
        account.EncryptedMfaSecret = request.MfaSecret != null
            ? _encryption.Encrypt(request.MfaSecret, tenantId) : null;
        account.Status = SocialAccountStatus.Active;
        account.UpdatedAt = DateTime.UtcNow;

        await _tenantDb.SaveChangesAsync();
        return Ok(MapToResponse(account));
    }

    [HttpPut("{id}/sync-config")]
    public async Task<IActionResult> UpdateSyncConfig(int id, [FromBody] UpdateSyncConfigRequest request)
    {
        var account = await _tenantDb.SocialAccounts.FindAsync(id);
        if (account == null) return NotFound();

        if (request.SyncFrequencyMinutes < 60 || request.SyncFrequencyMinutes > 2880)
            return BadRequest(new { error = "Sync frequency must be between 60 and 2880 minutes" });

        account.SyncFrequencyMinutes = request.SyncFrequencyMinutes;
        account.SyncWindowStart = request.SyncWindowStart != null
            ? TimeSpan.Parse(request.SyncWindowStart) : null;
        account.SyncWindowEnd = request.SyncWindowEnd != null
            ? TimeSpan.Parse(request.SyncWindowEnd) : null;
        account.MaxPostsPerSync = request.MaxPostsPerSync;
        account.ScrapeDepth = request.ScrapeDepth;
        account.AutoRetryMax = request.AutoRetryMax;
        account.UpdatedAt = DateTime.UtcNow;

        await _tenantDb.SaveChangesAsync();
        return Ok(MapToResponse(account));
    }

    [HttpPost("{id}/test-login")]
    public async Task<IActionResult> TestLogin(int id)
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var account = await _tenantDb.SocialAccounts.FindAsync(id);
        if (account == null) return NotFound();

        var tenantId = _tenantContext.TenantId.Value;
        var adapter = _adapters.FirstOrDefault(a =>
            a.Platform.Equals(account.Platform, StringComparison.OrdinalIgnoreCase));

        if (adapter == null)
            return BadRequest(new { error = $"No adapter available for platform: {account.Platform}" });

        var password = _encryption.Decrypt(account.EncryptedPassword, tenantId);
        var mfaSecret = account.EncryptedMfaSecret != null
            ? _encryption.Decrypt(account.EncryptedMfaSecret, tenantId) : null;

        var result = await adapter.TestLoginAsync(account.Username, password, mfaSecret);

        if (result.Success)
        {
            account.LastLoginAt = DateTime.UtcNow;
            account.Status = SocialAccountStatus.Active;
            await _tenantDb.SaveChangesAsync();
            return Ok(new { success = true, message = "Login test successful" });
        }

        account.Status = SocialAccountStatus.LoginFailed;
        await _tenantDb.SaveChangesAsync();
        return Ok(new { success = false, message = result.ErrorMessage ?? "Login test failed" });
    }

    [HttpPost("{id}/sync-now")]
    public async Task<IActionResult> SyncNow(int id)
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var account = await _tenantDb.SocialAccounts.FindAsync(id);
        if (account == null) return NotFound();

        var tenantId = _tenantContext.TenantId.Value;

        // Run the real sync via SyncService (uses platform adapters)
        await _syncService.RunSyncJobAsync(tenantId, id);

        // Get the latest sync job to return stats
        var latestJob = await _tenantDb.SyncJobs
            .Where(j => j.SocialAccountId == id)
            .OrderByDescending(j => j.CreatedAt)
            .FirstOrDefaultAsync();

        if (latestJob == null)
            return Ok(new { message = "Sync completed but no job record found" });

        if (latestJob.Status == SyncJobStatus.Failed)
            return BadRequest(new { error = latestJob.ErrorMessage ?? "Sync failed", jobId = latestJob.Id });

        return Ok(new
        {
            message = $"Sync complete: {latestJob.PostsFound} posts found",
            jobId = latestJob.Id,
            postsFound = latestJob.PostsFound,
            signalsGenerated = latestJob.SignalsGenerated
        });
    }

    [HttpGet("{id}/sync-jobs")]
    public async Task<IActionResult> GetSyncJobs(int id, [FromQuery] int limit = 20)
    {
        var jobs = await _tenantDb.SyncJobs
            .Where(j => j.SocialAccountId == id)
            .OrderByDescending(j => j.CreatedAt)
            .Take(limit)
            .ToListAsync();

        return Ok(jobs.Select(j => new SyncJobResponse
        {
            Id = j.Id,
            SocialAccountId = j.SocialAccountId,
            Status = j.Status.ToString(),
            PostsFound = j.PostsFound,
            SignalsGenerated = j.SignalsGenerated,
            StartedAt = j.StartedAt,
            CompletedAt = j.CompletedAt,
            DurationSeconds = j.DurationSeconds,
            ErrorMessage = j.ErrorMessage,
            RetryCount = j.RetryCount,
            CreatedAt = j.CreatedAt
        }));
    }

    [HttpGet("{id}/targets")]
    public async Task<IActionResult> GetTargets(int id)
    {
        var targets = await _tenantDb.MonitoredGroups
            .Where(g => g.SocialAccountId == id)
            .OrderBy(g => g.Id)
            .ToListAsync();

        return Ok(targets.Select(g => new MonitoredGroupResponse
        {
            Id = g.Id,
            SocialAccountId = g.SocialAccountId,
            Platform = g.Platform,
            GroupUrl = g.GroupUrl,
            GroupName = g.GroupName,
            IsActive = g.IsActive
        }));
    }

    [HttpPost("{id}/targets")]
    public async Task<IActionResult> AddTarget(int id, [FromBody] MonitoredGroupRequest request)
    {
        var account = await _tenantDb.SocialAccounts.FindAsync(id);
        if (account == null) return NotFound();

        var target = new MonitoredGroup
        {
            SocialAccountId = id,
            Platform = account.Platform,
            GroupUrl = request.GroupUrl,
            GroupName = request.GroupName,
            IsActive = true
        };

        _tenantDb.MonitoredGroups.Add(target);
        await _tenantDb.SaveChangesAsync();

        return Ok(new MonitoredGroupResponse
        {
            Id = target.Id,
            SocialAccountId = target.SocialAccountId,
            Platform = target.Platform,
            GroupUrl = target.GroupUrl,
            GroupName = target.GroupName,
            IsActive = target.IsActive
        });
    }

    [HttpPut("{id}/targets/{targetId}")]
    public async Task<IActionResult> UpdateTarget(int id, int targetId, [FromBody] MonitoredGroupRequest request)
    {
        var target = await _tenantDb.MonitoredGroups
            .FirstOrDefaultAsync(g => g.Id == targetId && g.SocialAccountId == id);
        if (target == null) return NotFound();

        target.GroupUrl = request.GroupUrl;
        target.GroupName = request.GroupName;
        await _tenantDb.SaveChangesAsync();

        return Ok(new MonitoredGroupResponse
        {
            Id = target.Id,
            SocialAccountId = target.SocialAccountId,
            Platform = target.Platform,
            GroupUrl = target.GroupUrl,
            GroupName = target.GroupName,
            IsActive = target.IsActive
        });
    }

    [HttpPatch("{id}/targets/{targetId}/toggle")]
    public async Task<IActionResult> ToggleTarget(int id, int targetId)
    {
        var target = await _tenantDb.MonitoredGroups
            .FirstOrDefaultAsync(g => g.Id == targetId && g.SocialAccountId == id);
        if (target == null) return NotFound();

        target.IsActive = !target.IsActive;
        await _tenantDb.SaveChangesAsync();
        return Ok(new { target.Id, target.IsActive });
    }

    [HttpPost("{id}/targets/{targetId}/test")]
    public async Task<IActionResult> TestTarget(int id, int targetId)
    {
        if (!_tenantContext.TenantId.HasValue)
            return BadRequest(new { error = "Tenant context required" });

        var account = await _tenantDb.SocialAccounts.FindAsync(id);
        if (account == null) return NotFound();

        var target = await _tenantDb.MonitoredGroups
            .FirstOrDefaultAsync(g => g.Id == targetId && g.SocialAccountId == id);
        if (target == null) return NotFound();

        var adapter = _adapters.FirstOrDefault(a =>
            a.Platform.Equals(account.Platform, StringComparison.OrdinalIgnoreCase));

        if (adapter == null)
            return BadRequest(new { error = $"No adapter for platform: {account.Platform}" });

        var tenantId = _tenantContext.TenantId.Value;
        var password = _encryption.Decrypt(account.EncryptedPassword, tenantId);
        var mfaSecret = account.EncryptedMfaSecret != null
            ? _encryption.Decrypt(account.EncryptedMfaSecret, tenantId) : null;

        var result = await adapter.ScrapePostsAsync(
            account.Username, password, mfaSecret,
            10, // limit to 10 posts for test
            account.ScrapeDepth,
            new List<string> { target.GroupUrl });

        if (!result.Success)
            return Ok(new { success = false, error = result.ErrorMessage, posts = Array.Empty<object>() });

        return Ok(new
        {
            success = true,
            postsFound = result.Posts.Count,
            posts = result.Posts.Take(10).Select(p => new
            {
                author = p.AuthorName,
                content = p.Content?.Length > 300 ? p.Content[..300] + "..." : p.Content,
                postUrl = p.PostUrl,
                postDate = p.PostDate
            })
        });
    }

    [HttpDelete("{id}/targets/{targetId}")]
    public async Task<IActionResult> DeleteTarget(int id, int targetId)
    {
        var target = await _tenantDb.MonitoredGroups
            .FirstOrDefaultAsync(g => g.Id == targetId && g.SocialAccountId == id);
        if (target == null) return NotFound();

        _tenantDb.MonitoredGroups.Remove(target);
        await _tenantDb.SaveChangesAsync();
        return Ok(new { message = "Target removed" });
    }

    [HttpDelete("{id}")]
    public async Task<IActionResult> Delete(int id)
    {
        var account = await _tenantDb.SocialAccounts
            .Include(a => a.MonitoredGroups)
            .FirstOrDefaultAsync(a => a.Id == id);

        if (account == null) return NotFound();

        _tenantDb.SocialAccounts.Remove(account);
        await _tenantDb.SaveChangesAsync();

        return Ok(new { message = "Social account deleted" });
    }

    private static SocialAccountResponse MapToResponse(SocialAccount account)
    {
        return new SocialAccountResponse
        {
            Id = account.Id,
            Platform = account.Platform,
            Username = account.Username,
            // Password is NEVER included in response
            SyncFrequencyMinutes = account.SyncFrequencyMinutes,
            SyncWindowStart = account.SyncWindowStart?.ToString(@"hh\:mm"),
            SyncWindowEnd = account.SyncWindowEnd?.ToString(@"hh\:mm"),
            MaxPostsPerSync = account.MaxPostsPerSync,
            ScrapeDepth = account.ScrapeDepth,
            AutoRetryMax = account.AutoRetryMax,
            Status = account.Status.ToString(),
            LastLoginAt = account.LastLoginAt,
            LastSyncAt = account.LastSyncAt,
            TotalPostsScraped = account.TotalPostsScraped,
            CreatedAt = account.CreatedAt
        };
    }
}
