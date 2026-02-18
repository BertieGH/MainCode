using Microsoft.AspNetCore.Mvc;
using Survey.Application.Services;
using Survey.Core.DTOs.QuestionBank;

namespace Survey.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class QuestionCategoriesController : ControllerBase
{
    private readonly IQuestionCategoryService _categoryService;

    public QuestionCategoriesController(IQuestionCategoryService categoryService)
    {
        _categoryService = categoryService;
    }

    /// <summary>
    /// Get all categories (hierarchical)
    /// </summary>
    [HttpGet]
    public async Task<IActionResult> GetAll()
    {
        var categories = await _categoryService.GetAllCategoriesAsync();
        return Ok(categories);
    }

    /// <summary>
    /// Get category by ID with subcategories
    /// </summary>
    [HttpGet("{id}")]
    public async Task<IActionResult> GetById(int id)
    {
        var category = await _categoryService.GetCategoryByIdAsync(id);

        if (category == null)
            return NotFound(new { message = $"Category with ID {id} not found" });

        return Ok(category);
    }

    /// <summary>
    /// Create new question category
    /// </summary>
    [HttpPost]
    public async Task<IActionResult> Create([FromBody] CreateQuestionCategoryDto dto)
    {
        var category = await _categoryService.CreateCategoryAsync(dto);
        return CreatedAtAction(nameof(GetById), new { id = category.Id }, category);
    }

    /// <summary>
    /// Update question category
    /// </summary>
    [HttpPut("{id}")]
    public async Task<IActionResult> Update(int id, [FromBody] UpdateQuestionCategoryDto dto)
    {
        var category = await _categoryService.UpdateCategoryAsync(id, dto);
        return Ok(category);
    }

    /// <summary>
    /// Delete question category
    /// </summary>
    [HttpDelete("{id}")]
    public async Task<IActionResult> Delete(int id)
    {
        await _categoryService.DeleteCategoryAsync(id);
        return NoContent();
    }
}
