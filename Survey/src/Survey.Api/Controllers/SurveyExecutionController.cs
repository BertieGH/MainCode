using Microsoft.AspNetCore.Mvc;
using Survey.Application.Services;
using Survey.Core.DTOs.SurveyExecution;

namespace Survey.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class SurveyExecutionController : ControllerBase
{
    private readonly ISurveyExecutionService _surveyExecutionService;
    private readonly ILogger<SurveyExecutionController> _logger;

    public SurveyExecutionController(
        ISurveyExecutionService surveyExecutionService,
        ILogger<SurveyExecutionController> logger)
    {
        _surveyExecutionService = surveyExecutionService;
        _logger = logger;
    }

    /// <summary>
    /// Get survey for client execution with auto-filled client data
    /// </summary>
    /// <param name="surveyId">Survey ID</param>
    /// <param name="crmClientId">CRM Client ID</param>
    /// <param name="clientData">Client data from CRM</param>
    /// <returns>Survey with questions and mapped client data</returns>
    [HttpPost("{surveyId}/prepare")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<ActionResult<SurveyExecutionDto>> GetSurveyForClient(
        int surveyId,
        [FromQuery] string crmClientId,
        [FromBody] Dictionary<string, string> clientData)
    {
        _logger.LogInformation("Getting survey {SurveyId} for client {CrmClientId}", surveyId, crmClientId);
        var survey = await _surveyExecutionService.GetSurveyForClientAsync(surveyId, crmClientId, clientData);
        return Ok(survey);
    }

    /// <summary>
    /// Start a new survey response
    /// </summary>
    /// <param name="dto">Survey start data with client information</param>
    /// <returns>Created response with ID</returns>
    [HttpPost("start")]
    [ProducesResponseType(StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<ActionResult<ResponseDto>> StartSurvey(StartSurveyDto dto)
    {
        _logger.LogInformation("Starting survey {SurveyId} for client {CrmClientId}",
            dto.SurveyId, dto.CrmClientId);

        var response = await _surveyExecutionService.StartSurveyResponseAsync(dto);
        return CreatedAtAction(nameof(GetResponse), new { id = response.Id }, response);
    }

    /// <summary>
    /// Submit answers for a response
    /// </summary>
    /// <param name="dto">Response answers</param>
    /// <returns>No content</returns>
    [HttpPost("submit-answers")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> SubmitAnswers(SubmitResponseDto dto)
    {
        _logger.LogInformation("Submitting answers for response {ResponseId}", dto.ResponseId);
        await _surveyExecutionService.SubmitAnswersAsync(dto);
        return NoContent();
    }

    /// <summary>
    /// Complete a survey response
    /// </summary>
    /// <param name="responseId">Response ID</param>
    /// <returns>Completed response</returns>
    [HttpPost("responses/{responseId}/complete")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<ActionResult<ResponseDto>> CompleteSurvey(int responseId)
    {
        _logger.LogInformation("Completing survey response {ResponseId}", responseId);
        var response = await _surveyExecutionService.CompleteSurveyAsync(responseId);
        return Ok(response);
    }

    /// <summary>
    /// Get response by ID
    /// </summary>
    /// <param name="id">Response ID</param>
    /// <returns>Response details</returns>
    [HttpGet("responses/{id}")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<ResponseDto>> GetResponse(int id)
    {
        _logger.LogInformation("Getting response {Id}", id);
        var response = await _surveyExecutionService.GetResponseAsync(id);
        return Ok(response);
    }
}
