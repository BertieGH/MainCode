using AutoMapper;
using Survey.Core.DTOs.SurveyBuilder;
using Survey.Core.Entities;
using Survey.Core.Enums;
using Survey.Core.Exceptions;
using Survey.Core.Interfaces;

namespace Survey.Application.Services;

public class SurveyBuilderService : ISurveyBuilderService
{
    private readonly ISurveyRepository _surveyRepository;
    private readonly ISurveyQuestionRepository _surveyQuestionRepository;
    private readonly IQuestionBankRepository _questionBankRepository;
    private readonly IUnitOfWork _unitOfWork;
    private readonly IMapper _mapper;

    public SurveyBuilderService(
        ISurveyRepository surveyRepository,
        ISurveyQuestionRepository surveyQuestionRepository,
        IQuestionBankRepository questionBankRepository,
        IUnitOfWork unitOfWork,
        IMapper mapper)
    {
        _surveyRepository = surveyRepository;
        _surveyQuestionRepository = surveyQuestionRepository;
        _questionBankRepository = questionBankRepository;
        _unitOfWork = unitOfWork;
        _mapper = mapper;
    }

    public async Task<SurveyQuestionDto> AddQuestionToSurveyAsync(int surveyId, AddQuestionToSurveyDto dto)
    {
        var survey = await _surveyRepository.GetByIdAsync(surveyId);
        if (survey == null)
            throw new NotFoundException("Survey", surveyId);

        var questionBank = await _questionBankRepository.GetQuestionWithOptionsAsync(dto.QuestionBankId);
        if (questionBank == null)
            throw new NotFoundException("QuestionBank", dto.QuestionBankId);

        // Get next order index
        int orderIndex = dto.OrderIndex ?? await _surveyQuestionRepository.GetMaxOrderIndexAsync(surveyId) + 1;

        var surveyQuestion = new SurveyQuestion
        {
            SurveyId = surveyId,
            QuestionBankId = dto.QuestionBankId,
            QuestionText = null, // Use bank's text by default
            QuestionType = questionBank.QuestionType,
            IsRequired = dto.IsRequired,
            OrderIndex = orderIndex,
            IsModified = false,
            CreatedAt = DateTime.UtcNow
        };

        // Copy options from question bank
        foreach (var bankOption in questionBank.Options.OrderBy(o => o.OrderIndex))
        {
            surveyQuestion.Options.Add(new SurveyQuestionOption
            {
                OptionText = bankOption.OptionText,
                OrderIndex = bankOption.OrderIndex
            });
        }

        await _surveyQuestionRepository.AddAsync(surveyQuestion);
        await _unitOfWork.SaveChangesAsync();

        return _mapper.Map<SurveyQuestionDto>(surveyQuestion);
    }

    public async Task<SurveyQuestionDto> ModifyQuestionInSurveyAsync(
        int surveyId, int surveyQuestionId, ModifySurveyQuestionDto dto)
    {
        var surveyQuestion = await _surveyQuestionRepository.GetQuestionWithOptionsAsync(surveyQuestionId);
        if (surveyQuestion == null || surveyQuestion.SurveyId != surveyId)
            throw new NotFoundException("SurveyQuestion", surveyQuestionId);

        // Modify question text if provided
        if (!string.IsNullOrWhiteSpace(dto.QuestionText))
        {
            surveyQuestion.QuestionText = dto.QuestionText;
            surveyQuestion.IsModified = true;
        }

        surveyQuestion.IsRequired = dto.IsRequired;

        // Modify options if provided
        if (dto.Options != null && dto.Options.Any())
        {
            // Clear existing options
            surveyQuestion.Options.Clear();

            // Add new options
            foreach (var optionDto in dto.Options.OrderBy(o => o.OrderIndex))
            {
                surveyQuestion.Options.Add(new SurveyQuestionOption
                {
                    SurveyQuestionId = surveyQuestionId,
                    OptionText = optionDto.OptionText,
                    OrderIndex = optionDto.OrderIndex
                });
            }

            surveyQuestion.IsModified = true;
        }

        await _surveyQuestionRepository.UpdateAsync(surveyQuestion);
        await _unitOfWork.SaveChangesAsync();

        return _mapper.Map<SurveyQuestionDto>(surveyQuestion);
    }

    public async Task RemoveQuestionFromSurveyAsync(int surveyId, int surveyQuestionId)
    {
        var surveyQuestion = await _surveyQuestionRepository.GetByIdAsync(surveyQuestionId);
        if (surveyQuestion == null || surveyQuestion.SurveyId != surveyId)
            throw new NotFoundException("SurveyQuestion", surveyQuestionId);

        await _surveyQuestionRepository.DeleteAsync(surveyQuestion);

        // Re-order remaining questions
        var remainingQuestions = await _surveyQuestionRepository.GetQuestionsBySurveyAsync(surveyId);
        int index = 0;
        foreach (var question in remainingQuestions.OrderBy(q => q.OrderIndex))
        {
            question.OrderIndex = index++;
            await _surveyQuestionRepository.UpdateAsync(question);
        }
        await _unitOfWork.SaveChangesAsync();
    }

    public async Task<IEnumerable<SurveyQuestionDto>> ReorderQuestionsAsync(int surveyId, ReorderQuestionsDto dto)
    {
        var survey = await _surveyRepository.GetByIdAsync(surveyId);
        if (survey == null)
            throw new NotFoundException("Survey", surveyId);

        // Update order index for each question
        foreach (var questionOrder in dto.Questions)
        {
            var surveyQuestion = await _surveyQuestionRepository.GetByIdAsync(questionOrder.SurveyQuestionId);
            if (surveyQuestion != null && surveyQuestion.SurveyId == surveyId)
            {
                surveyQuestion.OrderIndex = questionOrder.OrderIndex;
                await _surveyQuestionRepository.UpdateAsync(surveyQuestion);
            }
        }
        await _unitOfWork.SaveChangesAsync();

        var updatedQuestions = await _surveyQuestionRepository.GetQuestionsBySurveyAsync(surveyId);
        return _mapper.Map<IEnumerable<SurveyQuestionDto>>(updatedQuestions);
    }

    public async Task<IEnumerable<SurveyQuestionDto>> GetSurveyQuestionsAsync(int surveyId)
    {
        var questions = await _surveyQuestionRepository.GetQuestionsBySurveyAsync(surveyId);
        return _mapper.Map<IEnumerable<SurveyQuestionDto>>(questions);
    }
}
