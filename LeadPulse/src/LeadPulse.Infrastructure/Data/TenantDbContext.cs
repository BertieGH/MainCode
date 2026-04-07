using LeadPulse.Domain.Entities.Tenant;
using Microsoft.EntityFrameworkCore;

namespace LeadPulse.Infrastructure.Data;

public class TenantDbContext : DbContext
{
    public TenantDbContext(DbContextOptions<TenantDbContext> options) : base(options) { }

    public DbSet<User> Users => Set<User>();
    public DbSet<UserInvitation> UserInvitations => Set<UserInvitation>();
    public DbSet<SocialAccount> SocialAccounts => Set<SocialAccount>();
    public DbSet<MonitoredGroup> MonitoredGroups => Set<MonitoredGroup>();
    public DbSet<SyncJob> SyncJobs => Set<SyncJob>();
    public DbSet<KeywordRule> KeywordRules => Set<KeywordRule>();
    public DbSet<Signal> Signals => Set<Signal>();
    public DbSet<SignalKeywordMatch> SignalKeywordMatches => Set<SignalKeywordMatch>();
    public DbSet<Prospect> Prospects => Set<Prospect>();
    public DbSet<ProspectSignal> ProspectSignals => Set<ProspectSignal>();
    public DbSet<Strategy> Strategies => Set<Strategy>();
    public DbSet<DailyList> DailyLists => Set<DailyList>();
    public DbSet<DailyListItem> DailyListItems => Set<DailyListItem>();
    public DbSet<CallLog> CallLogs => Set<CallLog>();
    public DbSet<ActivityLog> ActivityLogs => Set<ActivityLog>();
    public DbSet<AuditLog> AuditLogs => Set<AuditLog>();
    public DbSet<ApiUsageLog> ApiUsageLogs => Set<ApiUsageLog>();
    public DbSet<AiSettings> AiSettings => Set<AiSettings>();
    public DbSet<EnrichmentSettings> EnrichmentSettings => Set<EnrichmentSettings>();
    public DbSet<LinkedInPost> LinkedInPosts => Set<LinkedInPost>();
    public DbSet<LinkedInScraperSettings> LinkedInScraperSettings => Set<LinkedInScraperSettings>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);

        modelBuilder.Entity<User>(entity =>
        {
            entity.HasIndex(e => e.Email).IsUnique();
            entity.Property(e => e.Role).HasConversion<string>();
            entity.Property(e => e.Status).HasConversion<string>();
        });

        modelBuilder.Entity<UserInvitation>(entity =>
        {
            entity.HasIndex(e => e.Token).IsUnique();
            entity.Property(e => e.Role).HasConversion<string>();
            entity.HasOne(e => e.InvitedBy).WithMany().HasForeignKey(e => e.InvitedByUserId);
        });

        modelBuilder.Entity<SocialAccount>(entity =>
        {
            entity.Property(e => e.Status).HasConversion<string>();
        });

        modelBuilder.Entity<MonitoredGroup>(entity =>
        {
            entity.HasOne(e => e.SocialAccount).WithMany(e => e.MonitoredGroups)
                .HasForeignKey(e => e.SocialAccountId).OnDelete(DeleteBehavior.Cascade);
        });

        modelBuilder.Entity<SyncJob>(entity =>
        {
            entity.Property(e => e.Status).HasConversion<string>();
            entity.HasOne(e => e.SocialAccount).WithMany(e => e.SyncJobs)
                .HasForeignKey(e => e.SocialAccountId);
        });

        modelBuilder.Entity<KeywordRule>(entity =>
        {
            entity.Property(e => e.MatchType).HasConversion<string>();
        });

        modelBuilder.Entity<Signal>(entity =>
        {
            entity.HasOne(e => e.SocialAccount).WithMany().HasForeignKey(e => e.SocialAccountId);
            entity.Property(e => e.IntentCategory).HasMaxLength(50);
            entity.Property(e => e.Sentiment).HasMaxLength(20);
            entity.Property(e => e.AiSummary).HasMaxLength(500);
            entity.Property(e => e.AiProvider).HasMaxLength(20);
        });

        modelBuilder.Entity<SignalKeywordMatch>(entity =>
        {
            entity.HasOne(e => e.Signal).WithMany(e => e.KeywordMatches).HasForeignKey(e => e.SignalId);
            entity.HasOne(e => e.KeywordRule).WithMany().HasForeignKey(e => e.KeywordRuleId);
        });

        modelBuilder.Entity<Prospect>(entity =>
        {
            entity.Property(e => e.Urgency).HasConversion<string>();
            entity.Property(e => e.EnrichmentStatus).HasConversion<string>();
            entity.Property(e => e.Status).HasConversion<string>();
            entity.HasOne(e => e.AssignedTo).WithMany().HasForeignKey(e => e.AssignedToUserId);
        });

        modelBuilder.Entity<ProspectSignal>(entity =>
        {
            entity.HasOne(e => e.Prospect).WithMany(e => e.ProspectSignals).HasForeignKey(e => e.ProspectId);
            entity.HasOne(e => e.Signal).WithMany().HasForeignKey(e => e.SignalId);
        });

        modelBuilder.Entity<LinkedInPost>(entity =>
        {
            entity.HasOne(e => e.Prospect).WithMany(e => e.LinkedInPosts).HasForeignKey(e => e.ProspectId);
        });

        modelBuilder.Entity<DailyList>(entity =>
        {
            entity.HasOne(e => e.Strategy).WithMany().HasForeignKey(e => e.StrategyId);
        });

        modelBuilder.Entity<DailyListItem>(entity =>
        {
            entity.Property(e => e.Status).HasConversion<string>();
            entity.HasOne(e => e.DailyList).WithMany(e => e.Items).HasForeignKey(e => e.DailyListId);
            entity.HasOne(e => e.Prospect).WithMany().HasForeignKey(e => e.ProspectId);
        });

        modelBuilder.Entity<CallLog>(entity =>
        {
            entity.Property(e => e.ContactMethod).HasConversion<string>();
            entity.HasOne(e => e.Prospect).WithMany(e => e.CallLogs).HasForeignKey(e => e.ProspectId);
            entity.HasOne(e => e.User).WithMany().HasForeignKey(e => e.UserId);
        });

        modelBuilder.Entity<ActivityLog>(entity =>
        {
            entity.HasOne(e => e.User).WithMany().HasForeignKey(e => e.UserId);
        });

        modelBuilder.Entity<AuditLog>(entity =>
        {
            entity.HasOne(e => e.User).WithMany().HasForeignKey(e => e.UserId);
        });

        modelBuilder.Entity<ApiUsageLog>(entity =>
        {
            entity.HasIndex(e => new { e.Service, e.Date }).IsUnique();
        });

        modelBuilder.Entity<AiSettings>(entity =>
        {
            entity.Property(e => e.AiProvider).HasMaxLength(20);
            entity.Property(e => e.AiModel).HasMaxLength(100);
        });

        modelBuilder.Entity<LinkedInScraperSettings>(entity =>
        {
            entity.Property(e => e.AiModel).HasMaxLength(100);
        });

        modelBuilder.Entity<EnrichmentSettings>(entity =>
        {
            entity.Property(e => e.Provider).HasMaxLength(20);
            entity.Property(e => e.Username).HasMaxLength(200);
            entity.HasIndex(e => e.Provider).IsUnique();
        });
    }
}
