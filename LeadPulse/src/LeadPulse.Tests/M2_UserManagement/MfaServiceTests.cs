using FluentAssertions;
using LeadPulse.Infrastructure.Services;
using OtpNet;

namespace LeadPulse.Tests.M2_UserManagement;

/// <summary>
/// M2-UT08: MFA verification
/// </summary>
public class MfaServiceTests
{
    private readonly MfaService _mfaService = new();

    [Fact]
    public void GenerateSecret_ReturnsValidBase32String()
    {
        var secret = _mfaService.GenerateSecret();

        secret.Should().NotBeNullOrEmpty();
        secret.Length.Should().BeGreaterThanOrEqualTo(16);

        // Should be valid base32
        var bytes = Base32Encoding.ToBytes(secret);
        bytes.Should().NotBeEmpty();
    }

    [Fact]
    public void GetQrCodeUri_ReturnsValidOtpAuthUri()
    {
        var secret = _mfaService.GenerateSecret();
        var uri = _mfaService.GetQrCodeUri("test@example.com", secret);

        uri.Should().StartWith("otpauth://totp/");
        uri.Should().Contain("test@example.com");
        uri.Should().Contain(secret);
        uri.Should().Contain("LeadPulse");
    }

    [Fact]
    public void VerifyCode_Succeeds_WithCorrectCode()
    {
        // M2-UT08: Given correct TOTP code, verification succeeds
        var secret = _mfaService.GenerateSecret();
        var keyBytes = Base32Encoding.ToBytes(secret);
        var totp = new Totp(keyBytes);
        var correctCode = totp.ComputeTotp();

        _mfaService.VerifyCode(secret, correctCode).Should().BeTrue();
    }

    [Fact]
    public void VerifyCode_Fails_WithWrongCode()
    {
        // M2-UT08: Given wrong TOTP code, verification fails
        var secret = _mfaService.GenerateSecret();

        _mfaService.VerifyCode(secret, "000000").Should().BeFalse();
    }

    [Fact]
    public void GenerateSecret_ProducesDifferentSecrets()
    {
        var s1 = _mfaService.GenerateSecret();
        var s2 = _mfaService.GenerateSecret();

        s1.Should().NotBe(s2);
    }
}
