using System.Security.Claims;
using System.Text.Json;
using LeadPulse.Application.DTOs;
using LeadPulse.Application.Interfaces;
using LeadPulse.Domain.Authorization;
using LeadPulse.Domain.Entities.Tenant;
using LeadPulse.Domain.Enums;
using LeadPulse.Infrastructure.Authorization;
using LeadPulse.Infrastructure.Data;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace LeadPulse.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
[Authorize]
public class UsersController : ControllerBase
{
    private readonly TenantDbContext _tenantDb;
    private readonly AppDbContext _appDb;
    private readonly ITenantContext _tenantContext;
    private readonly IPasswordHasher _passwordHasher;
    private readonly IMfaService _mfaService;

    public UsersController(
        TenantDbContext tenantDb,
        AppDbContext appDb,
        ITenantContext tenantContext,
        IPasswordHasher passwordHasher,
        IMfaService mfaService)
    {
        _tenantDb = tenantDb;
        _appDb = appDb;
        _tenantContext = tenantContext;
        _passwordHasher = passwordHasher;
        _mfaService = mfaService;
    }

    [HttpGet]
    [HasPermission(Permissions.ManageUsers)]
    public async Task<IActionResult> GetAll()
    {
        var users = await _tenantDb.Users
            .OrderByDescending(u => u.CreatedAt)
            .Select(u => MapToResponse(u))
            .ToListAsync();

        return Ok(users);
    }

    [HttpGet("{id}")]
    [HasPermission(Permissions.ManageUsers)]
    public async Task<IActionResult> GetById(int id)
    {
        var user = await _tenantDb.Users.FindAsync(id);
        if (user == null) return NotFound();
        return Ok(MapToResponse(user));
    }

    [HttpPost]
    [HasPermission(Permissions.ManageUsers)]
    public async Task<IActionResult> Create([FromBody] CreateUserRequest request)
    {
        var callerRole = User.FindFirstValue(ClaimTypes.Role) ?? User.FindFirstValue("role");

        // Validate role
        if (!Enum.TryParse<UserRole>(request.Role, out var role))
            return BadRequest(new { error = "Invalid role. Must be TenantAdmin, Agent, or Viewer" });

        // Tenant Admin cannot create Super Admin
        if (callerRole == "TenantAdmin" && request.Role == "SuperAdmin")
            return StatusCode(403, new { error = "Tenant Admin cannot create Super Admin" });

        // Agent/Viewer cannot create users at all (handled by permission policy, but double-check)
        if (callerRole is "Agent" or "Viewer")
            return StatusCode(403, new { error = "Insufficient permissions" });

        // Check plan user limit
        if (_tenantContext.TenantId.HasValue)
        {
            var tenant = await _appDb.Tenants
                .Include(t => t.Plan)
                .FirstOrDefaultAsync(t => t.Id == _tenantContext.TenantId.Value);

            if (tenant != null)
            {
                var currentUserCount = await _tenantDb.Users.CountAsync(u => u.Status != UserStatus.Disabled);
                if (currentUserCount >= tenant.Plan.MaxUsers)
                    return BadRequest(new { error = "Seat limit reached for your subscription plan" });
            }
        }

        // Check duplicate email
        if (await _tenantDb.Users.AnyAsync(u => u.Email == request.Email))
            return Conflict(new { error = "Email already exists" });

        var user = new User
        {
            FirstName = request.FirstName,
            LastName = request.LastName,
            Email = request.Email,
            PasswordHash = _passwordHasher.Hash(request.Password),
            Phone = request.Phone,
            Role = role,
            Permissions = request.Permissions != null ? JsonSerializer.Serialize(request.Permissions) : null,
            ForcePasswordChange = true,
            Status = UserStatus.Active,
            CreatedAt = DateTime.UtcNow
        };

        _tenantDb.Users.Add(user);
        await _tenantDb.SaveChangesAsync();

        return CreatedAtAction(nameof(GetById), new { id = user.Id }, MapToResponse(user));
    }

    [HttpPut("{id}")]
    [HasPermission(Permissions.ManageUsers)]
    public async Task<IActionResult> Update(int id, [FromBody] UpdateUserRequest request)
    {
        var user = await _tenantDb.Users.FindAsync(id);
        if (user == null) return NotFound();

        if (request.FirstName != null) user.FirstName = request.FirstName;
        if (request.LastName != null) user.LastName = request.LastName;
        if (request.Phone != null) user.Phone = request.Phone;

        if (request.Role != null && Enum.TryParse<UserRole>(request.Role, out var role))
            user.Role = role;

        if (request.Permissions != null)
            user.Permissions = JsonSerializer.Serialize(request.Permissions);

        user.UpdatedAt = DateTime.UtcNow;
        await _tenantDb.SaveChangesAsync();

        return Ok(MapToResponse(user));
    }

    [HttpPut("{id}/disable")]
    [HasPermission(Permissions.ManageUsers)]
    public async Task<IActionResult> Disable(int id)
    {
        var user = await _tenantDb.Users.FindAsync(id);
        if (user == null) return NotFound();

        user.Status = UserStatus.Disabled;
        user.UpdatedAt = DateTime.UtcNow;
        await _tenantDb.SaveChangesAsync();

        return Ok(new { message = "User disabled" });
    }

    [HttpPut("{id}/enable")]
    [HasPermission(Permissions.ManageUsers)]
    public async Task<IActionResult> Enable(int id)
    {
        var user = await _tenantDb.Users.FindAsync(id);
        if (user == null) return NotFound();

        user.Status = UserStatus.Active;
        user.UpdatedAt = DateTime.UtcNow;
        await _tenantDb.SaveChangesAsync();

        return Ok(new { message = "User enabled" });
    }

    [HttpPost("{id}/reset-password")]
    [HasPermission(Permissions.ManageUsers)]
    public async Task<IActionResult> ResetPassword(int id, [FromBody] ResetPasswordRequest request)
    {
        var user = await _tenantDb.Users.FindAsync(id);
        if (user == null) return NotFound();

        user.PasswordHash = _passwordHasher.Hash(request.NewPassword);
        user.ForcePasswordChange = true;
        user.UpdatedAt = DateTime.UtcNow;
        await _tenantDb.SaveChangesAsync();

        return Ok(new { message = "Password reset successfully" });
    }

    [HttpPost("invite")]
    [HasPermission(Permissions.ManageUsers)]
    public async Task<IActionResult> Invite([FromBody] InviteUserRequest request)
    {
        if (!Enum.TryParse<UserRole>(request.Role, out var role))
            return BadRequest(new { error = "Invalid role" });

        // Check if already invited or existing
        if (await _tenantDb.Users.AnyAsync(u => u.Email == request.Email))
            return Conflict(new { error = "User with this email already exists" });

        if (await _tenantDb.UserInvitations.AnyAsync(i => i.Email == request.Email && i.AcceptedAt == null && i.ExpiresAt > DateTime.UtcNow))
            return Conflict(new { error = "Pending invitation already exists for this email" });

        var callerIdStr = User.FindFirstValue(ClaimTypes.NameIdentifier);
        if (!int.TryParse(callerIdStr, out var callerId))
            return BadRequest(new { error = "Invalid caller" });

        var invitation = new UserInvitation
        {
            Email = request.Email,
            Role = role,
            InvitedByUserId = callerId,
            Token = Guid.NewGuid().ToString("N"),
            ExpiresAt = DateTime.UtcNow.AddDays(7),
            CreatedAt = DateTime.UtcNow
        };

        _tenantDb.UserInvitations.Add(invitation);
        await _tenantDb.SaveChangesAsync();

        // In production, send email via SendGrid/SMTP here

        return Ok(new { message = "Invitation sent", token = invitation.Token, expiresAt = invitation.ExpiresAt });
    }

    [HttpGet("invitations")]
    [HasPermission(Permissions.ManageUsers)]
    public async Task<IActionResult> GetInvitations()
    {
        var invitations = await _tenantDb.UserInvitations
            .Include(i => i.InvitedBy)
            .OrderByDescending(i => i.CreatedAt)
            .ToListAsync();

        return Ok(invitations.Select(i => new
        {
            i.Id, i.Email, Role = i.Role.ToString(),
            InvitedBy = $"{i.InvitedBy.FirstName} {i.InvitedBy.LastName}",
            i.ExpiresAt, i.AcceptedAt, i.CreatedAt,
            Status = i.AcceptedAt.HasValue ? "Accepted" : i.ExpiresAt < DateTime.UtcNow ? "Expired" : "Pending"
        }));
    }

    [HttpPost("accept-invitation")]
    [AllowAnonymous]
    public async Task<IActionResult> AcceptInvitation([FromBody] AcceptInvitationRequest request)
    {
        var invitation = await _tenantDb.UserInvitations
            .FirstOrDefaultAsync(i => i.Token == request.Token);

        if (invitation == null)
            return NotFound(new { error = "Invalid invitation token" });

        if (invitation.AcceptedAt.HasValue)
            return BadRequest(new { error = "Invitation already accepted" });

        if (invitation.ExpiresAt < DateTime.UtcNow)
            return BadRequest(new { error = "Invitation has expired" });

        var user = new User
        {
            FirstName = request.FirstName,
            LastName = request.LastName,
            Email = invitation.Email,
            PasswordHash = _passwordHasher.Hash(request.Password),
            Role = invitation.Role,
            ForcePasswordChange = false,
            Status = UserStatus.Active,
            CreatedAt = DateTime.UtcNow
        };

        _tenantDb.Users.Add(user);
        invitation.AcceptedAt = DateTime.UtcNow;
        await _tenantDb.SaveChangesAsync();

        return Ok(new { message = "Account created successfully", userId = user.Id });
    }

    [HttpGet("permissions-matrix")]
    [HasPermission(Permissions.ManageUsers)]
    public IActionResult GetPermissionsMatrix()
    {
        var matrix = new Dictionary<string, string[]>
        {
            ["SuperAdmin"] = Permissions.GetDefaultPermissions("SuperAdmin"),
            ["TenantAdmin"] = Permissions.GetDefaultPermissions("TenantAdmin"),
            ["Agent"] = Permissions.GetDefaultPermissions("Agent"),
            ["Viewer"] = Permissions.GetDefaultPermissions("Viewer")
        };

        return Ok(new { permissions = Permissions.All, matrix });
    }

    [HttpPost("me/mfa/setup")]
    public async Task<IActionResult> SetupMfa()
    {
        var userIdStr = User.FindFirstValue(ClaimTypes.NameIdentifier);
        if (!int.TryParse(userIdStr, out var userId))
            return BadRequest();

        var user = await _tenantDb.Users.FindAsync(userId);
        if (user == null) return NotFound();

        if (user.MfaEnabled)
            return BadRequest(new { error = "MFA is already enabled" });

        var secret = _mfaService.GenerateSecret();
        user.MfaSecret = secret;
        await _tenantDb.SaveChangesAsync();

        var qrUri = _mfaService.GetQrCodeUri(user.Email, secret);

        return Ok(new { secret, qrUri });
    }

    [HttpPost("me/mfa/verify")]
    public async Task<IActionResult> VerifyMfa([FromBody] MfaVerifyRequest request)
    {
        var userIdStr = User.FindFirstValue(ClaimTypes.NameIdentifier);
        if (!int.TryParse(userIdStr, out var userId))
            return BadRequest();

        var user = await _tenantDb.Users.FindAsync(userId);
        if (user == null) return NotFound();

        if (string.IsNullOrEmpty(user.MfaSecret))
            return BadRequest(new { error = "MFA not set up. Call /me/mfa/setup first" });

        if (!_mfaService.VerifyCode(user.MfaSecret, request.Code))
            return Unauthorized(new { error = "Invalid MFA code" });

        if (!user.MfaEnabled)
        {
            user.MfaEnabled = true;
            await _tenantDb.SaveChangesAsync();
        }

        return Ok(new { message = "MFA verified successfully" });
    }

    [HttpPost("me/mfa/disable")]
    public async Task<IActionResult> DisableMfa([FromBody] MfaVerifyRequest request)
    {
        var userIdStr = User.FindFirstValue(ClaimTypes.NameIdentifier);
        if (!int.TryParse(userIdStr, out var userId))
            return BadRequest();

        var user = await _tenantDb.Users.FindAsync(userId);
        if (user == null) return NotFound();

        if (!user.MfaEnabled)
            return BadRequest(new { error = "MFA is not enabled" });

        if (!_mfaService.VerifyCode(user.MfaSecret!, request.Code))
            return Unauthorized(new { error = "Invalid MFA code" });

        user.MfaEnabled = false;
        user.MfaSecret = null;
        await _tenantDb.SaveChangesAsync();

        return Ok(new { message = "MFA disabled" });
    }

    private static UserResponse MapToResponse(User user)
    {
        return new UserResponse
        {
            Id = user.Id,
            FirstName = user.FirstName,
            LastName = user.LastName,
            Email = user.Email,
            Phone = user.Phone,
            Role = user.Role.ToString(),
            Permissions = user.Permissions != null
                ? JsonSerializer.Deserialize<Dictionary<string, bool>>(user.Permissions)
                : null,
            MfaEnabled = user.MfaEnabled,
            Status = user.Status.ToString(),
            LastLoginAt = user.LastLoginAt,
            CreatedAt = user.CreatedAt
        };
    }
}
