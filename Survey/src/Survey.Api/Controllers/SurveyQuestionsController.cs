using Microsoft.AspNetCore.Mvc;
using Survey.Application.Services;
using Survey.Core.DTOs.SurveyBuilder;

namespace Survey.Api.Controllers;

[ApiController]
[Route("api/surveys/{surveyId}/[controller]")]
public class SurveyQuestionsController : ControllerBase
{
    private readonly ISurveyBuilderService _surveyBuilderService;

    public SurveyQuestionsController(ISurveyBuilderService surveyBuilderService)
    {
        _surveyBuilderService = surveyBuilderService;
    }

    /// <summary>
    /// Get all questions in a survey
    /// </summary>
    [HttpGet]
    public async Task<IActionResult> GetAll(int surveyId)
    {
        var questions = await _surveyBuilderService.GetSurveyQuestionsAsync(surveyId);
        return Ok(questions);
    }

    /// <summary>
    /// Add question from Question Bank to survey
    /// </summary>
    [HttpPost]
    public async Task<IActionResult> AddQuestion(int surveyId, [FromBody] AddQuestionToSurveyDto dto)
    {
        var question = await _surveyBuilderService.AddQuestionToSurveyAsync(surveyId, dto);
        return Ok(question);
    }

    /// <summary>
    /// Modify question in survey (customize text or options)
    /// </summary>
    [HttpPut("{questionId}")]
    public async Task<IActionResult> ModifyQuestion(
        int surveyId,
        int questionId,
        [FromBody] ModifySurveyQuestionDto dto)
    {
        var question = await _surveyBuilderService.ModifyQuestionInSurveyAsync(surveyId, questionId, dto);
        return Ok(question);
    }

    /// <summary>
    /// Remove question from survey
    /// </summary>
    [HttpDelete("{questionId}")]
    public async Task<IActionResult> RemoveQuestion(int surveyId, int questionId)
    {
        await _surveyBuilderService.RemoveQuestionFromSurveyAsync(surveyId, questionId);
        return NoContent();
    }

    /// <summary>
    /// Reorder questions in survey
    /// </summary>
    [HttpPatch("reorder")]
    public async Task<IActionResult> ReorderQuestions(int surveyId, [FromBody] ReorderQuestionsDto dto)
    {
        var questions = await _surveyBuilderService.ReorderQuestionsAsync(surveyId, dto);
        return Ok(questions);
    }
}
