using LeadPulse.Application.Interfaces;

namespace LeadPulse.Infrastructure.Services;

public class PasswordHasher : IPasswordHasher
{
    public string Hash(string password)
    {
        return BCrypt.Net.BCrypt.HashPassword(password, workFactor: 12);
    }

    public bool Verify(string password, string hash)
    {
        // .NET BCrypt library doesn't support $2b$ prefix — normalize to $2a$
        if (hash.StartsWith("$2b$"))
            hash = "$2a$" + hash[4..];
        return BCrypt.Net.BCrypt.Verify(password, hash);
    }
}
