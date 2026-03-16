using LeadPulse.Application.DTOs;

namespace LeadPulse.Application.Interfaces;

public interface IAuthService
{
    Task<AuthResult> LoginPlatformUserAsync(string email, string password);
    Task<AuthResult> LoginTenantUserAsync(int tenantId, string email, string password);
}
