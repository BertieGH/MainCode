using System.Security.Cryptography;
using System.Text;
using LeadPulse.Application.Interfaces;
using Microsoft.Extensions.Configuration;

namespace LeadPulse.Infrastructure.Services;

public class EncryptionService : IEncryptionService
{
    private readonly string _masterKey;

    public EncryptionService(IConfiguration configuration)
    {
        _masterKey = configuration["Encryption:MasterKey"]
            ?? throw new InvalidOperationException("Encryption master key not configured");
    }

    public string Encrypt(string plainText, int tenantId)
    {
        var key = DeriveKey(tenantId);
        using var aes = Aes.Create();
        aes.Key = key;
        aes.GenerateIV();
        aes.Mode = CipherMode.CBC;
        aes.Padding = PaddingMode.PKCS7;

        using var encryptor = aes.CreateEncryptor();
        var plainBytes = Encoding.UTF8.GetBytes(plainText);
        var cipherBytes = encryptor.TransformFinalBlock(plainBytes, 0, plainBytes.Length);

        // Prepend IV to cipher text
        var result = new byte[aes.IV.Length + cipherBytes.Length];
        Buffer.BlockCopy(aes.IV, 0, result, 0, aes.IV.Length);
        Buffer.BlockCopy(cipherBytes, 0, result, aes.IV.Length, cipherBytes.Length);

        return Convert.ToBase64String(result);
    }

    public string Decrypt(string cipherText, int tenantId)
    {
        var key = DeriveKey(tenantId);
        var fullBytes = Convert.FromBase64String(cipherText);

        using var aes = Aes.Create();
        aes.Key = key;
        aes.Mode = CipherMode.CBC;
        aes.Padding = PaddingMode.PKCS7;

        // Extract IV (first 16 bytes)
        var iv = new byte[16];
        Buffer.BlockCopy(fullBytes, 0, iv, 0, 16);
        aes.IV = iv;

        var cipherBytes = new byte[fullBytes.Length - 16];
        Buffer.BlockCopy(fullBytes, 16, cipherBytes, 0, cipherBytes.Length);

        using var decryptor = aes.CreateDecryptor();
        var plainBytes = decryptor.TransformFinalBlock(cipherBytes, 0, cipherBytes.Length);

        return Encoding.UTF8.GetString(plainBytes);
    }

    private byte[] DeriveKey(int tenantId)
    {
        var salt = Encoding.UTF8.GetBytes($"LeadPulse-Tenant-{tenantId}");
        using var deriveBytes = new Rfc2898DeriveBytes(
            _masterKey, salt, iterations: 100000, HashAlgorithmName.SHA256);
        return deriveBytes.GetBytes(32); // 256 bits
    }
}
