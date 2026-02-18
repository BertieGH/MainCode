using Microsoft.AspNetCore.Mvc;
using Survey.Application.Services;
using Survey.Core.DTOs.FieldMapping;

namespace Survey.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
public class FieldMappingsController : ControllerBase
{
    private readonly IFieldMappingService _fieldMappingService;
    private readonly ILogger<FieldMappingsController> _logger;

    public FieldMappingsController(
        IFieldMappingService fieldMappingService,
        ILogger<FieldMappingsController> logger)
    {
        _fieldMappingService = fieldMappingService;
        _logger = logger;
    }

    /// <summary>
    /// Get all field mappings
    /// </summary>
    /// <returns>List of field mappings</returns>
    [HttpGet]
    [ProducesResponseType(StatusCodes.Status200OK)]
    public async Task<ActionResult<IEnumerable<FieldMappingDto>>> GetAllMappings()
    {
        _logger.LogInformation("Getting all field mappings");
        var mappings = await _fieldMappingService.GetAllMappingsAsync();
        return Ok(mappings);
    }

    /// <summary>
    /// Get field mapping by ID
    /// </summary>
    /// <param name="id">Field mapping ID</param>
    /// <returns>Field mapping details</returns>
    [HttpGet("{id}")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<FieldMappingDto>> GetMappingById(int id)
    {
        _logger.LogInformation("Getting field mapping {Id}", id);
        var mapping = await _fieldMappingService.GetMappingByIdAsync(id);
        return Ok(mapping);
    }

    /// <summary>
    /// Create a new field mapping
    /// </summary>
    /// <param name="dto">Field mapping data</param>
    /// <returns>Created field mapping</returns>
    [HttpPost]
    [ProducesResponseType(StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<ActionResult<FieldMappingDto>> CreateMapping(CreateFieldMappingDto dto)
    {
        _logger.LogInformation("Creating field mapping: {CrmField} -> {SurveyField}",
            dto.CrmFieldName, dto.SurveyFieldName);

        var mapping = await _fieldMappingService.CreateMappingAsync(dto);
        return CreatedAtAction(nameof(GetMappingById), new { id = mapping.Id }, mapping);
    }

    /// <summary>
    /// Update an existing field mapping
    /// </summary>
    /// <param name="id">Field mapping ID</param>
    /// <param name="dto">Updated field mapping data</param>
    /// <returns>Updated field mapping</returns>
    [HttpPut("{id}")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<ActionResult<FieldMappingDto>> UpdateMapping(int id, UpdateFieldMappingDto dto)
    {
        _logger.LogInformation("Updating field mapping {Id}", id);
        var mapping = await _fieldMappingService.UpdateMappingAsync(id, dto);
        return Ok(mapping);
    }

    /// <summary>
    /// Delete a field mapping
    /// </summary>
    /// <param name="id">Field mapping ID</param>
    /// <returns>No content</returns>
    [HttpDelete("{id}")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> DeleteMapping(int id)
    {
        _logger.LogInformation("Deleting field mapping {Id}", id);
        await _fieldMappingService.DeleteMappingAsync(id);
        return NoContent();
    }

    /// <summary>
    /// Test field mappings with sample data
    /// </summary>
    /// <param name="dto">Sample CRM data</param>
    /// <returns>Test result with mapped data and validation errors</returns>
    [HttpPost("test")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    public async Task<ActionResult<TestMappingResultDto>> TestMappings(TestMappingDto dto)
    {
        _logger.LogInformation("Testing field mappings with sample data");
        var result = await _fieldMappingService.TestMappingsAsync(dto);
        return Ok(result);
    }
}
