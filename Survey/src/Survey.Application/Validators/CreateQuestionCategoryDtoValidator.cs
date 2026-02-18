using FluentValidation;
using Survey.Core.DTOs.QuestionBank;

namespace Survey.Application.Validators;

public class CreateQuestionCategoryDtoValidator : AbstractValidator<CreateQuestionCategoryDto>
{
    public CreateQuestionCategoryDtoValidator()
    {
        RuleFor(x => x.Name)
            .NotEmpty().WithMessage("Category name is required")
            .MaximumLength(200).WithMessage("Category name cannot exceed 200 characters");

        RuleFor(x => x.Description)
            .MaximumLength(1000).WithMessage("Description cannot exceed 1000 characters");
    }
}
