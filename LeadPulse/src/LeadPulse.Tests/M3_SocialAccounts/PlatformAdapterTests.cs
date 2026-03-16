using FluentAssertions;
using LeadPulse.Application.Interfaces;
using LeadPulse.Infrastructure.PlatformAdapters;
using Microsoft.Extensions.Logging;
using Moq;

namespace LeadPulse.Tests.M3_SocialAccounts;

/// <summary>
/// M3-UT06: Platform adapter registration and behavior
/// </summary>
public class PlatformAdapterTests
{
    [Fact]
    public void LinkedInAdapter_HasCorrectPlatform()
    {
        var adapter = new LinkedInAdapter(Mock.Of<ILogger<LinkedInAdapter>>());
        adapter.Platform.Should().Be("LinkedIn");
    }

    [Fact]
    public void FacebookAdapter_HasCorrectPlatform()
    {
        var adapter = new FacebookAdapter(Mock.Of<ILogger<FacebookAdapter>>());
        adapter.Platform.Should().Be("Facebook");
    }

    [Fact]
    public void NextdoorAdapter_HasCorrectPlatform()
    {
        var adapter = new NextdoorAdapter(Mock.Of<ILogger<NextdoorAdapter>>());
        adapter.Platform.Should().Be("Nextdoor");
    }

    [Fact]
    public void XTwitterAdapter_HasCorrectPlatform()
    {
        var adapter = new XTwitterAdapter(Mock.Of<ILogger<XTwitterAdapter>>());
        adapter.Platform.Should().Be("X");
    }

    [Fact]
    public async Task TestLogin_ReturnsSuccessStub()
    {
        var adapter = new LinkedInAdapter(Mock.Of<ILogger<LinkedInAdapter>>());

        var result = await adapter.TestLoginAsync("user", "pass", null);

        result.Should().NotBeNull();
        result.Success.Should().BeTrue();
    }

    [Fact]
    public async Task ScrapePostsAsync_ReturnsEmptyPostsStub()
    {
        var adapter = new LinkedInAdapter(Mock.Of<ILogger<LinkedInAdapter>>());

        var result = await adapter.ScrapePostsAsync("user", "pass", null, 50, "medium");

        result.Should().NotBeNull();
        result.Success.Should().BeTrue();
        result.Posts.Should().BeEmpty();
    }

    [Fact]
    public void AllAdapters_ImplementISocialPlatformAdapter()
    {
        typeof(LinkedInAdapter).Should().Implement<ISocialPlatformAdapter>();
        typeof(FacebookAdapter).Should().Implement<ISocialPlatformAdapter>();
        typeof(NextdoorAdapter).Should().Implement<ISocialPlatformAdapter>();
        typeof(XTwitterAdapter).Should().Implement<ISocialPlatformAdapter>();
    }

    [Fact]
    public void AdapterSelection_MatchesCaseInsensitive()
    {
        // Simulates how SyncService finds the right adapter
        var adapters = new ISocialPlatformAdapter[]
        {
            new LinkedInAdapter(Mock.Of<ILogger<LinkedInAdapter>>()),
            new FacebookAdapter(Mock.Of<ILogger<FacebookAdapter>>()),
            new NextdoorAdapter(Mock.Of<ILogger<NextdoorAdapter>>()),
            new XTwitterAdapter(Mock.Of<ILogger<XTwitterAdapter>>())
        };

        var match = adapters.FirstOrDefault(a =>
            a.Platform.Equals("linkedin", StringComparison.OrdinalIgnoreCase));

        match.Should().NotBeNull();
        match!.Platform.Should().Be("LinkedIn");
    }
}
