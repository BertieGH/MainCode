using Microsoft.EntityFrameworkCore;
using Survey.Core.Entities;
using Survey.Core.Interfaces;
using Survey.Infrastructure.Data;

namespace Survey.Infrastructure.Repositories;

public class QuestionBankRepository : Repository<QuestionBank>, IQuestionBankRepository
{
    public QuestionBankRepository(SurveyDbContext context) : base(context)
    {
    }

    public async Task<QuestionBank?> GetQuestionWithOptionsAsync(int id)
    {
        return await _dbSet
            .Include(q => q.Options.OrderBy(o => o.OrderIndex))
            .Include(q => q.Category)
            .FirstOrDefaultAsync(q => q.Id == id);
    }

    public async Task<IEnumerable<QuestionBank>> SearchQuestionsAsync(
        string? query, int? categoryId, int pageNumber, int pageSize)
    {
        var queryable = _dbSet
            .Include(q => q.Options.OrderBy(o => o.OrderIndex))
            .Include(q => q.Category)
            .Where(q => q.IsActive)
            .AsQueryable();

        if (!string.IsNullOrWhiteSpace(query))
        {
            query = query.ToLower();
            queryable = queryable.Where(q =>
                q.QuestionText.ToLower().Contains(query) ||
                (q.Tags != null && q.Tags.ToLower().Contains(query))
            );
        }

        if (categoryId.HasValue)
        {
            queryable = queryable.Where(q => q.CategoryId == categoryId.Value);
        }

        return await queryable
            .OrderByDescending(q => q.CreatedAt)
            .Skip((pageNumber - 1) * pageSize)
            .Take(pageSize)
            .ToListAsync();
    }

    public async Task<int> SearchQuestionsCountAsync(string? query, int? categoryId)
    {
        var queryable = _dbSet
            .Where(q => q.IsActive)
            .AsQueryable();

        if (!string.IsNullOrWhiteSpace(query))
        {
            query = query.ToLower();
            queryable = queryable.Where(q =>
                q.QuestionText.ToLower().Contains(query) ||
                (q.Tags != null && q.Tags.ToLower().Contains(query))
            );
        }

        if (categoryId.HasValue)
        {
            queryable = queryable.Where(q => q.CategoryId == categoryId.Value);
        }

        return await queryable.CountAsync();
    }

    public async Task<IEnumerable<QuestionBank>> GetQuestionVersionsAsync(int questionId)
    {
        var question = await _dbSet.FindAsync(questionId);
        if (question == null) return Enumerable.Empty<QuestionBank>();

        // Find all versions by matching the base question text pattern
        return await _dbSet
            .Include(q => q.Options)
            .Include(q => q.Category)
            .Where(q => q.Id == questionId ||
                       (q.QuestionText == question.QuestionText && q.CategoryId == question.CategoryId))
            .OrderByDescending(q => q.Version)
            .ToListAsync();
    }

    public async Task<IEnumerable<QuestionBank>> GetQuestionsByCategoryAsync(int categoryId)
    {
        return await _dbSet
            .Include(q => q.Options.OrderBy(o => o.OrderIndex))
            .Where(q => q.CategoryId == categoryId && q.IsActive)
            .OrderByDescending(q => q.CreatedAt)
            .ToListAsync();
    }
}
