using LeadPulse.Application.Interfaces;
using LeadPulse.Domain.Entities.App;
using LeadPulse.Domain.Enums;
using LeadPulse.Infrastructure;
using LeadPulse.Infrastructure.Data;
using LeadPulse.Infrastructure.Middleware;
using Microsoft.EntityFrameworkCore;
using Serilog;

var builder = WebApplication.CreateBuilder(args);

// Serilog
Log.Logger = new LoggerConfiguration()
    .ReadFrom.Configuration(builder.Configuration)
    .Enrich.FromLogContext()
    .WriteTo.Console()
    .WriteTo.File("logs/leadpulse-.log", rollingInterval: RollingInterval.Day)
    .CreateLogger();

builder.Host.UseSerilog();

// Infrastructure (DbContexts, Auth, Services)
builder.Services.AddInfrastructure(builder.Configuration);

// API
builder.Services.AddControllers();

// API Versioning
builder.Services.AddApiVersioning(options =>
{
    options.DefaultApiVersion = new Asp.Versioning.ApiVersion(1, 0);
    options.AssumeDefaultVersionWhenUnspecified = true;
    options.ReportApiVersions = true;
}).AddApiExplorer(options =>
{
    options.GroupNameFormat = "'v'VVV";
    options.SubstituteApiVersionInUrl = true;
});

// CORS
builder.Services.AddCors(options =>
{
    options.AddPolicy("AllowAngular", policy =>
    {
        policy.WithOrigins(
                builder.Configuration.GetSection("Cors:Origins").Get<string[]>() ?? new[] { "http://localhost:4200" })
            .AllowAnyHeader()
            .AllowAnyMethod()
            .AllowCredentials();
    });
});

var app = builder.Build();

// Database initialization
using (var scope = app.Services.CreateScope())
{
    var appDb = scope.ServiceProvider.GetRequiredService<AppDbContext>();
    appDb.Database.Migrate();

    // Seed default data if empty
    if (!appDb.SubscriptionPlans.Any())
    {
        appDb.SubscriptionPlans.AddRange(
            new SubscriptionPlan { Name = "Starter", MaxUsers = 3, MaxSocialAccounts = 2, MaxKeywords = 25, MaxApiCallsPerDay = 500, PriceMonthly = 49m, IsActive = true },
            new SubscriptionPlan { Name = "Professional", MaxUsers = 10, MaxSocialAccounts = 5, MaxKeywords = 100, MaxApiCallsPerDay = 2000, PriceMonthly = 149m, IsActive = true },
            new SubscriptionPlan { Name = "Enterprise", MaxUsers = 50, MaxSocialAccounts = 20, MaxKeywords = 500, MaxApiCallsPerDay = 10000, DedicatedDbServer = true, PriceMonthly = 499m, IsActive = true }
        );
        appDb.SaveChanges();
    }

    if (!appDb.PlatformUsers.Any())
    {
        var hasher = scope.ServiceProvider.GetRequiredService<IPasswordHasher>();
        appDb.PlatformUsers.Add(new PlatformUser
        {
            Email = "admin@leadpulse.com",
            PasswordHash = hasher.Hash("Admin123!"),
            FirstName = "Super",
            LastName = "Admin",
            Status = PlatformUserStatus.Active,
            CreatedAt = DateTime.UtcNow
        });
        appDb.SaveChanges();
    }
}

// Middleware pipeline
app.UseSerilogRequestLogging();
app.UseMiddleware<SecurityHeadersMiddleware>();
app.UseCors("AllowAngular");
app.UseAuthentication();
app.UseMiddleware<TenantResolutionMiddleware>();
app.UseAuthorization();
app.UseMiddleware<RateLimitingMiddleware>();
app.MapControllers();

app.Run();

// Make Program accessible for integration tests
public partial class Program { }
