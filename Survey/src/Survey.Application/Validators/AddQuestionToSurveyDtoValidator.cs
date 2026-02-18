using FluentValidation;
using Survey.Core.DTOs.SurveyBuilder;

namespace Survey.Application.Validators;

public class AddQuestionToSurveyDtoValidator : AbstractValidator<AddQuestionToSurveyDto>
{
    public AddQuestionToSurveyDtoValidator()
    {
        RuleFor(x => x.QuestionBankId)
            .GreaterThan(0).WithMessage("Valid Question Bank ID is required");

        RuleFor(x => x.OrderIndex)
            .GreaterThanOrEqualTo(0).When(x => x.OrderIndex.HasValue)
            .WithMessage("Order index must be non-negative");
    }
}
