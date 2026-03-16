using LeadPulse.Application.Interfaces;
using OtpNet;

namespace LeadPulse.Infrastructure.Services;

public class MfaService : IMfaService
{
    public string GenerateSecret()
    {
        var key = KeyGeneration.GenerateRandomKey(20);
        return Base32Encoding.ToString(key);
    }

    public string GetQrCodeUri(string email, string secret, string issuer = "LeadPulse")
    {
        return $"otpauth://totp/{issuer}:{email}?secret={secret}&issuer={issuer}&digits=6&period=30";
    }

    public bool VerifyCode(string secret, string code)
    {
        var keyBytes = Base32Encoding.ToBytes(secret);
        var totp = new Totp(keyBytes);
        return totp.VerifyTotp(code, out _, new VerificationWindow(previous: 1, future: 1));
    }
}
