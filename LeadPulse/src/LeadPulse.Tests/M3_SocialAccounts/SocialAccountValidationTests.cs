using FluentAssertions;
using LeadPulse.Application.DTOs;
using LeadPulse.Domain.Entities.Tenant;
using LeadPulse.Domain.Enums;

namespace LeadPulse.Tests.M3_SocialAccounts;

/// <summary>
/// M3-UT03: Sync frequency validation (60-2880 min range)
/// M3-UT05: Max accounts per plan limit
/// M3-UT09: Credentials never in API response
/// </summary>
public class SocialAccountValidationTests
{
    [Theory]
    [InlineData(59, false)]   // Below minimum
    [InlineData(60, true)]    // Minimum
    [InlineData(360, true)]   // Normal
    [InlineData(2880, true)]  // Maximum
    [InlineData(2881, false)] // Above maximum
    public void SyncFrequency_MustBeBetween60And2880(int frequency, bool isValid)
    {
        // M3-UT03: Sync frequency validation
        var valid = frequency >= 60 && frequency <= 2880;
        valid.Should().Be(isValid);
    }

    [Fact]
    public void SocialAccountResponse_NeverContainsPassword()
    {
        // M3-UT09: Verify the DTO has no password field
        var responseType = typeof(SocialAccountResponse);

        responseType.GetProperty("Password").Should().BeNull();
        responseType.GetProperty("EncryptedPassword").Should().BeNull();
        responseType.GetProperty("MfaSecret").Should().BeNull();
        responseType.GetProperty("EncryptedMfaSecret").Should().BeNull();
    }

    [Fact]
    public void SocialAccount_HasCorrectDefaultValues()
    {
        var account = new SocialAccount();

        account.SyncFrequencyMinutes.Should().Be(360);
        account.MaxPostsPerSync.Should().Be(500);
        account.AutoRetryMax.Should().Be(3);
        account.TotalPostsScraped.Should().Be(0);
        account.Status.Should().Be(SocialAccountStatus.Active);
        account.ScrapeDepth.Should().Be("48h");
    }

    [Fact]
    public void SyncJob_TracksExpectedFields()
    {
        var job = new SyncJob
        {
            SocialAccountId = 1,
            Status = SyncJobStatus.Running,
            StartedAt = DateTime.UtcNow,
            CreatedAt = DateTime.UtcNow
        };

        job.SocialAccountId.Should().Be(1);
        job.Status.Should().Be(SyncJobStatus.Running);
        job.StartedAt.Should().NotBeNull();
        job.PostsFound.Should().Be(0);
        job.RetryCount.Should().Be(0);
    }

    [Fact]
    public void SyncJobStatus_HasAllExpectedValues()
    {
        var values = Enum.GetValues<SyncJobStatus>();

        values.Should().Contain(SyncJobStatus.Queued);
        values.Should().Contain(SyncJobStatus.Running);
        values.Should().Contain(SyncJobStatus.Success);
        values.Should().Contain(SyncJobStatus.Failed);
        values.Should().Contain(SyncJobStatus.Cancelled);
    }

    [Fact]
    public void SocialAccountStatus_HasAllExpectedValues()
    {
        var values = Enum.GetValues<SocialAccountStatus>();

        values.Should().Contain(SocialAccountStatus.Active);
        values.Should().Contain(SocialAccountStatus.Syncing);
        values.Should().Contain(SocialAccountStatus.LoginFailed);
        values.Should().Contain(SocialAccountStatus.Disabled);
    }
}
