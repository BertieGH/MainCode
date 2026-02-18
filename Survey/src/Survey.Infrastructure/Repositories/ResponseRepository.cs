using Microsoft.EntityFrameworkCore;
using Survey.Core.Entities;
using Survey.Core.Interfaces;
using Survey.Infrastructure.Data;

namespace Survey.Infrastructure.Repositories;

public class ResponseRepository : Repository<Response>, IResponseRepository
{
    public ResponseRepository(SurveyDbContext context) : base(context)
    {
    }

    public async Task<Response?> GetResponseWithAnswersAsync(int id)
    {
        return await _dbSet
            .Include(r => r.Answers)
                .ThenInclude(a => a.SurveyQuestion)
                    .ThenInclude(sq => sq.Options)
            .Include(r => r.Survey)
            .FirstOrDefaultAsync(r => r.Id == id);
    }

    public async Task<IEnumerable<Response>> GetResponsesForSurveyAsync(int surveyId)
    {
        return await _dbSet
            .Include(r => r.Answers)
                .ThenInclude(a => a.SurveyQuestion)
            .Where(r => r.SurveyId == surveyId)
            .OrderByDescending(r => r.CreatedAt)
            .ToListAsync();
    }

    public async Task<IEnumerable<Response>> GetResponsesForClientAsync(string crmClientId)
    {
        return await _dbSet
            .Include(r => r.Survey)
            .Where(r => r.CrmClientId == crmClientId)
            .OrderByDescending(r => r.CreatedAt)
            .ToListAsync();
    }

    public async Task<int> GetTotalResponseCountAsync()
    {
        return await _dbSet.CountAsync();
    }

    public async Task<int> GetCompleteResponseCountForSurveyAsync(int surveyId)
    {
        return await _dbSet
            .Where(r => r.SurveyId == surveyId && r.IsComplete)
            .CountAsync();
    }

    public async Task<Dictionary<string, int>> GetUniqueClientsCountAsync()
    {
        return await _dbSet
            .GroupBy(r => r.CrmClientId)
            .Select(g => new { ClientId = g.Key, Count = g.Count() })
            .ToDictionaryAsync(x => x.ClientId, x => x.Count);
    }
}
