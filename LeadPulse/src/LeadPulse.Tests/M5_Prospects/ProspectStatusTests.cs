using FluentAssertions;
using LeadPulse.Api.Controllers;
using LeadPulse.Domain.Enums;

namespace LeadPulse.Tests.M5_Prospects;

/// <summary>
/// M5-UT09: Status transition validation
/// </summary>
public class ProspectStatusTests
{
    [Theory]
    [InlineData(ProspectStatus.New, ProspectStatus.Viewed, true)]
    [InlineData(ProspectStatus.New, ProspectStatus.Contacted, true)]
    [InlineData(ProspectStatus.New, ProspectStatus.Dismissed, true)]
    [InlineData(ProspectStatus.Viewed, ProspectStatus.Contacted, true)]
    [InlineData(ProspectStatus.Viewed, ProspectStatus.Dismissed, true)]
    [InlineData(ProspectStatus.Contacted, ProspectStatus.Converted, true)]
    [InlineData(ProspectStatus.Contacted, ProspectStatus.Dismissed, true)]
    [InlineData(ProspectStatus.Contacted, ProspectStatus.New, false)]     // Cannot go backwards
    [InlineData(ProspectStatus.Converted, ProspectStatus.New, false)]     // Terminal state
    [InlineData(ProspectStatus.Converted, ProspectStatus.Contacted, false)]
    [InlineData(ProspectStatus.Dismissed, ProspectStatus.New, false)]     // Terminal state
    [InlineData(ProspectStatus.New, ProspectStatus.Converted, false)]     // Cannot skip Contacted
    public void StatusTransition_ValidatesCorrectly(ProspectStatus from, ProspectStatus to, bool expected)
    {
        var result = ProspectsController.IsValidTransition(from, to);
        result.Should().Be(expected);
    }

    [Fact]
    public void SameStatus_IsValid()
    {
        ProspectsController.IsValidTransition(ProspectStatus.New, ProspectStatus.New).Should().BeTrue();
        ProspectsController.IsValidTransition(ProspectStatus.Contacted, ProspectStatus.Contacted).Should().BeTrue();
    }
}
