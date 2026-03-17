using System.Text;
using LeadPulse.Application.Interfaces;
using LeadPulse.Domain.Authorization;
using LeadPulse.Infrastructure.Authorization;
using LeadPulse.Infrastructure.Data;
using LeadPulse.Infrastructure.PlatformAdapters;
using LeadPulse.Infrastructure.Services;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Authorization;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.IdentityModel.Tokens;

namespace LeadPulse.Infrastructure;

public static class DependencyInjection
{
    public static IServiceCollection AddInfrastructure(this IServiceCollection services, IConfiguration configuration)
    {
        // App Database (shared)
        var appConnectionString = configuration.GetConnectionString("AppDb")
            ?? throw new InvalidOperationException("AppDb connection string not configured");

        services.AddDbContext<AppDbContext>(options =>
            options.UseMySql(appConnectionString, ServerVersion.AutoDetect(appConnectionString)));

        // Tenant context (per-request scope)
        services.AddScoped<ITenantContext, TenantContext>();

        // Services
        services.AddScoped<ITenantDbResolver, TenantDbResolver>();
        services.AddScoped<TenantDbContextFactory>();
        services.AddScoped<IPasswordHasher, PasswordHasher>();
        services.AddScoped<JwtTokenService>();
        services.AddScoped<IAuthService, AuthService>();
        services.AddScoped<ITenantProvisioningService, TenantProvisioningService>();
        services.AddScoped<IMigrationOrchestrator, MigrationOrchestrator>();
        services.AddScoped<IMfaService, MfaService>();
        services.AddSingleton<IEncryptionService, EncryptionService>();
        services.AddScoped<ISyncService, SyncService>();
        services.AddSingleton<IKeywordMatchEngine, KeywordMatchEngine>();
        services.AddScoped<ISignalProcessor, SignalProcessor>();
        services.AddScoped<IDailyListGenerator, DailyListGenerator>();
        services.AddScoped<IntentAnalyzerFactory>();
        services.AddHttpClient();
        services.AddScoped<ContactLookupService>();

        // Platform adapters
        services.AddScoped<ISocialPlatformAdapter, LinkedInAdapter>();
        services.AddScoped<ISocialPlatformAdapter, FacebookAdapter>();
        services.AddScoped<ISocialPlatformAdapter, NextdoorAdapter>();
        services.AddScoped<ISocialPlatformAdapter, XTwitterAdapter>();

        // Reddit adapter with HttpClient
        services.AddHttpClient<RedditAdapter>(client =>
        {
            client.DefaultRequestHeaders.Add("User-Agent", "LeadPulse/1.0 (Insurance Lead Generation)");
            client.Timeout = TimeSpan.FromSeconds(30);
        });
        services.AddScoped<ISocialPlatformAdapter>(provider => provider.GetRequiredService<RedditAdapter>());

        // Register TenantDbContext as scoped — resolved per-request via factory
        services.AddScoped<TenantDbContext>(provider =>
        {
            var tenantContext = provider.GetRequiredService<ITenantContext>();
            if (!tenantContext.TenantId.HasValue)
            {
                // Return a context pointing at app DB as fallback (won't be used for tenant queries)
                var options = new DbContextOptionsBuilder<TenantDbContext>()
                    .UseMySql(appConnectionString, ServerVersion.AutoDetect(appConnectionString))
                    .Options;
                return new TenantDbContext(options);
            }

            var factory = provider.GetRequiredService<TenantDbContextFactory>();
            return factory.CreateContextAsync(tenantContext.TenantId.Value).GetAwaiter().GetResult();
        });

        // JWT Authentication
        var jwtSecret = configuration["Jwt:Secret"]
            ?? throw new InvalidOperationException("JWT secret not configured");

        services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
            .AddJwtBearer(options =>
            {
                options.TokenValidationParameters = new TokenValidationParameters
                {
                    ValidateIssuer = true,
                    ValidateAudience = true,
                    ValidateLifetime = true,
                    ValidateIssuerSigningKey = true,
                    ValidIssuer = configuration["Jwt:Issuer"] ?? "LeadPulse",
                    ValidAudience = configuration["Jwt:Audience"] ?? "LeadPulse",
                    IssuerSigningKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(jwtSecret)),
                    ClockSkew = TimeSpan.Zero
                };
            });

        // Permission-based authorization
        services.AddScoped<IAuthorizationHandler, PermissionAuthorizationHandler>();

        services.AddAuthorization(options =>
        {
            foreach (var permission in Permissions.All)
            {
                options.AddPolicy(permission, policy =>
                    policy.Requirements.Add(new PermissionRequirement(permission)));
            }
        });

        return services;
    }
}
