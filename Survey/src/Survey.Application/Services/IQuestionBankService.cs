using Survey.Core.DTOs.Common;
using Survey.Core.DTOs.QuestionBank;

namespace Survey.Application.Services;

public interface IQuestionBankService
{
    Task<PagedResult<QuestionBankDto>> GetAllQuestionsAsync(
        int pageNumber, int pageSize, int? categoryId = null, string? searchQuery = null);
    Task<QuestionBankDto?> GetQuestionByIdAsync(int id);
    Task<QuestionBankDto> CreateQuestionAsync(CreateQuestionBankDto dto);
    Task<QuestionBankDto> UpdateQuestionAsync(int id, UpdateQuestionBankDto dto);
    Task DeleteQuestionAsync(int id);
    Task<IEnumerable<QuestionBankDto>> SearchQuestionsAsync(string query);
    Task<IEnumerable<QuestionBankDto>> GetQuestionVersionsAsync(int questionId);
}
