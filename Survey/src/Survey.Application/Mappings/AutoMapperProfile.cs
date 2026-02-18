using System.Text.Json;
using AutoMapper;
using Survey.Core.DTOs.QuestionBank;
using Survey.Core.DTOs.SurveyBuilder;
using Survey.Core.DTOs.FieldMapping;
using Survey.Core.DTOs.SurveyExecution;
using Survey.Core.DTOs.User;
using Survey.Core.Entities;

namespace Survey.Application.Mappings;

public class AutoMapperProfile : Profile
{
    public AutoMapperProfile()
    {
        // Question Bank mappings
        CreateMap<QuestionBank, QuestionBankDto>()
            .ForMember(dest => dest.CategoryName,
                opt => opt.MapFrom(src => src.Category != null ? src.Category.Name : null))
            .ForMember(dest => dest.Options,
                opt => opt.MapFrom(src => src.Options.OrderBy(o => o.OrderIndex)));

        CreateMap<QuestionBankOption, QuestionBankOptionDto>();

        CreateMap<CreateQuestionBankDto, QuestionBank>()
            .ForMember(dest => dest.Options,
                opt => opt.MapFrom(src => src.Options));

        CreateMap<CreateQuestionBankOptionDto, QuestionBankOption>();

        CreateMap<UpdateQuestionBankDto, QuestionBank>()
            .ForMember(dest => dest.Options,
                opt => opt.MapFrom(src => src.Options));

        // Question Category mappings
        CreateMap<QuestionCategory, QuestionCategoryDto>()
            .ForMember(dest => dest.ParentCategoryName,
                opt => opt.MapFrom(src => src.ParentCategory != null ? src.ParentCategory.Name : null))
            .ForMember(dest => dest.QuestionCount,
                opt => opt.MapFrom(src => src.Questions.Count))
            .ForMember(dest => dest.SubCategories,
                opt => opt.MapFrom(src => src.SubCategories));

        CreateMap<CreateQuestionCategoryDto, QuestionCategory>();

        CreateMap<UpdateQuestionCategoryDto, QuestionCategory>();

        // Survey mappings
        CreateMap<Core.Entities.Survey, SurveyDto>()
            .ForMember(dest => dest.QuestionCount,
                opt => opt.MapFrom(src => src.Questions.Count))
            .ForMember(dest => dest.Questions,
                opt => opt.MapFrom(src => src.Questions.OrderBy(q => q.OrderIndex)));

        CreateMap<CreateSurveyDto, Core.Entities.Survey>();

        CreateMap<UpdateSurveyDto, Core.Entities.Survey>();

        // Survey Question mappings
        CreateMap<SurveyQuestion, SurveyQuestionDto>()
            .ForMember(dest => dest.QuestionText,
                opt => opt.MapFrom(src => !string.IsNullOrEmpty(src.QuestionText)
                    ? src.QuestionText
                    : src.QuestionBank.QuestionText))
            .ForMember(dest => dest.Options,
                opt => opt.MapFrom(src => src.Options.OrderBy(o => o.OrderIndex)));

        CreateMap<SurveyQuestionOption, SurveyQuestionOptionDto>();

        // Field Mapping mappings
        CreateMap<FieldMapping, FieldMappingDto>();
        CreateMap<CreateFieldMappingDto, FieldMapping>();
        CreateMap<UpdateFieldMappingDto, FieldMapping>();

        // Survey Execution mappings
        CreateMap<Response, ResponseDto>()
            .ForMember(dest => dest.ClientData,
                opt => opt.MapFrom(src => DeserializeClientData(src.ClientData)));

        CreateMap<ResponseAnswer, ResponseAnswerDto>();

        // User mappings
        CreateMap<User, UserDto>()
            .ForMember(dest => dest.Role,
                opt => opt.MapFrom(src => src.Role.ToString()));

        CreateMap<CreateUserDto, User>();
    }

    private static Dictionary<string, string>? DeserializeClientData(string? clientData)
    {
        if (string.IsNullOrEmpty(clientData))
            return null;

        try
        {
            return JsonSerializer.Deserialize<Dictionary<string, string>>(clientData);
        }
        catch
        {
            return null;
        }
    }
}
