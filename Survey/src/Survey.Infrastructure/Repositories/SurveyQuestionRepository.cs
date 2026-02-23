using Microsoft.EntityFrameworkCore;
using Survey.Core.Entities;
using Survey.Core.Interfaces;
using Survey.Infrastructure.Data;

namespace Survey.Infrastructure.Repositories;

public class SurveyQuestionRepository : Repository<SurveyQuestion>, ISurveyQuestionRepository
{
    public SurveyQuestionRepository(SurveyDbContext context) : base(context)
    {
    }

    public async Task<IEnumerable<SurveyQuestion>> GetQuestionsBySurveyAsync(int surveyId)
    {
        return await _dbSet
            .Include(sq => sq.Options.OrderBy(o => o.OrderIndex))
            .Include(sq => sq.QuestionBank)
                .ThenInclude(qb => qb.Options)
            .Where(sq => sq.SurveyId == surveyId)
            .OrderBy(sq => sq.OrderIndex)
            .ToListAsync();
    }

    public async Task<SurveyQuestion?> GetQuestionWithOptionsAsync(int surveyQuestionId)
    {
        return await _dbSet
            .Include(sq => sq.Options.OrderBy(o => o.OrderIndex))
            .Include(sq => sq.QuestionBank)
                .ThenInclude(qb => qb.Options)
            .FirstOrDefaultAsync(sq => sq.Id == surveyQuestionId);
    }

    public async Task<int> GetMaxOrderIndexAsync(int surveyId)
    {
        var maxOrder = await _dbSet
            .Where(sq => sq.SurveyId == surveyId)
            .MaxAsync(sq => (int?)sq.OrderIndex);

        return maxOrder ?? -1;
    }

    public async Task DeleteByIdAsync(int id)
    {
        await _context.Database.ExecuteSqlInterpolatedAsync(
            $"DELETE FROM SurveyQuestions WHERE Id = {id}");
    }
}
