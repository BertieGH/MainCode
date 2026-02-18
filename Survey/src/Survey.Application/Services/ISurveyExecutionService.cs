using Survey.Core.DTOs.SurveyExecution;

namespace Survey.Application.Services;

public interface ISurveyExecutionService
{
    Task<SurveyExecutionDto> GetSurveyForClientAsync(int surveyId, string crmClientId, Dictionary<string, string> clientData);
    Task<ResponseDto> StartSurveyResponseAsync(StartSurveyDto dto);
    Task SubmitAnswersAsync(SubmitResponseDto dto);
    Task<ResponseDto> CompleteSurveyAsync(int responseId);
    Task<ResponseDto> GetResponseAsync(int responseId);
}
