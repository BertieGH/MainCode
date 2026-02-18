using System.Text;
using System.Text.Json;
using Survey.Core.DTOs.Analytics;
using Survey.Core.Enums;
using Survey.Core.Exceptions;
using Survey.Core.Interfaces;

namespace Survey.Application.Services;

public class AnalyticsService : IAnalyticsService
{
    private readonly ISurveyRepository _surveyRepository;
    private readonly IResponseRepository _responseRepository;

    public AnalyticsService(
        ISurveyRepository surveyRepository,
        IResponseRepository responseRepository)
    {
        _surveyRepository = surveyRepository;
        _responseRepository = responseRepository;
    }

    public async Task<SurveyStatisticsDto> GetSurveyStatisticsAsync(int surveyId)
    {
        var survey = await _surveyRepository.GetSurveyWithQuestionsAsync(surveyId);
        if (survey == null)
            throw new NotFoundException("Survey", surveyId);

        var responses = await _responseRepository.GetResponsesForSurveyAsync(surveyId);
        var responseList = responses.ToList();

        var completeResponses = responseList.Where(r => r.IsComplete).ToList();
        var totalResponses = responseList.Count;

        var statistics = new SurveyStatisticsDto
        {
            SurveyId = surveyId,
            SurveyTitle = survey.Title,
            TotalResponses = totalResponses,
            CompleteResponses = completeResponses.Count,
            IncompleteResponses = totalResponses - completeResponses.Count,
            CompletionRate = totalResponses > 0 ? (double)completeResponses.Count / totalResponses * 100 : 0,
            FirstResponseDate = responseList.Any() ? responseList.Min(r => r.CreatedAt) : null,
            LastResponseDate = responseList.Any() ? responseList.Max(r => r.CreatedAt) : null,
            AverageCompletionTimeMinutes = CalculateAverageCompletionTime(completeResponses)
        };

        // Question-level analytics
        foreach (var question in survey.Questions.OrderBy(q => q.OrderIndex))
        {
            var questionAnalytics = new QuestionAnalyticsDto
            {
                QuestionId = question.Id,
                QuestionText = !string.IsNullOrEmpty(question.QuestionText)
                    ? question.QuestionText
                    : question.QuestionBank.QuestionText,
                QuestionType = question.QuestionType
            };

            var answers = completeResponses
                .SelectMany(r => r.Answers)
                .Where(a => a.SurveyQuestionId == question.Id)
                .ToList();

            questionAnalytics.TotalAnswers = answers.Count;

            switch (question.QuestionType)
            {
                case QuestionType.SingleChoice:
                case QuestionType.MultipleChoice:
                    questionAnalytics.OptionDistribution = CalculateOptionDistribution(answers, question);
                    break;

                case QuestionType.Rating:
                    questionAnalytics.AverageRating = CalculateAverageRating(answers);
                    questionAnalytics.OptionDistribution = CalculateRatingDistribution(answers);
                    break;

                case QuestionType.Text:
                    questionAnalytics.TextResponses = answers
                        .Where(a => !string.IsNullOrWhiteSpace(a.AnswerText))
                        .Select(a => a.AnswerText!)
                        .ToList();
                    break;

                case QuestionType.YesNo:
                    var yesNoDistribution = CalculateYesNoDistribution(answers);
                    questionAnalytics.YesCount = yesNoDistribution.GetValueOrDefault("Yes", 0);
                    questionAnalytics.NoCount = yesNoDistribution.GetValueOrDefault("No", 0);
                    break;
            }

            statistics.QuestionAnalytics.Add(questionAnalytics);
        }

        return statistics;
    }

    public async Task<ClientSurveyHistoryDto> GetClientSurveyHistoryAsync(string crmClientId)
    {
        var responses = await _responseRepository.GetResponsesForClientAsync(crmClientId);
        var responseList = responses.ToList();

        var history = new ClientSurveyHistoryDto
        {
            CrmClientId = crmClientId,
            ClientName = ExtractClientName(responseList.FirstOrDefault()),
            TotalSurveysCompleted = responseList.Count(r => r.IsComplete),
            FirstSurveyDate = responseList.Any() ? responseList.Min(r => r.CreatedAt) : null,
            LastSurveyDate = responseList.Any() ? responseList.Max(r => r.CreatedAt) : null
        };

        history.Responses = responseList.Select(r => new ClientSurveyResponseDto
        {
            ResponseId = r.Id,
            SurveyId = r.SurveyId,
            SurveyTitle = r.Survey.Title,
            CompletedAt = r.CompletedAt ?? r.CreatedAt,
            IsComplete = r.IsComplete
        }).ToList();

        return history;
    }

    public async Task<DashboardSummaryDto> GetDashboardSummaryAsync()
    {
        var allSurveys = await _surveyRepository.GetAllAsync();
        var surveyList = allSurveys.ToList();
        var totalResponses = await _responseRepository.GetTotalResponseCountAsync();
        var uniqueClients = await _responseRepository.GetUniqueClientsCountAsync();

        var dashboard = new DashboardSummaryDto
        {
            TotalSurveys = surveyList.Count,
            ActiveSurveys = surveyList.Count(s => s.Status == SurveyStatus.Active),
            TotalResponses = totalResponses,
            TotalClients = uniqueClients.Count
        };

        // Calculate overall completion rate
        var allResponses = new List<Core.Entities.Response>();
        foreach (var survey in surveyList)
        {
            var responses = await _responseRepository.GetResponsesForSurveyAsync(survey.Id);
            allResponses.AddRange(responses);
        }

        if (allResponses.Any())
        {
            dashboard.OverallCompletionRate =
                (double)allResponses.Count(r => r.IsComplete) / allResponses.Count * 100;
        }

        // Recent surveys
        dashboard.RecentSurveys = surveyList
            .OrderByDescending(s => s.CreatedAt)
            .Take(5)
            .Select(s => new SurveySummaryDto
            {
                SurveyId = s.Id,
                Title = s.Title,
                Status = s.Status.ToString(),
                ResponseCount = allResponses.Count(r => r.SurveyId == s.Id),
                CompletionRate = CalculateSurveyCompletionRate(s.Id, allResponses)
            })
            .ToList();

        // Recent responses
        dashboard.RecentResponses = allResponses
            .Where(r => r.IsComplete)
            .OrderByDescending(r => r.CompletedAt)
            .Take(10)
            .Select(r => new RecentResponseDto
            {
                ResponseId = r.Id,
                SurveyTitle = r.Survey.Title,
                CrmClientId = r.CrmClientId,
                CompletedAt = r.CompletedAt ?? r.CreatedAt
            })
            .ToList();

        return dashboard;
    }

    public async Task<List<SurveyResponseListDto>> GetSurveyResponsesAsync(int surveyId)
    {
        var survey = await _surveyRepository.GetByIdAsync(surveyId);
        if (survey == null)
            throw new NotFoundException("Survey", surveyId);

        var responses = await _responseRepository.GetResponsesForSurveyAsync(surveyId);

        return responses.Select(r => new SurveyResponseListDto
        {
            ResponseId = r.Id,
            CrmClientId = r.CrmClientId,
            StartedAt = r.StartedAt,
            CompletedAt = r.CompletedAt,
            IsComplete = r.IsComplete
        }).OrderByDescending(r => r.CompletedAt ?? r.StartedAt).ToList();
    }

    public async Task<ResponseDetailDto> GetResponseDetailAsync(int responseId)
    {
        var response = await _responseRepository.GetResponseWithAnswersAsync(responseId);
        if (response == null)
            throw new NotFoundException("Response", responseId);

        var survey = await _surveyRepository.GetSurveyWithQuestionsAsync(response.SurveyId);

        var detail = new ResponseDetailDto
        {
            ResponseId = response.Id,
            SurveyId = response.SurveyId,
            SurveyTitle = survey?.Title ?? "Unknown Survey",
            CrmClientId = response.CrmClientId,
            StartedAt = response.StartedAt,
            CompletedAt = response.CompletedAt,
            IsComplete = response.IsComplete
        };

        foreach (var answer in response.Answers)
        {
            var question = survey?.Questions.FirstOrDefault(q => q.Id == answer.SurveyQuestionId);
            var answerDetail = new ResponseAnswerDetailDto
            {
                SurveyQuestionId = answer.SurveyQuestionId,
                QuestionText = question != null
                    ? (!string.IsNullOrEmpty(question.QuestionText) ? question.QuestionText : question.QuestionBank.QuestionText)
                    : "Unknown Question",
                QuestionType = question?.QuestionType.ToString() ?? "Unknown",
                AnswerText = answer.AnswerText
            };

            if (answer.SelectedOptionIds != null && answer.SelectedOptionIds.Any() && question != null)
            {
                answerDetail.SelectedOptions = answer.SelectedOptionIds
                    .Select(optId => question.Options.FirstOrDefault(o => o.Id == optId)?.OptionText ?? $"Option {optId}")
                    .ToList();
            }

            detail.Answers.Add(answerDetail);
        }

        return detail;
    }

    public async Task<byte[]> ExportSurveyResultsAsync(int surveyId, string format)
    {
        var statistics = await GetSurveyStatisticsAsync(surveyId);

        return format.ToLower() switch
        {
            "csv" => ExportToCsv(statistics),
            "json" => ExportToJson(statistics),
            _ => throw new BusinessRuleException($"Unsupported export format: {format}")
        };
    }

    private double CalculateAverageCompletionTime(List<Core.Entities.Response> responses)
    {
        if (!responses.Any()) return 0;

        var completionTimes = responses
            .Where(r => r.CompletedAt.HasValue)
            .Select(r => (r.CompletedAt!.Value - r.StartedAt).TotalMinutes)
            .ToList();

        return completionTimes.Any() ? completionTimes.Average() : 0;
    }

    private Dictionary<string, int> CalculateOptionDistribution(
        List<Core.Entities.ResponseAnswer> answers,
        Core.Entities.SurveyQuestion question)
    {
        var distribution = new Dictionary<string, int>();

        foreach (var answer in answers)
        {
            if (answer.SelectedOptionIds != null && answer.SelectedOptionIds.Any())
            {
                foreach (var optionId in answer.SelectedOptionIds)
                {
                    var option = question.Options.FirstOrDefault(o => o.Id == optionId);
                    if (option != null)
                    {
                        if (distribution.ContainsKey(option.OptionText))
                            distribution[option.OptionText]++;
                        else
                            distribution[option.OptionText] = 1;
                    }
                }
            }
        }

        return distribution;
    }

    private double? CalculateAverageRating(List<Core.Entities.ResponseAnswer> answers)
    {
        var ratings = answers
            .Where(a => !string.IsNullOrEmpty(a.AnswerText) && int.TryParse(a.AnswerText, out _))
            .Select(a => int.Parse(a.AnswerText!))
            .ToList();

        return ratings.Any() ? ratings.Average() : null;
    }

    private Dictionary<string, int> CalculateRatingDistribution(List<Core.Entities.ResponseAnswer> answers)
    {
        return answers
            .Where(a => !string.IsNullOrEmpty(a.AnswerText))
            .GroupBy(a => a.AnswerText!)
            .ToDictionary(g => $"{g.Key} stars", g => g.Count());
    }

    private Dictionary<string, int> CalculateYesNoDistribution(List<Core.Entities.ResponseAnswer> answers)
    {
        return answers
            .Where(a => !string.IsNullOrEmpty(a.AnswerText))
            .GroupBy(a => a.AnswerText!)
            .ToDictionary(g => g.Key, g => g.Count());
    }

    private double CalculateSurveyCompletionRate(int surveyId, List<Core.Entities.Response> allResponses)
    {
        var surveyResponses = allResponses.Where(r => r.SurveyId == surveyId).ToList();
        if (!surveyResponses.Any()) return 0;

        return (double)surveyResponses.Count(r => r.IsComplete) / surveyResponses.Count * 100;
    }

    private string ExtractClientName(Core.Entities.Response? response)
    {
        if (response?.ClientData == null) return "Unknown";

        try
        {
            var clientData = JsonSerializer.Deserialize<Dictionary<string, object>>(response.ClientData);
            return clientData?.GetValueOrDefault("ClientName")?.ToString() ?? "Unknown";
        }
        catch
        {
            return "Unknown";
        }
    }

    private byte[] ExportToCsv(SurveyStatisticsDto statistics)
    {
        var csv = new StringBuilder();
        csv.AppendLine($"Survey Statistics Report");
        csv.AppendLine($"Survey: {statistics.SurveyTitle}");
        csv.AppendLine($"Generated: {DateTime.UtcNow:yyyy-MM-dd HH:mm:ss} UTC");
        csv.AppendLine();
        csv.AppendLine($"Total Responses,{statistics.TotalResponses}");
        csv.AppendLine($"Complete Responses,{statistics.CompleteResponses}");
        csv.AppendLine($"Completion Rate,{statistics.CompletionRate:F2}%");
        csv.AppendLine();
        csv.AppendLine("Question Analytics");
        csv.AppendLine("Question,Type,Total Answers,Details");

        foreach (var qa in statistics.QuestionAnalytics)
        {
            var details = qa.QuestionType switch
            {
                QuestionType.Rating => $"Average: {qa.AverageRating:F2}",
                QuestionType.YesNo => $"Yes: {qa.YesCount}, No: {qa.NoCount}",
                QuestionType.Text => $"{qa.TextResponses.Count} text responses",
                _ => string.Join("; ", qa.OptionDistribution.Select(kvp => $"{kvp.Key}: {kvp.Value}"))
            };

            csv.AppendLine($"\"{qa.QuestionText}\",{qa.QuestionType},{qa.TotalAnswers},\"{details}\"");
        }

        return Encoding.UTF8.GetBytes(csv.ToString());
    }

    private byte[] ExportToJson(SurveyStatisticsDto statistics)
    {
        var json = JsonSerializer.Serialize(statistics, new JsonSerializerOptions
        {
            WriteIndented = true
        });
        return Encoding.UTF8.GetBytes(json);
    }
}
