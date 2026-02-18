using Survey.Core.Entities;

namespace Survey.Core.Interfaces;

public interface ISurveyQuestionRepository : IRepository<SurveyQuestion>
{
    Task<IEnumerable<SurveyQuestion>> GetQuestionsBySurveyAsync(int surveyId);
    Task<SurveyQuestion?> GetQuestionWithOptionsAsync(int surveyQuestionId);
    Task<int> GetMaxOrderIndexAsync(int surveyId);
}
