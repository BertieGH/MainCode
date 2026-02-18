using AutoMapper;
using Survey.Core.DTOs.FieldMapping;
using Survey.Core.Entities;
using Survey.Core.Exceptions;
using Survey.Core.Interfaces;

namespace Survey.Application.Services;

public class FieldMappingService : IFieldMappingService
{
    private readonly IFieldMappingRepository _fieldMappingRepository;
    private readonly IUnitOfWork _unitOfWork;
    private readonly IMapper _mapper;

    public FieldMappingService(
        IFieldMappingRepository fieldMappingRepository,
        IUnitOfWork unitOfWork,
        IMapper mapper)
    {
        _fieldMappingRepository = fieldMappingRepository;
        _unitOfWork = unitOfWork;
        _mapper = mapper;
    }

    public async Task<IEnumerable<FieldMappingDto>> GetAllMappingsAsync()
    {
        var mappings = await _fieldMappingRepository.GetAllMappingsAsync();
        return _mapper.Map<IEnumerable<FieldMappingDto>>(mappings);
    }

    public async Task<FieldMappingDto?> GetMappingByIdAsync(int id)
    {
        var mapping = await _fieldMappingRepository.GetMappingByIdAsync(id);
        if (mapping == null)
            throw new NotFoundException(nameof(FieldMapping), id);

        return _mapper.Map<FieldMappingDto>(mapping);
    }

    public async Task<FieldMappingDto> CreateMappingAsync(CreateFieldMappingDto dto)
    {
        var mapping = _mapper.Map<FieldMapping>(dto);
        mapping.CreatedAt = DateTime.UtcNow;
        mapping.UpdatedAt = DateTime.UtcNow;

        await _fieldMappingRepository.AddAsync(mapping);
        await _unitOfWork.SaveChangesAsync();

        return _mapper.Map<FieldMappingDto>(mapping);
    }

    public async Task<FieldMappingDto> UpdateMappingAsync(int id, UpdateFieldMappingDto dto)
    {
        var mapping = await _fieldMappingRepository.GetByIdAsync(id);
        if (mapping == null)
            throw new NotFoundException(nameof(FieldMapping), id);

        mapping.CrmFieldName = dto.CrmFieldName;
        mapping.SurveyFieldName = dto.SurveyFieldName;
        mapping.FieldType = dto.FieldType;
        mapping.IsRequired = dto.IsRequired;
        mapping.UpdatedAt = DateTime.UtcNow;

        await _fieldMappingRepository.UpdateAsync(mapping);
        await _unitOfWork.SaveChangesAsync();

        return _mapper.Map<FieldMappingDto>(mapping);
    }

    public async Task DeleteMappingAsync(int id)
    {
        var mapping = await _fieldMappingRepository.GetByIdAsync(id);
        if (mapping == null)
            throw new NotFoundException(nameof(FieldMapping), id);

        await _fieldMappingRepository.DeleteAsync(mapping);
        await _unitOfWork.SaveChangesAsync();
    }

    public async Task<TestMappingResultDto> TestMappingsAsync(TestMappingDto dto)
    {
        var result = new TestMappingResultDto
        {
            MappedData = new Dictionary<string, string>(),
            Errors = new List<string>(),
            IsValid = true
        };

        var mappings = await _fieldMappingRepository.GetAllMappingsAsync();

        foreach (var mapping in mappings)
        {
            if (dto.SampleData.ContainsKey(mapping.CrmFieldName))
            {
                var value = dto.SampleData[mapping.CrmFieldName];

                // Validate field type
                if (!ValidateFieldType(value, mapping.FieldType))
                {
                    result.Errors.Add($"Field '{mapping.CrmFieldName}' has invalid type. Expected: {mapping.FieldType}");
                    result.IsValid = false;
                    continue;
                }

                result.MappedData[mapping.SurveyFieldName] = value;
            }
            else if (mapping.IsRequired)
            {
                result.Errors.Add($"Required field '{mapping.CrmFieldName}' is missing");
                result.IsValid = false;
            }
        }

        return result;
    }

    public async Task<Dictionary<string, string>> ApplyMappingsAsync(Dictionary<string, string> crmData)
    {
        var mappedData = new Dictionary<string, string>();
        var mappings = await _fieldMappingRepository.GetAllMappingsAsync();

        foreach (var mapping in mappings)
        {
            if (crmData.ContainsKey(mapping.CrmFieldName))
            {
                mappedData[mapping.SurveyFieldName] = crmData[mapping.CrmFieldName];
            }
            else if (mapping.IsRequired)
            {
                throw new BusinessRuleException($"Required field '{mapping.CrmFieldName}' is missing from CRM data");
            }
        }

        return mappedData;
    }

    private bool ValidateFieldType(string value, string fieldType)
    {
        return fieldType.ToLower() switch
        {
            "string" => true, // All values can be strings
            "number" => int.TryParse(value, out _) || double.TryParse(value, out _),
            "date" => DateTime.TryParse(value, out _),
            "email" => value.Contains("@") && value.Contains("."),
            "phone" => value.Length >= 10 && value.All(c => char.IsDigit(c) || c == '-' || c == '(' || c == ')' || c == ' ' || c == '+'),
            _ => true
        };
    }
}
