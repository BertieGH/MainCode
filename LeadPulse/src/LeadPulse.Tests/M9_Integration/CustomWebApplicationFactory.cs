using LeadPulse.Infrastructure.Data;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace LeadPulse.Tests.M9_Integration;

public class CustomWebApplicationFactory : WebApplicationFactory<Program>
{
    private readonly string _dbId = Guid.NewGuid().ToString();

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.ConfigureServices(services =>
        {
            // Remove existing DbContext registrations
            var descriptorsToRemove = services
                .Where(d => d.ServiceType == typeof(DbContextOptions<AppDbContext>) ||
                           d.ServiceType == typeof(DbContextOptions<TenantDbContext>) ||
                           d.ServiceType == typeof(AppDbContext) ||
                           d.ServiceType == typeof(TenantDbContext))
                .ToList();

            foreach (var descriptor in descriptorsToRemove)
                services.Remove(descriptor);

            // Add in-memory AppDbContext
            services.AddDbContext<AppDbContext>(options =>
                options.UseInMemoryDatabase("TestAppDb_" + _dbId));

            // Add in-memory TenantDbContext
            services.AddScoped<TenantDbContext>(_ =>
            {
                var options = new DbContextOptionsBuilder<TenantDbContext>()
                    .UseInMemoryDatabase("TestTenantDb_" + _dbId)
                    .Options;
                return new TenantDbContext(options);
            });
        });

        builder.UseEnvironment("Testing");
    }
}
