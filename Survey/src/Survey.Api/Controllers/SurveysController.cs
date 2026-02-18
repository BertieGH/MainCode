using Microsoft.AspNetCore.Mvc;
using Survey.Application.Services;
using Survey.Core.DTOs.SurveyBuilder;
using Survey.Core.Enums;

namespace Survey.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class SurveysController : ControllerBase
{
    private readonly ISurveyService _surveyService;

    public SurveysController(ISurveyService surveyService)
    {
        _surveyService = surveyService;
    }

    /// <summary>
    /// Get all surveys with pagination
    /// </summary>
    [HttpGet]
    public async Task<IActionResult> GetAll(
        [FromQuery] int pageNumber = 1,
        [FromQuery] int pageSize = 20)
    {
        var result = await _surveyService.GetAllSurveysAsync(pageNumber, pageSize);
        return Ok(result);
    }

    /// <summary>
    /// Get survey by ID with all questions
    /// </summary>
    [HttpGet("{id}")]
    public async Task<IActionResult> GetById(int id)
    {
        var survey = await _surveyService.GetSurveyByIdAsync(id);

        if (survey == null)
            return NotFound(new { message = $"Survey with ID {id} not found" });

        return Ok(survey);
    }

    /// <summary>
    /// Create new survey
    /// </summary>
    [HttpPost]
    public async Task<IActionResult> Create([FromBody] CreateSurveyDto dto)
    {
        var survey = await _surveyService.CreateSurveyAsync(dto);
        return CreatedAtAction(nameof(GetById), new { id = survey.Id }, survey);
    }

    /// <summary>
    /// Update survey metadata (title, description)
    /// </summary>
    [HttpPut("{id}")]
    public async Task<IActionResult> Update(int id, [FromBody] UpdateSurveyDto dto)
    {
        var survey = await _surveyService.UpdateSurveyAsync(id, dto);
        return Ok(survey);
    }

    /// <summary>
    /// Delete survey
    /// </summary>
    [HttpDelete("{id}")]
    public async Task<IActionResult> Delete(int id)
    {
        await _surveyService.DeleteSurveyAsync(id);
        return NoContent();
    }

    /// <summary>
    /// Update survey status (Draft, Active, Paused, Archived)
    /// </summary>
    [HttpPatch("{id}/status")]
    public async Task<IActionResult> UpdateStatus(int id, [FromBody] UpdateSurveyStatusDto dto)
    {
        var survey = await _surveyService.UpdateSurveyStatusAsync(id, dto.Status);
        return Ok(survey);
    }

    /// <summary>
    /// Duplicate an existing survey
    /// </summary>
    [HttpPost("{id}/duplicate")]
    public async Task<IActionResult> Duplicate(int id, [FromBody] DuplicateSurveyDto dto)
    {
        var survey = await _surveyService.DuplicateSurveyAsync(id, dto.NewTitle);
        return CreatedAtAction(nameof(GetById), new { id = survey.Id }, survey);
    }
}

public class DuplicateSurveyDto
{
    public string NewTitle { get; set; } = string.Empty;
}
