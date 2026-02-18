using Survey.Core.DTOs.QuestionBank;

namespace Survey.Application.Services;

public interface IQuestionCategoryService
{
    Task<IEnumerable<QuestionCategoryDto>> GetAllCategoriesAsync();
    Task<QuestionCategoryDto?> GetCategoryByIdAsync(int id);
    Task<QuestionCategoryDto> CreateCategoryAsync(CreateQuestionCategoryDto dto);
    Task<QuestionCategoryDto> UpdateCategoryAsync(int id, UpdateQuestionCategoryDto dto);
    Task DeleteCategoryAsync(int id);
}
