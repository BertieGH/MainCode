namespace LeadPulse.Application.Interfaces;

public interface IEncryptionService
{
    string Encrypt(string plainText, int tenantId);
    string Decrypt(string cipherText, int tenantId);
}
