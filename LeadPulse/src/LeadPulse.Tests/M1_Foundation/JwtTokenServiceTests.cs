using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using FluentAssertions;
using LeadPulse.Infrastructure.Services;
using Microsoft.Extensions.Configuration;

namespace LeadPulse.Tests.M1_Foundation;

public class JwtTokenServiceTests
{
    private readonly JwtTokenService _jwtService;

    public JwtTokenServiceTests()
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Jwt:Secret"] = "LeadPulse-JWT-Secret-Key-Change-In-Production-Min32Chars!",
                ["Jwt:Issuer"] = "LeadPulse",
                ["Jwt:Audience"] = "LeadPulse",
                ["Jwt:ExpiryHours"] = "8"
            })
            .Build();

        _jwtService = new JwtTokenService(config);
    }

    [Fact]
    public void GenerateToken_ForSuperAdmin_DoesNotContainTenantId()
    {
        var token = _jwtService.GenerateToken(1, null, "SuperAdmin", "admin@leadpulse.com");

        var handler = new JwtSecurityTokenHandler();
        var jwt = handler.ReadJwtToken(token);

        jwt.Claims.Should().Contain(c => c.Type == ClaimTypes.Role && c.Value == "SuperAdmin");
        jwt.Claims.Should().NotContain(c => c.Type == "tenantId");
    }

    [Fact]
    public void GenerateToken_ForTenantUser_ContainsTenantId()
    {
        var token = _jwtService.GenerateToken(5, 142, "Agent", "agent@test.com");

        var handler = new JwtSecurityTokenHandler();
        var jwt = handler.ReadJwtToken(token);

        jwt.Claims.Should().Contain(c => c.Type == "tenantId" && c.Value == "142");
        jwt.Claims.Should().Contain(c => c.Type == "role" && c.Value == "Agent");
    }

    [Fact]
    public void GenerateToken_SetsCorrectExpiry()
    {
        var token = _jwtService.GenerateToken(1, null, "SuperAdmin", "admin@leadpulse.com");

        var handler = new JwtSecurityTokenHandler();
        var jwt = handler.ReadJwtToken(token);

        jwt.ValidTo.Should().BeCloseTo(DateTime.UtcNow.AddHours(8), TimeSpan.FromMinutes(1));
    }
}
