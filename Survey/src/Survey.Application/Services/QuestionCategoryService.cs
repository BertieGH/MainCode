using AutoMapper;
using Survey.Core.DTOs.QuestionBank;
using Survey.Core.Entities;
using Survey.Core.Exceptions;
using Survey.Core.Interfaces;

namespace Survey.Application.Services;

public class QuestionCategoryService : IQuestionCategoryService
{
    private readonly IUnitOfWork _unitOfWork;
    private readonly IMapper _mapper;

    public QuestionCategoryService(IUnitOfWork unitOfWork, IMapper mapper)
    {
        _unitOfWork = unitOfWork;
        _mapper = mapper;
    }

    public async Task<IEnumerable<QuestionCategoryDto>> GetAllCategoriesAsync()
    {
        var categories = await _unitOfWork.QuestionCategoryRepository.GetCategoriesHierarchicalAsync();
        return _mapper.Map<IEnumerable<QuestionCategoryDto>>(categories);
    }

    public async Task<QuestionCategoryDto?> GetCategoryByIdAsync(int id)
    {
        var category = await _unitOfWork.QuestionCategoryRepository.GetCategoryWithSubCategoriesAsync(id);
        return category == null ? null : _mapper.Map<QuestionCategoryDto>(category);
    }

    public async Task<QuestionCategoryDto> CreateCategoryAsync(CreateQuestionCategoryDto dto)
    {
        var category = _mapper.Map<QuestionCategory>(dto);
        category.CreatedAt = DateTime.UtcNow;

        await _unitOfWork.QuestionCategoryRepository.AddAsync(category);
        await _unitOfWork.SaveChangesAsync();

        return _mapper.Map<QuestionCategoryDto>(category);
    }

    public async Task<QuestionCategoryDto> UpdateCategoryAsync(int id, UpdateQuestionCategoryDto dto)
    {
        var category = await _unitOfWork.QuestionCategoryRepository.GetByIdAsync(id);
        if (category == null)
            throw new NotFoundException("QuestionCategory", id);

        _mapper.Map(dto, category);

        await _unitOfWork.QuestionCategoryRepository.UpdateAsync(category);
        await _unitOfWork.SaveChangesAsync();

        return _mapper.Map<QuestionCategoryDto>(category);
    }

    public async Task DeleteCategoryAsync(int id)
    {
        var category = await _unitOfWork.QuestionCategoryRepository.GetByIdAsync(id);
        if (category == null)
            throw new NotFoundException("QuestionCategory", id);

        // Check if category has questions
        var categoryWithQuestions = await _unitOfWork.QuestionCategoryRepository
            .GetCategoryWithSubCategoriesAsync(id);

        if (categoryWithQuestions?.Questions.Any() == true)
            throw new BusinessRuleException("Cannot delete category with existing questions");

        if (categoryWithQuestions?.SubCategories.Any() == true)
            throw new BusinessRuleException("Cannot delete category with subcategories");

        await _unitOfWork.QuestionCategoryRepository.DeleteAsync(category);
        await _unitOfWork.SaveChangesAsync();
    }
}
