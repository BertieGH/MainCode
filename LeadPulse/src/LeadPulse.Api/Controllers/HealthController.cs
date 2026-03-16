using LeadPulse.Infrastructure.Data;
using Microsoft.AspNetCore.Mvc;

namespace LeadPulse.Api.Controllers;

[ApiController]
[Route("[controller]")]
public class HealthController : ControllerBase
{
    private readonly AppDbContext _appDb;

    public HealthController(AppDbContext appDb)
    {
        _appDb = appDb;
    }

    [HttpGet]
    public async Task<IActionResult> Get()
    {
        try
        {
            await _appDb.Database.CanConnectAsync();
            return Ok(new { status = "healthy", database = "connected", timestamp = DateTime.UtcNow });
        }
        catch (Exception ex)
        {
            return StatusCode(503, new { status = "unhealthy", database = "disconnected", error = ex.Message });
        }
    }
}
