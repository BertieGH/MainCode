using FluentValidation;
using Survey.Core.DTOs.SurveyBuilder;

namespace Survey.Application.Validators;

public class CreateSurveyDtoValidator : AbstractValidator<CreateSurveyDto>
{
    public CreateSurveyDtoValidator()
    {
        RuleFor(x => x.Title)
            .NotEmpty().WithMessage("Survey title is required")
            .MaximumLength(300).WithMessage("Survey title cannot exceed 300 characters");

        RuleFor(x => x.Description)
            .MaximumLength(2000).WithMessage("Description cannot exceed 2000 characters");
    }
}
