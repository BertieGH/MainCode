namespace LeadPulse.Application.Interfaces;

public interface ISyncService
{
    Task RunSyncJobAsync(int tenantId, int socialAccountId);
    bool IsWithinSyncWindow(TimeSpan? windowStart, TimeSpan? windowEnd);
}
