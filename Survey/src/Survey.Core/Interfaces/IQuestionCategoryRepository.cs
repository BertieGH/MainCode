using Survey.Core.Entities;

namespace Survey.Core.Interfaces;

public interface IQuestionCategoryRepository : IRepository<QuestionCategory>
{
    Task<IEnumerable<QuestionCategory>> GetCategoriesHierarchicalAsync();
    Task<QuestionCategory?> GetCategoryWithSubCategoriesAsync(int id);
}
