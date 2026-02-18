using Survey.Core.DTOs.Analytics;

namespace Survey.Application.Services;

public interface IAnalyticsService
{
    Task<SurveyStatisticsDto> GetSurveyStatisticsAsync(int surveyId);
    Task<ClientSurveyHistoryDto> GetClientSurveyHistoryAsync(string crmClientId);
    Task<DashboardSummaryDto> GetDashboardSummaryAsync();
    Task<byte[]> ExportSurveyResultsAsync(int surveyId, string format);
    Task<List<SurveyResponseListDto>> GetSurveyResponsesAsync(int surveyId);
    Task<ResponseDetailDto> GetResponseDetailAsync(int responseId);
}
