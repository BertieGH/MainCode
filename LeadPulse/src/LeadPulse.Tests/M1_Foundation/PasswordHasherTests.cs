using FluentAssertions;
using LeadPulse.Infrastructure.Services;

namespace LeadPulse.Tests.M1_Foundation;

/// <summary>
/// M1-UT11: Password hashing roundtrip
/// </summary>
public class PasswordHasherTests
{
    private readonly PasswordHasher _hasher = new();

    [Fact]
    public void Hash_ProducesValidBCryptHash()
    {
        var hash = _hasher.Hash("TestPassword123!");

        hash.Should().NotBeNullOrEmpty();
        hash.Should().StartWith("$2");
    }

    [Fact]
    public void Verify_ReturnsTrueForCorrectPassword()
    {
        var password = "TestPassword123!";
        var hash = _hasher.Hash(password);

        _hasher.Verify(password, hash).Should().BeTrue();
    }

    [Fact]
    public void Verify_ReturnsFalseForIncorrectPassword()
    {
        var hash = _hasher.Hash("CorrectPassword");

        _hasher.Verify("WrongPassword", hash).Should().BeFalse();
    }

    [Fact]
    public void Hash_ProducesDifferentHashesForSamePassword()
    {
        var hash1 = _hasher.Hash("SamePassword");
        var hash2 = _hasher.Hash("SamePassword");

        hash1.Should().NotBe(hash2, "BCrypt uses random salt");
    }
}
