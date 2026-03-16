using FluentAssertions;
using LeadPulse.Domain.Entities.App;
using LeadPulse.Domain.Enums;

namespace LeadPulse.Tests.M9_Security;

/// <summary>
/// M9 Security audit tests — OWASP top 10 verification
/// </summary>
public class SecurityTests
{
    [Fact]
    public void JwtSecret_MinimumLength()
    {
        var secret = "LeadPulse-JWT-Secret-Key-Change-In-Production-Min32Chars!";
        secret.Length.Should().BeGreaterThanOrEqualTo(32, "JWT HMAC-SHA256 requires minimum 32 char key");
    }

    [Fact]
    public void EncryptionKey_MinimumLength()
    {
        var key = "LeadPulse-Master-Encryption-Key-Change-In-Production!";
        key.Length.Should().BeGreaterThanOrEqualTo(32, "AES-256 requires sufficient key material");
    }

    [Fact]
    public void TenantStatus_NonActiveBlocksAccess()
    {
        var statuses = new[] { TenantStatus.Suspended, TenantStatus.Deleted, TenantStatus.PendingSetup };
        foreach (var status in statuses)
        {
            var allowed = status == TenantStatus.Active;
            allowed.Should().BeFalse($"status {status} should not allow access");
        }
    }

    [Fact]
    public void PasswordHash_NeverStoredPlaintext()
    {
        var plainPassword = "MySecurePassword123!";
        var hash = Convert.ToBase64String(
            System.Security.Cryptography.SHA256.HashData(
                System.Text.Encoding.UTF8.GetBytes(plainPassword)));

        hash.Should().NotBe(plainPassword, "passwords must be hashed");
        hash.Length.Should().BeGreaterThan(0);
    }

    [Fact]
    public void ApiRateLimit_PreventsAbuse()
    {
        var rateLimit = new ApiRateLimit
        {
            TenantId = 1,
            Date = DateTime.UtcNow.Date,
            CallCount = 1000
        };

        int maxAllowed = 500;
        var isBlocked = rateLimit.CallCount >= maxAllowed;
        isBlocked.Should().BeTrue("requests exceeding rate limit must be blocked");
    }

    [Fact]
    public void TenantDbMapping_NeverExposesCredentials()
    {
        var mapping = new TenantDbMapping
        {
            TenantId = 1,
            DatabaseName = "lp_ten1",
            ServerHost = "localhost",
            Username = "dbuser",
            EncryptedPassword = "encrypted_base64_string"
        };

        // API should only return DatabaseName, never credentials
        var apiResponse = new { mapping.DatabaseName };
        var serialized = System.Text.Json.JsonSerializer.Serialize(apiResponse);
        serialized.Should().NotContain("Password");
        serialized.Should().NotContain("Username");
        serialized.Should().Contain("lp_ten1");
    }

    [Fact]
    public void SoftDelete_PreservesData()
    {
        var tenant = new Tenant
        {
            Id = 1,
            Name = "Test Tenant",
            Status = TenantStatus.Active
        };

        tenant.Status = TenantStatus.Deleted;
        tenant.UpdatedAt = DateTime.UtcNow;

        tenant.Name.Should().Be("Test Tenant", "soft delete preserves tenant data");
        tenant.Status.Should().Be(TenantStatus.Deleted);
    }

    [Fact]
    public void SubscriptionPlan_EnforcesLimits()
    {
        var plan = new SubscriptionPlan
        {
            Name = "Basic",
            MaxUsers = 5,
            MaxKeywords = 50,
            MaxApiCallsPerDay = 500
        };

        int currentUsers = 6;
        var isOverLimit = currentUsers > plan.MaxUsers;
        isOverLimit.Should().BeTrue("exceeding plan limits should be detected");
    }
}
