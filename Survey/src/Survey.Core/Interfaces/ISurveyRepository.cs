using Survey.Core.Entities;

namespace Survey.Core.Interfaces;

public interface ISurveyRepository : IRepository<Entities.Survey>
{
    Task<Entities.Survey?> GetSurveyWithQuestionsAsync(int id);
    Task<IEnumerable<Entities.Survey>> GetActiveSurveysAsync();
    Task<IEnumerable<Entities.Survey>> GetSurveysPagedAsync(int pageNumber, int pageSize);
    Task<int> GetTotalSurveysCountAsync();
}
