using FluentAssertions;
using LeadPulse.Infrastructure.Services;
using Microsoft.Extensions.Configuration;

namespace LeadPulse.Tests.M3_SocialAccounts;

/// <summary>
/// M3-UT01: Encryption roundtrip
/// M3-UT02: Per-tenant key isolation
/// M3-UT09: Credentials never returned in API response (tested via controller mapping)
/// </summary>
public class EncryptionServiceTests
{
    private static EncryptionService CreateService(string masterKey = "test-master-key-for-unit-tests-32chars!")
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Encryption:MasterKey"] = masterKey
            })
            .Build();
        return new EncryptionService(config);
    }

    [Fact]
    public void EncryptDecrypt_Roundtrip_ReturnsOriginalText()
    {
        // M3-UT01: Encrypt then decrypt should return original plaintext
        var service = CreateService();
        var plainText = "MyS3cur3P@ssw0rd!";
        var tenantId = 1;

        var encrypted = service.Encrypt(plainText, tenantId);
        var decrypted = service.Decrypt(encrypted, tenantId);

        decrypted.Should().Be(plainText);
    }

    [Fact]
    public void Encrypt_ProducesDifferentCiphertext_EachTime()
    {
        // Due to random IV, same plaintext should produce different ciphertext
        var service = CreateService();
        var plainText = "password123";

        var encrypted1 = service.Encrypt(plainText, 1);
        var encrypted2 = service.Encrypt(plainText, 1);

        encrypted1.Should().NotBe(encrypted2);
    }

    [Fact]
    public void Encrypt_DifferentTenants_ProduceDifferentCiphertext()
    {
        // M3-UT02: Per-tenant isolation — same password encrypted for different tenants
        // should not be decryptable with wrong tenant key
        var service = CreateService();
        var plainText = "shared-password";

        var encryptedTenant1 = service.Encrypt(plainText, 1);
        var encryptedTenant2 = service.Encrypt(plainText, 2);

        // Ciphertext should differ (different derived keys + different IVs)
        encryptedTenant1.Should().NotBe(encryptedTenant2);
    }

    [Fact]
    public void Decrypt_WithWrongTenant_Fails()
    {
        // M3-UT02: Encrypted with tenant 1 key, cannot decrypt with tenant 2 key
        var service = CreateService();
        var encrypted = service.Encrypt("secret", 1);

        var act = () => service.Decrypt(encrypted, 2);

        act.Should().Throw<Exception>();
    }

    [Fact]
    public void Encrypt_EmptyString_RoundtripsCorrectly()
    {
        var service = CreateService();
        var encrypted = service.Encrypt("", 1);
        var decrypted = service.Decrypt(encrypted, 1);

        decrypted.Should().BeEmpty();
    }

    [Fact]
    public void Constructor_ThrowsWithoutMasterKey()
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>())
            .Build();

        var act = () => new EncryptionService(config);

        act.Should().Throw<InvalidOperationException>()
            .WithMessage("*master key*");
    }
}
