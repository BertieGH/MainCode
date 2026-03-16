namespace LeadPulse.Application.Interfaces;

public interface IMfaService
{
    string GenerateSecret();
    string GetQrCodeUri(string email, string secret, string issuer = "LeadPulse");
    bool VerifyCode(string secret, string code);
}
