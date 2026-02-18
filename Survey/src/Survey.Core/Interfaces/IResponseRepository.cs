using Survey.Core.Entities;

namespace Survey.Core.Interfaces;

public interface IResponseRepository : IRepository<Response>
{
    Task<Response?> GetResponseWithAnswersAsync(int id);
    Task<IEnumerable<Response>> GetResponsesForSurveyAsync(int surveyId);
    Task<IEnumerable<Response>> GetResponsesForClientAsync(string crmClientId);
    Task<int> GetTotalResponseCountAsync();
    Task<int> GetCompleteResponseCountForSurveyAsync(int surveyId);
    Task<Dictionary<string, int>> GetUniqueClientsCountAsync();
}
