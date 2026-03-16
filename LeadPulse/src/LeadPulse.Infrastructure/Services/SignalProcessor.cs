using System.Text.RegularExpressions;
using LeadPulse.Application.Interfaces;
using LeadPulse.Domain.Entities.Tenant;
using LeadPulse.Domain.Enums;
using LeadPulse.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace LeadPulse.Infrastructure.Services;

public class SignalProcessor : ISignalProcessor
{
    private readonly TenantDbContextFactory _tenantDbFactory;
    private readonly IKeywordMatchEngine _matchEngine;
    private readonly ILogger<SignalProcessor> _logger;

    public SignalProcessor(
        TenantDbContextFactory tenantDbFactory,
        IKeywordMatchEngine matchEngine,
        ILogger<SignalProcessor> logger)
    {
        _tenantDbFactory = tenantDbFactory;
        _matchEngine = matchEngine;
        _logger = logger;
    }

    public async Task ProcessSignalsAsync(int tenantId)
    {
        await using var db = await _tenantDbFactory.CreateContextAsync(tenantId);

        // Get unprocessed signals (no keyword matches yet)
        var unprocessedSignals = await db.Signals
            .Where(s => !s.KeywordMatches.Any())
            .OrderBy(s => s.DetectedAt)
            .Take(500)
            .ToListAsync();

        if (unprocessedSignals.Count == 0)
        {
            _logger.LogInformation("No unprocessed signals for tenant {TenantId}", tenantId);
            return;
        }

        var activeRules = await db.KeywordRules
            .Where(k => k.IsActive)
            .ToListAsync();

        if (activeRules.Count == 0)
        {
            _logger.LogInformation("No active keyword rules for tenant {TenantId}", tenantId);
            return;
        }

        _logger.LogInformation("Processing {Count} signals against {Rules} keyword rules for tenant {TenantId}",
            unprocessedSignals.Count, activeRules.Count, tenantId);

        // Signal-level dedup: skip signals whose normalized content matches an already-processed signal
        var seenContentHashes = new HashSet<string>();
        // Load content hashes of already-processed signals (those with keyword matches)
        var existingHashes = await db.Signals
            .Where(s => s.KeywordMatches.Any())
            .Select(s => s.PostContent)
            .ToListAsync();
        foreach (var content in existingHashes)
            seenContentHashes.Add(NormalizeContentForDedup(content));

        // Batch-aware prospect dedup: track prospects created in this batch
        var batchProspects = new Dictionary<string, Prospect>(StringComparer.OrdinalIgnoreCase);

        foreach (var signal in unprocessedSignals)
        {
            // Fix generic author names on the signal itself
            FixGenericAuthorName(signal);

            // Skip duplicate signals (same normalized content already processed)
            var contentHash = NormalizeContentForDedup(signal.PostContent);
            if (!seenContentHashes.Add(contentHash))
            {
                _logger.LogDebug("Skipping duplicate signal {SignalId} (content already processed)", signal.Id);
                continue;
            }

            var matches = _matchEngine.FindMatches(signal.PostContent, activeRules, signal.Platform);

            if (matches.Count == 0) continue;

            // Store keyword matches
            foreach (var match in matches)
            {
                db.SignalKeywordMatches.Add(new SignalKeywordMatch
                {
                    SignalId = signal.Id,
                    KeywordRuleId = match.KeywordRuleId,
                    MatchScore = match.MatchScore,
                    MatchedText = match.MatchedText
                });
            }

            // Update hit counts
            foreach (var match in matches)
            {
                var rule = activeRules.First(r => r.Id == match.KeywordRuleId);
                rule.HitCount30d++;
            }

            // Create or update prospect (batch-aware)
            await CreateOrUpdateProspect(db, signal, matches, batchProspects);
        }

        await db.SaveChangesAsync();

        _logger.LogInformation("Signal processing complete for tenant {TenantId}", tenantId);
    }

    public async Task<int> FixGenericAuthorNamesAsync(int tenantId)
    {
        await using var db = await _tenantDbFactory.CreateContextAsync(tenantId);

        var signals = await db.Signals
            .Where(s => s.AuthorName == "Nextdoor Neighbor" ||
                        s.AuthorName == "Unknown" ||
                        s.AuthorName == "Anonymous" ||
                        s.AuthorName == "Neighbor" ||
                        s.AuthorName == "Community Member" ||
                        s.AuthorName == null)
            .ToListAsync();

        var fixedCount = 0;
        foreach (var signal in signals)
        {
            var extracted = ExtractAuthorFromContent(signal.PostContent);
            if (extracted != null && extracted != signal.AuthorName)
            {
                signal.AuthorName = extracted;
                fixedCount++;
            }
        }

        if (fixedCount > 0)
            await db.SaveChangesAsync();

        _logger.LogInformation("Fixed {Count} generic author names for tenant {TenantId}", fixedCount, tenantId);
        return fixedCount;
    }

    public async Task<int> BackfillProspectLocationsAsync(int tenantId)
    {
        await using var db = await _tenantDbFactory.CreateContextAsync(tenantId);

        // Get prospects without city/state that have linked Nextdoor signals
        var prospects = await db.Prospects
            .Include(p => p.ProspectSignals)
                .ThenInclude(ps => ps.Signal)
            .Where(p => (p.City == null || p.City == "") && p.Platform == "Nextdoor")
            .ToListAsync();

        var fixedCount = 0;
        foreach (var prospect in prospects)
        {
            var signal = prospect.ProspectSignals.FirstOrDefault()?.Signal;
            if (signal == null) continue;

            var (city, state) = ExtractLocationFromContent(signal.PostContent, signal.Platform);
            if (city != null || state != null)
            {
                if (city != null) prospect.City = city;
                if (state != null) prospect.State = state;
                prospect.UpdatedAt = DateTime.UtcNow;
                fixedCount++;
            }
        }

        if (fixedCount > 0)
            await db.SaveChangesAsync();

        _logger.LogInformation("Backfilled location for {Count} prospects in tenant {TenantId}", fixedCount, tenantId);
        return fixedCount;
    }

    private static readonly HashSet<string> GenericNames = new(StringComparer.OrdinalIgnoreCase)
    {
        "Unknown", "Nextdoor Neighbor", "Anonymous", "Neighbor", "Community Member"
    };

    /// <summary>
    /// Replace generic/placeholder author names on the signal with the real name extracted from content.
    /// </summary>
    private static void FixGenericAuthorName(Signal signal)
    {
        var name = signal.AuthorName;
        if (string.IsNullOrEmpty(name) || GenericNames.Contains(name))
        {
            var extracted = ExtractAuthorFromContent(signal.PostContent);
            if (extracted != null)
            {
                signal.AuthorName = extracted;
            }
        }
    }

    private static async Task CreateOrUpdateProspect(
        TenantDbContext db, Signal signal, List<KeywordMatchResult> matches,
        Dictionary<string, Prospect> batchProspects)
    {
        // Try to deduplicate by author name + platform
        // Skip dedup for generic/placeholder names — each signal should be its own prospect
        Prospect? existing = null;
        var dedupKey = $"{signal.AuthorName}|{signal.Platform}";

        if (!string.IsNullOrEmpty(signal.AuthorName) && !GenericNames.Contains(signal.AuthorName))
        {
            // Check batch-local prospects first (not yet committed to DB)
            if (batchProspects.TryGetValue(dedupKey, out var batchProspect))
            {
                existing = batchProspect;
            }
            else
            {
                existing = await db.Prospects
                    .Include(p => p.ProspectSignals)
                    .FirstOrDefaultAsync(p =>
                        p.Name == signal.AuthorName &&
                        p.Platform == signal.Platform);
            }
        }

        var prospectName = signal.AuthorName ?? "Unknown";

        var compositeScore = CalculateCompositeScore(matches, signal);
        var category = DetermineCategory(matches);
        var urgency = DetermineUrgency(compositeScore);

        // Extract location from post content (Nextdoor posts have location lines)
        var (city, state) = ExtractLocationFromContent(signal.PostContent, signal.Platform);

        if (existing != null)
        {
            // Update existing prospect — keep the higher score
            if (compositeScore > existing.CompositeScore)
                existing.CompositeScore = compositeScore;

            existing.Urgency = urgency;
            if (category != null) existing.Category = category;
            existing.SignalSnippet = Truncate(signal.PostContent, 500);
            existing.UpdatedAt = DateTime.UtcNow;

            // Fill in location if not already set
            if (string.IsNullOrEmpty(existing.City) && city != null) existing.City = city;
            if (string.IsNullOrEmpty(existing.State) && state != null) existing.State = state;

            // Link signal
            if (existing.ProspectSignals == null || !existing.ProspectSignals.Any(ps => ps.SignalId == signal.Id))
            {
                db.ProspectSignals.Add(new ProspectSignal
                {
                    ProspectId = existing.Id,
                    SignalId = signal.Id
                });
            }
        }
        else
        {
            var prospect = new Prospect
            {
                Name = prospectName,
                LinkedInUrl = signal.AuthorProfileUrl,
                CompositeScore = compositeScore,
                Urgency = urgency,
                Category = category,
                Platform = signal.Platform,
                City = city,
                State = state,
                SignalSnippet = Truncate(signal.PostContent, 500),
                CreatedAt = DateTime.UtcNow
            };

            db.Prospects.Add(prospect);
            await db.SaveChangesAsync(); // Get the prospect Id

            db.ProspectSignals.Add(new ProspectSignal
            {
                ProspectId = prospect.Id,
                SignalId = signal.Id
            });

            // Track in batch for dedup within this processing run
            if (!string.IsNullOrEmpty(signal.AuthorName) && !GenericNames.Contains(signal.AuthorName))
            {
                prospect.ProspectSignals = new List<ProspectSignal>();
                batchProspects[dedupKey] = prospect;
            }
        }
    }

    /// <summary>
    /// Composite score = sum of keyword boosts + recency bonus + match quality bonus.
    /// Capped at 100.
    /// </summary>
    public static int CalculateCompositeScore(List<KeywordMatchResult> matches, Signal signal)
    {
        // Base: sum of keyword score boosts
        var keywordScore = matches.Sum(m => m.ScoreBoost);

        // Recency bonus: posts within 24h get +15, within 72h get +10, within 7d get +5
        var recencyBonus = 0;
        if (signal.PostDate.HasValue)
        {
            var age = DateTime.UtcNow - signal.PostDate.Value;
            recencyBonus = age.TotalHours switch
            {
                <= 24 => 15,
                <= 72 => 10,
                <= 168 => 5,
                _ => 0
            };
        }

        // Match quality bonus: average match score / 10
        var avgMatchScore = matches.Average(m => (double)m.MatchScore);
        var qualityBonus = (int)(avgMatchScore / 10);

        var total = keywordScore + recencyBonus + qualityBonus;
        return Math.Min(total, 100);
    }

    private static Urgency DetermineUrgency(int score)
    {
        return score switch
        {
            >= 70 => Urgency.Hot,
            >= 40 => Urgency.Warm,
            _ => Urgency.Cool
        };
    }

    private static string? DetermineCategory(List<KeywordMatchResult> matches)
    {
        // Most common category from matches
        return matches
            .Where(m => !string.IsNullOrEmpty(m.Category))
            .GroupBy(m => m.Category)
            .OrderByDescending(g => g.Count())
            .Select(g => g.Key)
            .FirstOrDefault();
    }

    private static string Truncate(string text, int maxLength)
    {
        return text.Length <= maxLength ? text : text[..maxLength] + "...";
    }

    /// <summary>
    /// Try to extract a real author name from Nextdoor-style post content.
    /// Nextdoor posts typically start with a single letter initial, then the full name on the next line.
    /// E.g.: "L\nLinda Whitehouse\nCrow Canyon..." or "Candy V.\nDel Amigo..."
    /// </summary>
    private static string? ExtractAuthorFromContent(string content)
    {
        if (string.IsNullOrEmpty(content)) return null;

        var lines = content.Split('\n', StringSplitOptions.RemoveEmptyEntries);
        if (lines.Length < 2) return null;

        // Pattern 1: Single char initial on line 0, full name on line 1
        // e.g. "L\nLinda Whitehouse\nCrow Canyon..."
        if (lines[0].Trim().Length <= 2)
        {
            var candidate = lines[1].Trim();
            // Name should be 2-40 chars, contain a space or period, and not look like a location
            if (candidate.Length >= 2 && candidate.Length <= 40 &&
                (candidate.Contains(' ') || candidate.Contains('.')) &&
                !candidate.Contains("·") && !candidate.Contains(','))
            {
                return candidate;
            }
        }

        // Pattern 2: Name with period/initial on line 0
        // e.g. "Candy V.\nDel Amigo..."
        var firstLine = lines[0].Trim();
        if (firstLine.Length >= 2 && firstLine.Length <= 40 &&
            (firstLine.Contains(' ') || firstLine.Contains('.')) &&
            !firstLine.Contains("·") && !firstLine.Contains(',') &&
            !firstLine.Any(char.IsDigit))
        {
            return firstLine;
        }

        return null;
    }

    /// <summary>
    /// Extract location (city, state) from Nextdoor post content.
    /// Nextdoor posts have a location line like "Pleasanton, CA · 1 Mar" or "Walnut Creek, CA · 16 Feb"
    /// or a neighborhood line like "Del Amigo · 16 hr ago" (no state, but can still use as city).
    /// </summary>
    private static (string? city, string? state) ExtractLocationFromContent(string content, string platform)
    {
        if (string.IsNullOrEmpty(content) || !platform.Equals("Nextdoor", StringComparison.OrdinalIgnoreCase))
            return (null, null);

        var lines = content.Split('\n', StringSplitOptions.RemoveEmptyEntries);

        // Find the location line — it's the one containing "·" (middle dot) near the top (lines 0-4)
        for (int i = 0; i < Math.Min(lines.Length, 5); i++)
        {
            var line = lines[i].Trim();
            var dotIdx = line.IndexOf('·');
            if (dotIdx < 0) continue;

            var locationPart = line[..dotIdx].Trim();
            if (string.IsNullOrEmpty(locationPart) || locationPart.Length < 2) continue;

            // Check for "City, ST" pattern (e.g., "Pleasanton, CA" or "Walnut Creek, CA")
            var cityStateMatch = Regex.Match(locationPart, @"^(.+),\s*([A-Z]{2})$");
            if (cityStateMatch.Success)
            {
                var city = cityStateMatch.Groups[1].Value.Trim();
                var state = cityStateMatch.Groups[2].Value.Trim();
                if (UsStateAbbreviations.Contains(state))
                    return (city, state);
            }

            // Neighborhood name only (e.g., "Del Amigo", "Northgate", "Seven Hills Rd")
            // Use as city if it doesn't look like a person's name (should not be the author line)
            if (locationPart.Length <= 50 && !locationPart.Contains('.') && i >= 1)
            {
                return (locationPart, null);
            }
        }

        return (null, null);
    }

    /// <summary>
    /// Normalize post content for dedup comparison.
    /// Strips the leading single-char initial line that Nextdoor sometimes includes,
    /// so "L\nLitzy Bruno\n..." and "Litzy Bruno\n..." are treated as the same post.
    /// </summary>
    private static string NormalizeContentForDedup(string content)
    {
        if (string.IsNullOrEmpty(content)) return string.Empty;

        var text = content.Trim();

        // Strip leading single-char initial + newline (e.g., "L\nLitzy Bruno\n..." → "Litzy Bruno\n...")
        if (text.Length >= 2 && text[1] == '\n' && char.IsLetter(text[0]))
        {
            text = text[2..];
        }

        // Normalize whitespace for comparison
        return Regex.Replace(text, @"\s+", " ").Trim().ToLowerInvariant();
    }

    /// <summary>
    /// Clean up existing duplicate signals and merge duplicate prospects.
    /// Call this once to fix data that was already duplicated.
    /// </summary>
    public async Task<(int duplicateSignalsRemoved, int duplicateProspectsMerged)> DeduplicateExistingAsync(int tenantId)
    {
        await using var db = await _tenantDbFactory.CreateContextAsync(tenantId);

        // --- 1. Remove duplicate signals (keep the earliest, remove later duplicates) ---
        var allSignals = await db.Signals
            .OrderBy(s => s.DetectedAt)
            .ToListAsync();

        var seenContent = new Dictionary<string, long>(); // normalized content → kept signal ID
        var duplicateSignalIds = new List<long>();

        foreach (var signal in allSignals)
        {
            var normalized = NormalizeContentForDedup(signal.PostContent);
            if (seenContent.TryGetValue(normalized, out var keptId))
            {
                duplicateSignalIds.Add(signal.Id);
            }
            else
            {
                seenContent[normalized] = signal.Id;
            }
        }

        if (duplicateSignalIds.Count > 0)
        {
            // Remove keyword matches and prospect-signal links for duplicate signals
            var dupMatches = await db.SignalKeywordMatches
                .Where(m => duplicateSignalIds.Contains(m.SignalId))
                .ToListAsync();
            db.SignalKeywordMatches.RemoveRange(dupMatches);

            var dupProspectSignals = await db.ProspectSignals
                .Where(ps => duplicateSignalIds.Contains(ps.SignalId))
                .ToListAsync();
            db.ProspectSignals.RemoveRange(dupProspectSignals);

            var dupSignals = await db.Signals
                .Where(s => duplicateSignalIds.Contains(s.Id))
                .ToListAsync();
            db.Signals.RemoveRange(dupSignals);

            await db.SaveChangesAsync();
            _logger.LogInformation("Removed {Count} duplicate signals for tenant {TenantId}",
                duplicateSignalIds.Count, tenantId);
        }

        // --- 2. Merge duplicate prospects (same name + platform) ---
        var allProspects = await db.Prospects
            .Include(p => p.ProspectSignals)
            .OrderBy(p => p.CreatedAt)
            .ToListAsync();

        var prospectGroups = allProspects
            .Where(p => !string.IsNullOrEmpty(p.Name) && !GenericNames.Contains(p.Name))
            .GroupBy(p => $"{p.Name}|{p.Platform}", StringComparer.OrdinalIgnoreCase)
            .Where(g => g.Count() > 1)
            .ToList();

        int mergedCount = 0;
        foreach (var group in prospectGroups)
        {
            var keep = group.First(); // keep earliest
            var duplicates = group.Skip(1).ToList();

            foreach (var dup in duplicates)
            {
                // Keep the higher score
                if (dup.CompositeScore > keep.CompositeScore)
                    keep.CompositeScore = dup.CompositeScore;

                // Fill in missing fields from duplicate
                if (string.IsNullOrEmpty(keep.Phone) && !string.IsNullOrEmpty(dup.Phone))
                    keep.Phone = dup.Phone;
                if (string.IsNullOrEmpty(keep.Email) && !string.IsNullOrEmpty(dup.Email))
                    keep.Email = dup.Email;
                if (string.IsNullOrEmpty(keep.City) && !string.IsNullOrEmpty(dup.City))
                    keep.City = dup.City;
                if (string.IsNullOrEmpty(keep.State) && !string.IsNullOrEmpty(dup.State))
                    keep.State = dup.State;

                // Move signal links from duplicate to kept prospect
                var signalLinks = await db.ProspectSignals
                    .Where(ps => ps.ProspectId == dup.Id)
                    .ToListAsync();
                foreach (var link in signalLinks)
                {
                    // Only move if not already linked to kept prospect
                    var alreadyLinked = await db.ProspectSignals
                        .AnyAsync(ps => ps.ProspectId == keep.Id && ps.SignalId == link.SignalId);
                    if (!alreadyLinked)
                    {
                        link.ProspectId = keep.Id;
                    }
                    else
                    {
                        db.ProspectSignals.Remove(link);
                    }
                }

                // Remove daily list entries for the duplicate
                var dailyListEntries = await db.DailyListItems
                    .Where(dlp => dlp.ProspectId == dup.Id)
                    .ToListAsync();
                db.DailyListItems.RemoveRange(dailyListEntries);

                db.Prospects.Remove(dup);
                mergedCount++;
            }

            keep.UpdatedAt = DateTime.UtcNow;
        }

        if (mergedCount > 0)
            await db.SaveChangesAsync();

        _logger.LogInformation("Merged {Count} duplicate prospects for tenant {TenantId}", mergedCount, tenantId);

        return (duplicateSignalIds.Count, mergedCount);
    }

    private static readonly HashSet<string> UsStateAbbreviations = new()
    {
        "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS",
        "KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY",
        "NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV",
        "WI","WY","DC"
    };
}
