using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Text;
using Microsoft.Extensions.Configuration;
using Microsoft.IdentityModel.Tokens;

namespace LeadPulse.Infrastructure.Services;

public class JwtTokenService
{
    private readonly IConfiguration _configuration;

    public JwtTokenService(IConfiguration configuration)
    {
        _configuration = configuration;
    }

    public string GenerateToken(int userId, int? tenantId, string role, string email, string? tenantName = null)
    {
        var key = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(
            _configuration["Jwt:Secret"] ?? throw new InvalidOperationException("JWT secret not configured")));

        var claims = new List<Claim>
        {
            new(ClaimTypes.NameIdentifier, userId.ToString()),
            new(ClaimTypes.Email, email),
            new(ClaimTypes.Role, role),
            new("role", role)
        };

        if (tenantId.HasValue)
            claims.Add(new Claim("tenantId", tenantId.Value.ToString()));

        if (!string.IsNullOrEmpty(tenantName))
            claims.Add(new Claim("tenantName", tenantName));

        var token = new JwtSecurityToken(
            issuer: _configuration["Jwt:Issuer"] ?? "LeadPulse",
            audience: _configuration["Jwt:Audience"] ?? "LeadPulse",
            claims: claims,
            expires: DateTime.UtcNow.AddHours(int.Parse(_configuration["Jwt:ExpiryHours"] ?? "8")),
            signingCredentials: new SigningCredentials(key, SecurityAlgorithms.HmacSha256)
        );

        return new JwtSecurityTokenHandler().WriteToken(token);
    }
}
