using Survey.Core.Entities;

namespace Survey.Core.Interfaces;

public interface IQuestionBankRepository : IRepository<QuestionBank>
{
    Task<QuestionBank?> GetQuestionWithOptionsAsync(int id);
    Task<IEnumerable<QuestionBank>> SearchQuestionsAsync(string? query, int? categoryId, int pageNumber, int pageSize);
    Task<int> SearchQuestionsCountAsync(string? query, int? categoryId);
    Task<IEnumerable<QuestionBank>> GetQuestionVersionsAsync(int questionId);
    Task<IEnumerable<QuestionBank>> GetQuestionsByCategoryAsync(int categoryId);
}
