using AutoMapper;
using Survey.Core.DTOs.Common;
using Survey.Core.DTOs.QuestionBank;
using Survey.Core.Entities;
using Survey.Core.Exceptions;
using Survey.Core.Interfaces;

namespace Survey.Application.Services;

public class QuestionBankService : IQuestionBankService
{
    private readonly IUnitOfWork _unitOfWork;
    private readonly IMapper _mapper;

    public QuestionBankService(IUnitOfWork unitOfWork, IMapper mapper)
    {
        _unitOfWork = unitOfWork;
        _mapper = mapper;
    }

    public async Task<PagedResult<QuestionBankDto>> GetAllQuestionsAsync(
        int pageNumber, int pageSize, int? categoryId = null, string? searchQuery = null)
    {
        var questions = await _unitOfWork.QuestionBankRepository
            .SearchQuestionsAsync(searchQuery, categoryId, pageNumber, pageSize);

        var totalCount = await _unitOfWork.QuestionBankRepository
            .SearchQuestionsCountAsync(searchQuery, categoryId);

        var questionDtos = _mapper.Map<List<QuestionBankDto>>(questions);

        return new PagedResult<QuestionBankDto>
        {
            Items = questionDtos,
            TotalCount = totalCount,
            PageNumber = pageNumber,
            PageSize = pageSize
        };
    }

    public async Task<QuestionBankDto?> GetQuestionByIdAsync(int id)
    {
        var question = await _unitOfWork.QuestionBankRepository.GetQuestionWithOptionsAsync(id);
        return question == null ? null : _mapper.Map<QuestionBankDto>(question);
    }

    public async Task<QuestionBankDto> CreateQuestionAsync(CreateQuestionBankDto dto)
    {
        var question = _mapper.Map<QuestionBank>(dto);
        question.Version = 1;
        question.IsActive = true;
        question.CreatedAt = DateTime.UtcNow;
        question.UpdatedAt = DateTime.UtcNow;

        await _unitOfWork.QuestionBankRepository.AddAsync(question);
        await _unitOfWork.SaveChangesAsync();

        return _mapper.Map<QuestionBankDto>(question);
    }

    public async Task<QuestionBankDto> UpdateQuestionAsync(int id, UpdateQuestionBankDto dto)
    {
        var existingQuestion = await _unitOfWork.QuestionBankRepository.GetQuestionWithOptionsAsync(id);
        if (existingQuestion == null)
            throw new NotFoundException("QuestionBank", id);

        // Create new version
        existingQuestion.IsActive = false;
        await _unitOfWork.QuestionBankRepository.UpdateAsync(existingQuestion);

        var newVersion = _mapper.Map<QuestionBank>(dto);
        newVersion.Version = existingQuestion.Version + 1;
        newVersion.IsActive = true;
        newVersion.CreatedAt = DateTime.UtcNow;
        newVersion.UpdatedAt = DateTime.UtcNow;
        newVersion.CreatedBy = existingQuestion.CreatedBy;

        await _unitOfWork.QuestionBankRepository.AddAsync(newVersion);
        await _unitOfWork.SaveChangesAsync();

        return _mapper.Map<QuestionBankDto>(newVersion);
    }

    public async Task DeleteQuestionAsync(int id)
    {
        var question = await _unitOfWork.QuestionBankRepository.GetByIdAsync(id);
        if (question == null)
            throw new NotFoundException("QuestionBank", id);

        // Soft delete
        question.IsActive = false;
        question.UpdatedAt = DateTime.UtcNow;

        await _unitOfWork.QuestionBankRepository.UpdateAsync(question);
        await _unitOfWork.SaveChangesAsync();
    }

    public async Task<IEnumerable<QuestionBankDto>> SearchQuestionsAsync(string query)
    {
        var questions = await _unitOfWork.QuestionBankRepository
            .SearchQuestionsAsync(query, null, 1, 50);

        return _mapper.Map<IEnumerable<QuestionBankDto>>(questions);
    }

    public async Task<IEnumerable<QuestionBankDto>> GetQuestionVersionsAsync(int questionId)
    {
        var versions = await _unitOfWork.QuestionBankRepository.GetQuestionVersionsAsync(questionId);
        return _mapper.Map<IEnumerable<QuestionBankDto>>(versions);
    }
}
