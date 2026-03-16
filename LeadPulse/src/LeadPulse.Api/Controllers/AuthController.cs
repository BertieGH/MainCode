using LeadPulse.Application.DTOs;
using LeadPulse.Application.Interfaces;
using Microsoft.AspNetCore.Mvc;

namespace LeadPulse.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class AuthController : ControllerBase
{
    private readonly IAuthService _authService;

    public AuthController(IAuthService authService)
    {
        _authService = authService;
    }

    [HttpPost("platform/login")]
    public async Task<IActionResult> PlatformLogin([FromBody] PlatformLoginRequest request)
    {
        var result = await _authService.LoginPlatformUserAsync(request.Email, request.Password);

        if (!result.Success)
            return Unauthorized(new { error = result.Error });

        return Ok(result);
    }

    [HttpPost("tenant/login")]
    public async Task<IActionResult> TenantLogin([FromBody] TenantLoginRequest request)
    {
        var result = await _authService.LoginTenantUserAsync(request.TenantId, request.Email, request.Password);

        if (!result.Success)
        {
            if (result.Error == "Tenant suspended")
                return StatusCode(403, new { error = result.Error });

            return Unauthorized(new { error = result.Error });
        }

        return Ok(result);
    }
}
