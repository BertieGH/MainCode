using LeadPulse.Application.DTOs;

namespace LeadPulse.Application.Interfaces;

public interface IIntentAnalyzer
{
    Task<IntentAnalysisResult> AnalyzeAsync(string postContent, string platform);
}
