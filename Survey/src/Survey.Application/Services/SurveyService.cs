using AutoMapper;
using Survey.Core.DTOs.Common;
using Survey.Core.DTOs.SurveyBuilder;
using Survey.Core.Enums;
using Survey.Core.Exceptions;
using Survey.Core.Interfaces;

namespace Survey.Application.Services;

public class SurveyService : ISurveyService
{
    private readonly ISurveyRepository _surveyRepository;
    private readonly ISurveyQuestionRepository _surveyQuestionRepository;
    private readonly IUnitOfWork _unitOfWork;
    private readonly IMapper _mapper;

    public SurveyService(
        ISurveyRepository surveyRepository,
        ISurveyQuestionRepository surveyQuestionRepository,
        IUnitOfWork unitOfWork,
        IMapper mapper)
    {
        _surveyRepository = surveyRepository;
        _surveyQuestionRepository = surveyQuestionRepository;
        _unitOfWork = unitOfWork;
        _mapper = mapper;
    }

    public async Task<PagedResult<SurveyDto>> GetAllSurveysAsync(int pageNumber, int pageSize)
    {
        var surveys = await _surveyRepository.GetSurveysPagedAsync(pageNumber, pageSize);
        var totalCount = await _surveyRepository.GetTotalSurveysCountAsync();

        var surveyDtos = _mapper.Map<List<SurveyDto>>(surveys);

        return new PagedResult<SurveyDto>
        {
            Items = surveyDtos,
            TotalCount = totalCount,
            PageNumber = pageNumber,
            PageSize = pageSize
        };
    }

    public async Task<SurveyDto?> GetSurveyByIdAsync(int id)
    {
        var survey = await _surveyRepository.GetSurveyWithQuestionsAsync(id);
        return survey == null ? null : _mapper.Map<SurveyDto>(survey);
    }

    public async Task<SurveyDto> CreateSurveyAsync(CreateSurveyDto dto)
    {
        var survey = _mapper.Map<Core.Entities.Survey>(dto);
        survey.Status = SurveyStatus.Draft;
        survey.CreatedAt = DateTime.UtcNow;
        survey.UpdatedAt = DateTime.UtcNow;

        await _surveyRepository.AddAsync(survey);
        await _unitOfWork.SaveChangesAsync();

        return _mapper.Map<SurveyDto>(survey);
    }

    public async Task<SurveyDto> UpdateSurveyAsync(int id, UpdateSurveyDto dto)
    {
        var survey = await _surveyRepository.GetByIdAsync(id);
        if (survey == null)
            throw new NotFoundException("Survey", id);

        _mapper.Map(dto, survey);
        survey.UpdatedAt = DateTime.UtcNow;

        await _surveyRepository.UpdateAsync(survey);
        await _unitOfWork.SaveChangesAsync();

        return _mapper.Map<SurveyDto>(survey);
    }

    public async Task DeleteSurveyAsync(int id)
    {
        var survey = await _surveyRepository.GetByIdAsync(id);
        if (survey == null)
            throw new NotFoundException("Survey", id);

        // Check if survey has responses
        if (survey.Responses?.Any() == true)
            throw new BusinessRuleException("Cannot delete survey with existing responses");

        await _surveyRepository.DeleteAsync(survey);
        await _unitOfWork.SaveChangesAsync();
    }

    public async Task<SurveyDto> UpdateSurveyStatusAsync(int id, SurveyStatus status)
    {
        var survey = await _surveyRepository.GetSurveyWithQuestionsAsync(id);
        if (survey == null)
            throw new NotFoundException("Survey", id);

        // Validate status change
        if (status == SurveyStatus.Active && !survey.Questions.Any())
            throw new BusinessRuleException("Cannot activate survey without questions");

        survey.Status = status;
        survey.UpdatedAt = DateTime.UtcNow;

        await _surveyRepository.UpdateAsync(survey);
        await _unitOfWork.SaveChangesAsync();

        return _mapper.Map<SurveyDto>(survey);
    }

    public async Task<SurveyDto> DuplicateSurveyAsync(int id, string newTitle, string? createdBy = null)
    {
        var originalSurvey = await _surveyRepository.GetSurveyWithQuestionsAsync(id);
        if (originalSurvey == null)
            throw new NotFoundException("Survey", id);

        var newSurvey = new Core.Entities.Survey
        {
            Title = newTitle,
            Description = originalSurvey.Description,
            Status = SurveyStatus.Draft,
            CreatedAt = DateTime.UtcNow,
            UpdatedAt = DateTime.UtcNow,
            CreatedBy = createdBy ?? originalSurvey.CreatedBy
        };

        await _surveyRepository.AddAsync(newSurvey);

        // Copy questions
        foreach (var originalQuestion in originalSurvey.Questions.OrderBy(q => q.OrderIndex))
        {
            var newQuestion = new Core.Entities.SurveyQuestion
            {
                SurveyId = newSurvey.Id,
                QuestionBankId = originalQuestion.QuestionBankId,
                QuestionText = originalQuestion.QuestionText,
                QuestionType = originalQuestion.QuestionType,
                IsRequired = originalQuestion.IsRequired,
                OrderIndex = originalQuestion.OrderIndex,
                IsModified = originalQuestion.IsModified,
                CreatedAt = DateTime.UtcNow
            };

            await _surveyQuestionRepository.AddAsync(newQuestion);

            // Copy options
            foreach (var originalOption in originalQuestion.Options.OrderBy(o => o.OrderIndex))
            {
                newQuestion.Options.Add(new Core.Entities.SurveyQuestionOption
                {
                    OptionText = originalOption.OptionText,
                    OrderIndex = originalOption.OrderIndex
                });
            }
        }

        await _unitOfWork.SaveChangesAsync();

        return _mapper.Map<SurveyDto>(newSurvey);
    }
}
