using Microsoft.EntityFrameworkCore;
using Survey.Core.Interfaces;
using Survey.Infrastructure.Data;

namespace Survey.Infrastructure.Repositories;

public class SurveyRepository : Repository<Core.Entities.Survey>, ISurveyRepository
{
    public SurveyRepository(SurveyDbContext context) : base(context)
    {
    }

    public async Task<Core.Entities.Survey?> GetSurveyWithQuestionsAsync(int id)
    {
        return await _dbSet
            .Include(s => s.Questions.OrderBy(q => q.OrderIndex))
                .ThenInclude(q => q.Options.OrderBy(o => o.OrderIndex))
            .Include(s => s.Questions)
                .ThenInclude(q => q.QuestionBank)
            .FirstOrDefaultAsync(s => s.Id == id);
    }

    public async Task<IEnumerable<Core.Entities.Survey>> GetActiveSurveysAsync()
    {
        return await _dbSet
            .Include(s => s.Questions)
            .Where(s => s.Status == Core.Enums.SurveyStatus.Active)
            .OrderByDescending(s => s.CreatedAt)
            .ToListAsync();
    }

    public async Task<IEnumerable<Core.Entities.Survey>> GetSurveysPagedAsync(int pageNumber, int pageSize)
    {
        return await _dbSet
            .Include(s => s.Questions)
            .OrderByDescending(s => s.CreatedAt)
            .Skip((pageNumber - 1) * pageSize)
            .Take(pageSize)
            .ToListAsync();
    }

    public async Task<int> GetTotalSurveysCountAsync()
    {
        return await _dbSet.CountAsync();
    }
}
