using Survey.Core.DTOs.FieldMapping;

namespace Survey.Application.Services;

public interface IFieldMappingService
{
    Task<IEnumerable<FieldMappingDto>> GetAllMappingsAsync();
    Task<FieldMappingDto?> GetMappingByIdAsync(int id);
    Task<FieldMappingDto> CreateMappingAsync(CreateFieldMappingDto dto);
    Task<FieldMappingDto> UpdateMappingAsync(int id, UpdateFieldMappingDto dto);
    Task DeleteMappingAsync(int id);
    Task<TestMappingResultDto> TestMappingsAsync(TestMappingDto dto);
    Task<Dictionary<string, string>> ApplyMappingsAsync(Dictionary<string, string> crmData);
}
