using LeadPulse.Application.DTOs;
using LeadPulse.Application.Interfaces;
using LeadPulse.Domain.Entities.App;
using LeadPulse.Domain.Enums;
using LeadPulse.Infrastructure.Data;
using LeadPulse.Infrastructure.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace LeadPulse.Api.Controllers;

[ApiController]
[Route("api/tenants")]
[Authorize(Roles = "SuperAdmin")]
public class TenantsController : ControllerBase
{
    private readonly AppDbContext _appDb;
    private readonly ITenantProvisioningService _provisioning;
    private readonly JwtTokenService _jwtService;
    private readonly IMigrationOrchestrator _migrationOrchestrator;

    public TenantsController(
        AppDbContext appDb,
        ITenantProvisioningService provisioning,
        JwtTokenService jwtService,
        IMigrationOrchestrator migrationOrchestrator)
    {
        _appDb = appDb;
        _provisioning = provisioning;
        _jwtService = jwtService;
        _migrationOrchestrator = migrationOrchestrator;
    }

    [HttpGet]
    public async Task<IActionResult> GetAll()
    {
        var tenants = await _appDb.Tenants
            .Include(t => t.Plan)
            .Include(t => t.DbMapping)
            .Where(t => t.Status != TenantStatus.Deleted)
            .OrderByDescending(t => t.CreatedAt)
            .ToListAsync();

        return Ok(tenants.Select(MapToResponse));
    }

    [HttpGet("{id}")]
    public async Task<IActionResult> GetById(int id)
    {
        var tenant = await _appDb.Tenants
            .Include(t => t.Plan)
            .Include(t => t.DbMapping)
            .FirstOrDefaultAsync(t => t.Id == id);

        if (tenant == null) return NotFound();
        return Ok(MapToResponse(tenant));
    }

    [HttpPost]
    public async Task<IActionResult> Create([FromBody] CreateTenantRequest request)
    {
        if (await _appDb.Tenants.AnyAsync(t => t.Slug == request.Slug))
            return Conflict(new { error = "Slug already exists" });

        var plan = await _appDb.SubscriptionPlans.FindAsync(request.PlanId);
        if (plan == null)
            return BadRequest(new { error = "Invalid plan" });

        var tenant = new Tenant
        {
            Name = request.Name,
            Slug = request.Slug,
            Industry = request.Industry,
            PlanId = request.PlanId,
            BillingEmail = request.BillingEmail,
            Status = TenantStatus.PendingSetup,
            CreatedAt = DateTime.UtcNow
        };

        _appDb.Tenants.Add(tenant);
        await _appDb.SaveChangesAsync();

        await _provisioning.ProvisionTenantDatabaseAsync(tenant.Id, tenant.Name);

        return CreatedAtAction(nameof(GetById), new { id = tenant.Id }, MapToResponse(tenant));
    }

    [HttpPut("{id}/plan")]
    public async Task<IActionResult> UpdatePlan(int id, [FromBody] UpdatePlanRequest request)
    {
        var tenant = await _appDb.Tenants.FindAsync(id);
        if (tenant == null) return NotFound();

        var plan = await _appDb.SubscriptionPlans.FindAsync(request.PlanId);
        if (plan == null) return BadRequest(new { error = "Invalid plan" });

        tenant.PlanId = request.PlanId;
        tenant.UpdatedAt = DateTime.UtcNow;
        await _appDb.SaveChangesAsync();

        return Ok(new { message = $"Plan updated to {plan.Name}" });
    }

    [HttpPut("{id}/suspend")]
    public async Task<IActionResult> Suspend(int id)
    {
        var tenant = await _appDb.Tenants.FindAsync(id);
        if (tenant == null) return NotFound();

        tenant.Status = TenantStatus.Suspended;
        tenant.UpdatedAt = DateTime.UtcNow;
        await _appDb.SaveChangesAsync();

        return Ok(new { message = "Tenant suspended" });
    }

    [HttpPut("{id}/reactivate")]
    public async Task<IActionResult> Reactivate(int id)
    {
        var tenant = await _appDb.Tenants.FindAsync(id);
        if (tenant == null) return NotFound();

        tenant.Status = TenantStatus.Active;
        tenant.UpdatedAt = DateTime.UtcNow;
        await _appDb.SaveChangesAsync();

        return Ok(new { message = "Tenant reactivated" });
    }

    [HttpDelete("{id}")]
    public async Task<IActionResult> Delete(int id)
    {
        var tenant = await _appDb.Tenants.FindAsync(id);
        if (tenant == null) return NotFound();

        // Soft delete — DB preserved for retention period
        tenant.Status = TenantStatus.Deleted;
        tenant.UpdatedAt = DateTime.UtcNow;
        await _appDb.SaveChangesAsync();

        return Ok(new { message = "Tenant soft-deleted. Database preserved for retention period." });
    }

    [HttpPost("{id}/impersonate")]
    public async Task<IActionResult> Impersonate(int id)
    {
        var tenant = await _appDb.Tenants
            .Include(t => t.Plan)
            .FirstOrDefaultAsync(t => t.Id == id);

        if (tenant == null) return NotFound();
        if (tenant.Status != TenantStatus.Active)
            return BadRequest(new { error = "Cannot impersonate inactive tenant" });

        // Get current super admin user id
        var userIdClaim = User.FindFirst("userId")?.Value;
        if (string.IsNullOrEmpty(userIdClaim))
            return Unauthorized();

        var userId = int.Parse(userIdClaim);

        // Generate a JWT scoped to the target tenant
        var token = _jwtService.GenerateToken(userId, id, "SuperAdmin", "impersonate@leadpulse.com");

        return Ok(new { token, tenantId = id, tenantName = tenant.Name });
    }

    [HttpPost("migrate-all")]
    public async Task<IActionResult> MigrateAll()
    {
        await _migrationOrchestrator.MigrateAllTenantsAsync();
        return Ok(new { message = "Migrations applied to all active tenant databases" });
    }

    [HttpGet("plans")]
    public async Task<IActionResult> GetPlans()
    {
        var plans = await _appDb.SubscriptionPlans
            .Where(p => p.IsActive)
            .OrderBy(p => p.PriceMonthly)
            .ToListAsync();

        return Ok(plans);
    }

    private static object MapToResponse(Tenant t)
    {
        return new
        {
            t.Id,
            t.Name,
            t.Slug,
            t.Industry,
            t.PlanId,
            PlanName = t.Plan?.Name,
            t.BillingEmail,
            t.CustomDomain,
            Status = t.Status.ToString(),
            DatabaseName = t.DbMapping?.DatabaseName,
            t.CreatedAt,
            t.UpdatedAt
        };
    }
}

public class UpdatePlanRequest
{
    public int PlanId { get; set; }
}
