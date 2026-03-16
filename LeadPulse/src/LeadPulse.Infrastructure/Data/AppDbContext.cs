using LeadPulse.Domain.Entities.App;
using Microsoft.EntityFrameworkCore;

namespace LeadPulse.Infrastructure.Data;

public class AppDbContext : DbContext
{
    public AppDbContext(DbContextOptions<AppDbContext> options) : base(options) { }

    public DbSet<Tenant> Tenants => Set<Tenant>();
    public DbSet<TenantDbMapping> TenantDbMappings => Set<TenantDbMapping>();
    public DbSet<SubscriptionPlan> SubscriptionPlans => Set<SubscriptionPlan>();
    public DbSet<PlatformUser> PlatformUsers => Set<PlatformUser>();
    public DbSet<BillingRecord> BillingRecords => Set<BillingRecord>();
    public DbSet<PlatformAuditLog> PlatformAuditLogs => Set<PlatformAuditLog>();
    public DbSet<ApiRateLimit> ApiRateLimits => Set<ApiRateLimit>();
    public DbSet<GlobalSetting> GlobalSettings => Set<GlobalSetting>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);

        modelBuilder.Entity<Tenant>(entity =>
        {
            entity.HasIndex(e => e.Slug).IsUnique();
            entity.Property(e => e.Status).HasConversion<string>();
            entity.HasOne(e => e.Plan).WithMany().HasForeignKey(e => e.PlanId);
            entity.HasOne(e => e.DbMapping).WithOne(e => e.Tenant).HasForeignKey<TenantDbMapping>(e => e.TenantId);
        });

        modelBuilder.Entity<TenantDbMapping>(entity =>
        {
            entity.HasIndex(e => e.TenantId).IsUnique();
        });

        modelBuilder.Entity<PlatformUser>(entity =>
        {
            entity.HasIndex(e => e.Email).IsUnique();
            entity.Property(e => e.Status).HasConversion<string>();
        });

        modelBuilder.Entity<BillingRecord>(entity =>
        {
            entity.Property(e => e.Status).HasConversion<string>();
            entity.HasOne(e => e.Tenant).WithMany(e => e.BillingRecords).HasForeignKey(e => e.TenantId);
        });

        modelBuilder.Entity<ApiRateLimit>(entity =>
        {
            entity.HasIndex(e => new { e.TenantId, e.Date }).IsUnique();
            entity.HasOne(e => e.Tenant).WithMany().HasForeignKey(e => e.TenantId);
        });

        modelBuilder.Entity<GlobalSetting>(entity =>
        {
            entity.HasKey(e => e.Key);
        });
    }
}
