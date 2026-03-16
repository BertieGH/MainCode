namespace LeadPulse.Domain.Entities.App;

public class TenantDbMapping
{
    public int Id { get; set; }
    public int TenantId { get; set; }
    public string DatabaseName { get; set; } = string.Empty;
    public string ServerHost { get; set; } = string.Empty;
    public int Port { get; set; } = 3306;
    public string Username { get; set; } = string.Empty;
    public string EncryptedPassword { get; set; } = string.Empty;
    public string SslMode { get; set; } = "Required";
    public string? MigrationVersion { get; set; }
    public DateTime CreatedAt { get; set; }

    public Tenant Tenant { get; set; } = null!;

    public string GetConnectionString(string decryptedPassword)
    {
        return $"Server={ServerHost};Port={Port};Database={DatabaseName};User={Username};Password={decryptedPassword};SslMode={SslMode}";
    }
}
