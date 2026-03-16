using LeadPulse.Application.Interfaces;
using LeadPulse.Domain.Entities.Tenant;
using LeadPulse.Domain.Enums;
using LeadPulse.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace LeadPulse.Infrastructure.Services;

public class SyncService : ISyncService
{
    private readonly TenantDbContextFactory _tenantDbFactory;
    private readonly IEncryptionService _encryption;
    private readonly IEnumerable<ISocialPlatformAdapter> _adapters;
    private readonly ISignalProcessor _signalProcessor;
    private readonly ILogger<SyncService> _logger;

    public SyncService(
        TenantDbContextFactory tenantDbFactory,
        IEncryptionService encryption,
        IEnumerable<ISocialPlatformAdapter> adapters,
        ISignalProcessor signalProcessor,
        ILogger<SyncService> logger)
    {
        _tenantDbFactory = tenantDbFactory;
        _encryption = encryption;
        _adapters = adapters;
        _signalProcessor = signalProcessor;
        _logger = logger;
    }

    public async Task RunSyncJobAsync(int tenantId, int socialAccountId)
    {
        await using var tenantDb = await _tenantDbFactory.CreateContextAsync(tenantId);

        var account = await tenantDb.SocialAccounts.FindAsync(socialAccountId);
        if (account == null)
        {
            _logger.LogWarning("Social account {AccountId} not found for tenant {TenantId}", socialAccountId, tenantId);
            return;
        }

        // Check sync window
        if (!IsWithinSyncWindow(account.SyncWindowStart, account.SyncWindowEnd))
        {
            _logger.LogInformation("Sync skipped for account {AccountId} — outside sync window", socialAccountId);
            return;
        }

        // Auto-seed default keyword rules if none exist
        if (!await tenantDb.KeywordRules.AnyAsync(k => k.IsActive))
        {
            _logger.LogInformation("No active keyword rules found for tenant {TenantId}, seeding defaults", tenantId);
            tenantDb.KeywordRules.AddRange(GetDefaultKeywordRules());
            await tenantDb.SaveChangesAsync();
        }

        // Create sync job record
        var job = new SyncJob
        {
            SocialAccountId = socialAccountId,
            Status = SyncJobStatus.Running,
            StartedAt = DateTime.UtcNow,
            CreatedAt = DateTime.UtcNow
        };
        tenantDb.SyncJobs.Add(job);
        await tenantDb.SaveChangesAsync();

        var adapter = _adapters.FirstOrDefault(a =>
            a.Platform.Equals(account.Platform, StringComparison.OrdinalIgnoreCase));

        if (adapter == null)
        {
            job.Status = SyncJobStatus.Failed;
            job.ErrorMessage = $"No adapter for platform: {account.Platform}";
            job.CompletedAt = DateTime.UtcNow;
            await tenantDb.SaveChangesAsync();
            return;
        }

        var password = _encryption.Decrypt(account.EncryptedPassword, tenantId);
        var mfaSecret = account.EncryptedMfaSecret != null
            ? _encryption.Decrypt(account.EncryptedMfaSecret, tenantId) : null;

        // Load configured target URLs
        var targetUrls = await tenantDb.MonitoredGroups
            .Where(g => g.SocialAccountId == socialAccountId && g.IsActive)
            .Select(g => g.GroupUrl)
            .ToListAsync();

        int retryCount = 0;
        bool success = false;

        while (retryCount <= account.AutoRetryMax && !success)
        {
            try
            {
                account.Status = SocialAccountStatus.Syncing;
                await tenantDb.SaveChangesAsync();

                var result = await adapter.ScrapePostsAsync(
                    account.Username, password, mfaSecret,
                    account.MaxPostsPerSync, account.ScrapeDepth,
                    targetUrls.Count > 0 ? targetUrls : null);

                if (result.Success)
                {
                    // Deduplicate against existing signals
                    var existingUrlsList = await tenantDb.Signals
                        .Where(s => s.SocialAccountId == socialAccountId)
                        .Select(s => s.PostUrl)
                        .ToListAsync();
                    var existingUrls = new HashSet<string>(existingUrlsList.Where(u => u != null)!);

                    var newPosts = result.Posts
                        .Where(p => !string.IsNullOrEmpty(p.PostUrl) && !existingUrls.Contains(p.PostUrl))
                        .ToList();

                    job.PostsFound = newPosts.Count;

                    // Store signals
                    foreach (var post in newPosts)
                    {
                        var signal = new Signal
                        {
                            SocialAccountId = socialAccountId,
                            Platform = account.Platform,
                            AuthorName = post.AuthorName,
                            AuthorProfileUrl = post.AuthorProfileUrl,
                            PostContent = post.Content,
                            PostUrl = post.PostUrl,
                            PostDate = post.PostDate,
                            DetectedAt = DateTime.UtcNow
                        };
                        tenantDb.Signals.Add(signal);
                    }

                    await tenantDb.SaveChangesAsync();

                    // Process signals → keyword matches → prospects
                    await _signalProcessor.ProcessSignalsAsync(tenantId);

                    // Count generated signals (prospects created/updated)
                    job.SignalsGenerated = newPosts.Count;
                    job.Status = SyncJobStatus.Success;
                    account.Status = SocialAccountStatus.Active;
                    account.LastSyncAt = DateTime.UtcNow;
                    account.TotalPostsScraped += newPosts.Count;
                    success = true;

                    // Log activity
                    tenantDb.ActivityLogs.Add(new ActivityLog
                    {
                        ActionType = "Sync",
                        Description = $"Synced {newPosts.Count} posts from {account.Platform} ({account.Username})",
                        CreatedAt = DateTime.UtcNow
                    });
                }
                else
                {
                    throw new Exception(result.ErrorMessage ?? "Scrape failed");
                }
            }
            catch (Exception ex)
            {
                retryCount++;
                job.RetryCount = retryCount;

                if (retryCount > account.AutoRetryMax)
                {
                    job.Status = SyncJobStatus.Failed;
                    job.ErrorMessage = ex.Message;
                    account.Status = SocialAccountStatus.LoginFailed;
                    _logger.LogError(ex, "Sync failed for account {AccountId} after {Retries} retries",
                        socialAccountId, retryCount);
                }
                else
                {
                    _logger.LogWarning("Sync attempt {Retry}/{Max} failed for account {AccountId}: {Error}",
                        retryCount, account.AutoRetryMax, socialAccountId, ex.Message);
                    await Task.Delay(TimeSpan.FromSeconds(Math.Pow(2, retryCount))); // Exponential backoff
                }
            }
        }

        job.CompletedAt = DateTime.UtcNow;
        job.DurationSeconds = (int)(job.CompletedAt.Value - job.StartedAt!.Value).TotalSeconds;
        await tenantDb.SaveChangesAsync();
    }

    public bool IsWithinSyncWindow(TimeSpan? windowStart, TimeSpan? windowEnd)
    {
        if (!windowStart.HasValue || !windowEnd.HasValue)
            return true; // No window configured = always OK

        var now = DateTime.UtcNow.TimeOfDay;

        if (windowStart.Value <= windowEnd.Value)
            return now >= windowStart.Value && now <= windowEnd.Value;

        // Window spans midnight (e.g., 22:00 - 06:00)
        return now >= windowStart.Value || now <= windowEnd.Value;
    }

    private static KeywordRule[] GetDefaultKeywordRules()
    {
        return new[]
        {
            new KeywordRule { Keyword = "insurance", MatchType = KeywordMatchType.Contains, Category = "General", ScoreBoost = 10, IsActive = true, CreatedAt = DateTime.UtcNow },
            new KeywordRule { Keyword = "car insurance", MatchType = KeywordMatchType.Contains, Category = "Auto", ScoreBoost = 20, IsActive = true, CreatedAt = DateTime.UtcNow },
            new KeywordRule { Keyword = "auto insurance", MatchType = KeywordMatchType.Contains, Category = "Auto", ScoreBoost = 20, IsActive = true, CreatedAt = DateTime.UtcNow },
            new KeywordRule { Keyword = "home insurance", MatchType = KeywordMatchType.Contains, Category = "Home", ScoreBoost = 20, IsActive = true, CreatedAt = DateTime.UtcNow },
            new KeywordRule { Keyword = "homeowners insurance", MatchType = KeywordMatchType.Contains, Category = "Home", ScoreBoost = 25, IsActive = true, CreatedAt = DateTime.UtcNow },
            new KeywordRule { Keyword = "life insurance", MatchType = KeywordMatchType.Contains, Category = "Life", ScoreBoost = 25, IsActive = true, CreatedAt = DateTime.UtcNow },
            new KeywordRule { Keyword = "health insurance", MatchType = KeywordMatchType.Contains, Category = "Life", ScoreBoost = 20, IsActive = true, CreatedAt = DateTime.UtcNow },
            new KeywordRule { Keyword = "flood insurance", MatchType = KeywordMatchType.Contains, Category = "Home", ScoreBoost = 20, IsActive = true, CreatedAt = DateTime.UtcNow },
            new KeywordRule { Keyword = "renters insurance", MatchType = KeywordMatchType.Contains, Category = "Home", ScoreBoost = 15, IsActive = true, CreatedAt = DateTime.UtcNow },
            new KeywordRule { Keyword = "commercial liability", MatchType = KeywordMatchType.Contains, Category = "Auto", ScoreBoost = 25, IsActive = true, CreatedAt = DateTime.UtcNow },
            new KeywordRule { Keyword = "umbrella insurance", MatchType = KeywordMatchType.Contains, Category = "Home", ScoreBoost = 20, IsActive = true, CreatedAt = DateTime.UtcNow },
            new KeywordRule { Keyword = "workers comp", MatchType = KeywordMatchType.Contains, Category = "Auto", ScoreBoost = 25, IsActive = true, CreatedAt = DateTime.UtcNow },
            new KeywordRule { Keyword = "coverage", MatchType = KeywordMatchType.Contains, Category = "General", ScoreBoost = 5, IsActive = true, CreatedAt = DateTime.UtcNow },
            new KeywordRule { Keyword = "premiums", MatchType = KeywordMatchType.Contains, Category = "General", ScoreBoost = 10, IsActive = true, CreatedAt = DateTime.UtcNow },
        };
    }
}
