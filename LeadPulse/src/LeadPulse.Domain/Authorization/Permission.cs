namespace LeadPulse.Domain.Authorization;

public static class Permissions
{
    public const string ViewProspects = "ViewProspects";
    public const string ManageProspects = "ManageProspects";
    public const string LogCalls = "LogCalls";
    public const string ManageStrategies = "ManageStrategies";
    public const string ExportData = "ExportData";
    public const string ManageSocialAccounts = "ManageSocialAccounts";
    public const string ManageKeywords = "ManageKeywords";
    public const string ViewAnalytics = "ViewAnalytics";
    public const string ManageUsers = "ManageUsers";
    public const string ManageTenants = "ManageTenants";

    public static readonly string[] All = new[]
    {
        ViewProspects, ManageProspects, LogCalls, ManageStrategies,
        ExportData, ManageSocialAccounts, ManageKeywords,
        ViewAnalytics, ManageUsers, ManageTenants
    };

    public static string[] GetDefaultPermissions(string role)
    {
        return role switch
        {
            "SuperAdmin" => All,
            "TenantAdmin" => new[]
            {
                ViewProspects, ManageProspects, LogCalls, ManageStrategies,
                ExportData, ManageSocialAccounts, ManageKeywords,
                ViewAnalytics, ManageUsers
            },
            "Agent" => new[]
            {
                ViewProspects, ManageProspects, LogCalls, ManageStrategies,
                ExportData, ViewAnalytics
            },
            "Viewer" => new[]
            {
                ViewProspects, ViewAnalytics
            },
            _ => Array.Empty<string>()
        };
    }
}
