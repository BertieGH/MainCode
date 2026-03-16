using System.Net;
using System.Net.Http.Json;
using FluentAssertions;

namespace LeadPulse.Tests.M9_Integration;

public class AuthEndpointTests : IClassFixture<CustomWebApplicationFactory>
{
    private readonly HttpClient _client;

    public AuthEndpointTests(CustomWebApplicationFactory factory)
    {
        _client = factory.CreateClient();
    }

    [Fact]
    public async Task PlatformLogin_InvalidCredentials_ReturnsUnauthorized()
    {
        var response = await _client.PostAsJsonAsync("/api/auth/platform/login",
            new { email = "nonexistent@test.com", password = "wrong" });
        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }

    [Fact]
    public async Task TenantLogin_InvalidCredentials_ReturnsUnauthorized()
    {
        var response = await _client.PostAsJsonAsync("/api/auth/tenant/login",
            new { tenantId = 999, email = "nonexistent@test.com", password = "wrong" });
        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }

    [Fact]
    public async Task ProtectedEndpoint_NoToken_ReturnsUnauthorized()
    {
        var response = await _client.GetAsync("/api/tenants");
        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }

    [Fact]
    public async Task ProspectsEndpoint_NoToken_ReturnsUnauthorized()
    {
        var response = await _client.GetAsync("/api/prospects");
        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }
}
