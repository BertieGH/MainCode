namespace LeadPulse.Application.Interfaces;

public interface ISignalProcessor
{
    Task ProcessSignalsAsync(int tenantId);
    Task<int> FixGenericAuthorNamesAsync(int tenantId);
    Task<int> FixProspectNamesAsync(int tenantId);
    Task<int> BackfillProspectLocationsAsync(int tenantId);
    Task<(int duplicateSignalsRemoved, int duplicateProspectsMerged)> DeduplicateExistingAsync(int tenantId);
}
