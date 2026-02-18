using System.Text.Json;
using AutoMapper;
using Survey.Core.DTOs.SurveyExecution;
using Survey.Core.Entities;
using Survey.Core.Enums;
using Survey.Core.Exceptions;
using Survey.Core.Interfaces;

namespace Survey.Application.Services;

public class SurveyExecutionService : ISurveyExecutionService
{
    private readonly ISurveyRepository _surveyRepository;
    private readonly IResponseRepository _responseRepository;
    private readonly IFieldMappingService _fieldMappingService;
    private readonly IUnitOfWork _unitOfWork;
    private readonly IMapper _mapper;

    public SurveyExecutionService(
        ISurveyRepository surveyRepository,
        IResponseRepository responseRepository,
        IFieldMappingService fieldMappingService,
        IUnitOfWork unitOfWork,
        IMapper mapper)
    {
        _surveyRepository = surveyRepository;
        _responseRepository = responseRepository;
        _fieldMappingService = fieldMappingService;
        _unitOfWork = unitOfWork;
        _mapper = mapper;
    }

    public async Task<SurveyExecutionDto> GetSurveyForClientAsync(int surveyId, string crmClientId, Dictionary<string, string> clientData)
    {
        var survey = await _surveyRepository.GetSurveyWithQuestionsAsync(surveyId);
        if (survey == null)
            throw new NotFoundException(nameof(Core.Entities.Survey), surveyId);

        if (survey.Status != SurveyStatus.Active)
            throw new BusinessRuleException("Survey is not active");

        // Apply field mappings to client data
        var mappedData = await _fieldMappingService.ApplyMappingsAsync(clientData);

        var executionDto = new SurveyExecutionDto
        {
            SurveyId = survey.Id,
            SurveyTitle = survey.Title,
            Description = survey.Description,
            CrmClientId = crmClientId,
            ClientData = mappedData,
            Questions = survey.Questions.OrderBy(q => q.OrderIndex).Select(q => new ExecutionQuestionDto
            {
                SurveyQuestionId = q.Id,
                QuestionText = !string.IsNullOrEmpty(q.QuestionText)
                    ? q.QuestionText
                    : q.QuestionBank.QuestionText,
                QuestionType = q.QuestionType.ToString(),
                IsRequired = q.IsRequired,
                OrderIndex = q.OrderIndex,
                Options = q.Options.OrderBy(o => o.OrderIndex).Select(o => new ExecutionOptionDto
                {
                    Id = o.Id,
                    OptionText = o.OptionText,
                    OrderIndex = o.OrderIndex
                }).ToList()
            }).ToList()
        };

        return executionDto;
    }

    public async Task<ResponseDto> StartSurveyResponseAsync(StartSurveyDto dto)
    {
        var survey = await _surveyRepository.GetByIdAsync(dto.SurveyId);
        if (survey == null)
            throw new NotFoundException(nameof(Core.Entities.Survey), dto.SurveyId);

        if (survey.Status != SurveyStatus.Active)
            throw new BusinessRuleException("Survey is not active");

        // Apply field mappings
        var mappedData = await _fieldMappingService.ApplyMappingsAsync(dto.ClientData);

        var response = new Core.Entities.Response
        {
            SurveyId = dto.SurveyId,
            CrmClientId = dto.CrmClientId,
            ClientData = JsonSerializer.Serialize(mappedData),
            StartedAt = DateTime.UtcNow,
            IsComplete = false,
            CreatedAt = DateTime.UtcNow
        };

        await _responseRepository.AddAsync(response);
        await _unitOfWork.SaveChangesAsync();

        return _mapper.Map<ResponseDto>(response);
    }

    public async Task SubmitAnswersAsync(SubmitResponseDto dto)
    {
        var response = await _responseRepository.GetResponseWithAnswersAsync(dto.ResponseId);
        if (response == null)
            throw new NotFoundException(nameof(Core.Entities.Response), dto.ResponseId);

        if (response.IsComplete)
            throw new BusinessRuleException("Response has already been completed");

        // Remove existing answers for the questions being updated
        var existingAnswerIds = response.Answers
            .Where(a => dto.Answers.Any(na => na.SurveyQuestionId == a.SurveyQuestionId))
            .Select(a => a.Id)
            .ToList();

        foreach (var answerId in existingAnswerIds)
        {
            var answerToRemove = response.Answers.First(a => a.Id == answerId);
            response.Answers.Remove(answerToRemove);
        }

        // Add new answers
        foreach (var answerDto in dto.Answers)
        {
            var answer = new ResponseAnswer
            {
                ResponseId = dto.ResponseId,
                SurveyQuestionId = answerDto.SurveyQuestionId,
                AnswerText = answerDto.AnswerText,
                SelectedOptionIds = answerDto.SelectedOptionIds,
                CreatedAt = DateTime.UtcNow
            };
            response.Answers.Add(answer);
        }

        await _responseRepository.UpdateAsync(response);
        await _unitOfWork.SaveChangesAsync();
    }

    public async Task<ResponseDto> CompleteSurveyAsync(int responseId)
    {
        var response = await _responseRepository.GetResponseWithAnswersAsync(responseId);
        if (response == null)
            throw new NotFoundException(nameof(Core.Entities.Response), responseId);

        if (response.IsComplete)
            throw new BusinessRuleException("Response has already been completed");

        // Validate all required questions are answered
        var survey = await _surveyRepository.GetSurveyWithQuestionsAsync(response.SurveyId);
        if (survey == null)
            throw new NotFoundException(nameof(Core.Entities.Survey), response.SurveyId);

        var requiredQuestions = survey.Questions.Where(q => q.IsRequired).Select(q => q.Id).ToList();
        var answeredQuestions = response.Answers.Select(a => a.SurveyQuestionId).Distinct().ToList();
        var unansweredRequired = requiredQuestions.Except(answeredQuestions).ToList();

        if (unansweredRequired.Any())
        {
            throw new BusinessRuleException($"Required questions have not been answered: {string.Join(", ", unansweredRequired)}");
        }

        response.IsComplete = true;
        response.CompletedAt = DateTime.UtcNow;

        await _responseRepository.UpdateAsync(response);
        await _unitOfWork.SaveChangesAsync();

        return _mapper.Map<ResponseDto>(response);
    }

    public async Task<ResponseDto> GetResponseAsync(int responseId)
    {
        var response = await _responseRepository.GetResponseWithAnswersAsync(responseId);
        if (response == null)
            throw new NotFoundException(nameof(Core.Entities.Response), responseId);

        return _mapper.Map<ResponseDto>(response);
    }
}
