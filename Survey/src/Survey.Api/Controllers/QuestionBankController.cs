using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Survey.Application.Services;
using Survey.Core.DTOs.QuestionBank;

namespace Survey.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
[Authorize]
public class QuestionBankController : ControllerBase
{
    private readonly IQuestionBankService _questionBankService;

    public QuestionBankController(IQuestionBankService questionBankService)
    {
        _questionBankService = questionBankService;
    }

    /// <summary>
    /// Get all question templates with pagination and filtering
    /// </summary>
    [HttpGet]
    public async Task<IActionResult> GetAll(
        [FromQuery] int pageNumber = 1,
        [FromQuery] int pageSize = 20,
        [FromQuery] int? categoryId = null,
        [FromQuery] string? search = null)
    {
        var result = await _questionBankService.GetAllQuestionsAsync(
            pageNumber, pageSize, categoryId, search);

        return Ok(result);
    }

    /// <summary>
    /// Get question template by ID with options
    /// </summary>
    [HttpGet("{id}")]
    public async Task<IActionResult> GetById(int id)
    {
        var question = await _questionBankService.GetQuestionByIdAsync(id);

        if (question == null)
            return NotFound(new { message = $"Question with ID {id} not found" });

        return Ok(question);
    }

    /// <summary>
    /// Create new question template
    /// </summary>
    [HttpPost]
    [Authorize(Roles = "Admin,Manager")]
    public async Task<IActionResult> Create([FromBody] CreateQuestionBankDto dto)
    {
        dto.CreatedBy = User.Identity?.Name;
        var question = await _questionBankService.CreateQuestionAsync(dto);
        return CreatedAtAction(nameof(GetById), new { id = question.Id }, question);
    }

    /// <summary>
    /// Update question template (creates new version)
    /// </summary>
    [HttpPut("{id}")]
    [Authorize(Roles = "Admin,Manager")]
    public async Task<IActionResult> Update(int id, [FromBody] UpdateQuestionBankDto dto)
    {
        var question = await _questionBankService.UpdateQuestionAsync(id, dto);
        return Ok(question);
    }

    /// <summary>
    /// Soft delete question template (sets IsActive = false)
    /// </summary>
    [HttpDelete("{id}")]
    [Authorize(Roles = "Admin,Manager")]
    public async Task<IActionResult> Delete(int id)
    {
        await _questionBankService.DeleteQuestionAsync(id);
        return NoContent();
    }

    /// <summary>
    /// Search questions by text or tags
    /// </summary>
    [HttpGet("search")]
    public async Task<IActionResult> Search([FromQuery] string query)
    {
        var questions = await _questionBankService.SearchQuestionsAsync(query);
        return Ok(questions);
    }

    /// <summary>
    /// Get all versions of a question
    /// </summary>
    [HttpGet("versions/{questionId}")]
    public async Task<IActionResult> GetVersions(int questionId)
    {
        var versions = await _questionBankService.GetQuestionVersionsAsync(questionId);
        return Ok(versions);
    }
}
