using Microsoft.AspNetCore.Mvc;
using Survey.Application.Services;

namespace Survey.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class AnalyticsController : ControllerBase
{
    private readonly IAnalyticsService _analyticsService;
    private readonly ILogger<AnalyticsController> _logger;

    public AnalyticsController(
        IAnalyticsService analyticsService,
        ILogger<AnalyticsController> logger)
    {
        _analyticsService = analyticsService;
        _logger = logger;
    }

    /// <summary>
    /// Get comprehensive statistics for a survey including question analytics
    /// </summary>
    /// <param name="surveyId">Survey ID</param>
    /// <returns>Survey statistics with question-level analytics</returns>
    [HttpGet("survey/{surveyId}")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> GetSurveyStatistics(int surveyId)
    {
        _logger.LogInformation("Getting statistics for survey {SurveyId}", surveyId);
        var statistics = await _analyticsService.GetSurveyStatisticsAsync(surveyId);
        return Ok(statistics);
    }

    /// <summary>
    /// Get survey history for a CRM client
    /// </summary>
    /// <param name="crmClientId">CRM Client ID</param>
    /// <returns>Client's survey history</returns>
    [HttpGet("client/{crmClientId}")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    public async Task<IActionResult> GetClientSurveyHistory(string crmClientId)
    {
        _logger.LogInformation("Getting survey history for client {CrmClientId}", crmClientId);
        var history = await _analyticsService.GetClientSurveyHistoryAsync(crmClientId);
        return Ok(history);
    }

    /// <summary>
    /// Get overall dashboard summary
    /// </summary>
    /// <returns>Dashboard with overall statistics</returns>
    [HttpGet("dashboard")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    public async Task<IActionResult> GetDashboardSummary()
    {
        _logger.LogInformation("Getting dashboard summary");
        var dashboard = await _analyticsService.GetDashboardSummaryAsync();
        return Ok(dashboard);
    }

    /// <summary>
    /// Get all responses for a survey with client IDs
    /// </summary>
    [HttpGet("survey/{surveyId}/responses")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> GetSurveyResponses(int surveyId)
    {
        _logger.LogInformation("Getting responses for survey {SurveyId}", surveyId);
        var responses = await _analyticsService.GetSurveyResponsesAsync(surveyId);
        return Ok(responses);
    }

    /// <summary>
    /// Get a single response with full answer details
    /// </summary>
    [HttpGet("response/{responseId}")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> GetResponseDetail(int responseId)
    {
        _logger.LogInformation("Getting response detail {ResponseId}", responseId);
        var detail = await _analyticsService.GetResponseDetailAsync(responseId);
        return Ok(detail);
    }

    /// <summary>
    /// Export survey results to CSV or JSON format
    /// </summary>
    /// <param name="surveyId">Survey ID</param>
    /// <param name="format">Export format (csv or json)</param>
    /// <returns>File download with survey results</returns>
    [HttpGet("export/survey/{surveyId}")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> ExportSurveyResults(int surveyId, [FromQuery] string format = "csv")
    {
        _logger.LogInformation("Exporting survey {SurveyId} results as {Format}", surveyId, format);

        var fileBytes = await _analyticsService.ExportSurveyResultsAsync(surveyId, format);

        var contentType = format.ToLower() switch
        {
            "csv" => "text/csv",
            "json" => "application/json",
            _ => "application/octet-stream"
        };

        var fileName = $"survey_{surveyId}_results_{DateTime.UtcNow:yyyyMMddHHmmss}.{format.ToLower()}";

        return File(fileBytes, contentType, fileName);
    }
}
