using Survey.Core.DTOs.Common;
using Survey.Core.DTOs.SurveyBuilder;
using Survey.Core.Enums;

namespace Survey.Application.Services;

public interface ISurveyService
{
    Task<PagedResult<SurveyDto>> GetAllSurveysAsync(int pageNumber, int pageSize);
    Task<SurveyDto?> GetSurveyByIdAsync(int id);
    Task<SurveyDto> CreateSurveyAsync(CreateSurveyDto dto);
    Task<SurveyDto> UpdateSurveyAsync(int id, UpdateSurveyDto dto);
    Task DeleteSurveyAsync(int id);
    Task<SurveyDto> UpdateSurveyStatusAsync(int id, SurveyStatus status);
    Task<SurveyDto> DuplicateSurveyAsync(int id, string newTitle);
}
