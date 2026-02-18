using Survey.Core.DTOs.SurveyBuilder;

namespace Survey.Application.Services;

public interface ISurveyBuilderService
{
    Task<SurveyQuestionDto> AddQuestionToSurveyAsync(int surveyId, AddQuestionToSurveyDto dto);
    Task<SurveyQuestionDto> ModifyQuestionInSurveyAsync(int surveyId, int surveyQuestionId, ModifySurveyQuestionDto dto);
    Task RemoveQuestionFromSurveyAsync(int surveyId, int surveyQuestionId);
    Task<IEnumerable<SurveyQuestionDto>> ReorderQuestionsAsync(int surveyId, ReorderQuestionsDto dto);
    Task<IEnumerable<SurveyQuestionDto>> GetSurveyQuestionsAsync(int surveyId);
}
