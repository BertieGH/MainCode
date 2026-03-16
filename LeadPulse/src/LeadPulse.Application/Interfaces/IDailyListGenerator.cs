namespace LeadPulse.Application.Interfaces;

public interface IDailyListGenerator
{
    Task GenerateDailyListAsync(int tenantId, int strategyId);
}
