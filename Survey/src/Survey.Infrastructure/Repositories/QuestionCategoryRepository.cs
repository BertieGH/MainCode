using Microsoft.EntityFrameworkCore;
using Survey.Core.Entities;
using Survey.Core.Interfaces;
using Survey.Infrastructure.Data;

namespace Survey.Infrastructure.Repositories;

public class QuestionCategoryRepository : Repository<QuestionCategory>, IQuestionCategoryRepository
{
    public QuestionCategoryRepository(SurveyDbContext context) : base(context)
    {
    }

    public async Task<IEnumerable<QuestionCategory>> GetCategoriesHierarchicalAsync()
    {
        // Get all categories with their questions count
        var categories = await _dbSet
            .Include(c => c.Questions)
            .OrderBy(c => c.Name)
            .ToListAsync();

        // Return only root categories (ParentCategoryId is null)
        // Navigation properties will include subcategories
        return categories.Where(c => c.ParentCategoryId == null).ToList();
    }

    public async Task<QuestionCategory?> GetCategoryWithSubCategoriesAsync(int id)
    {
        return await _dbSet
            .Include(c => c.SubCategories)
            .Include(c => c.Questions)
            .Include(c => c.ParentCategory)
            .FirstOrDefaultAsync(c => c.Id == id);
    }
}
