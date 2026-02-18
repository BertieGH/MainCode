using FluentValidation;
using Survey.Core.DTOs.QuestionBank;
using Survey.Core.Enums;

namespace Survey.Application.Validators;

public class CreateQuestionBankDtoValidator : AbstractValidator<CreateQuestionBankDto>
{
    public CreateQuestionBankDtoValidator()
    {
        RuleFor(x => x.QuestionText)
            .NotEmpty().WithMessage("Question text is required")
            .MaximumLength(1000).WithMessage("Question text cannot exceed 1000 characters");

        RuleFor(x => x.QuestionType)
            .IsInEnum().WithMessage("Invalid question type");

        RuleFor(x => x.Tags)
            .MaximumLength(500).WithMessage("Tags cannot exceed 500 characters");

        RuleFor(x => x.Options)
            .Must(HaveOptionsForChoiceQuestions)
            .WithMessage("Choice questions must have at least 2 options");
    }

    private bool HaveOptionsForChoiceQuestions(CreateQuestionBankDto dto, List<CreateQuestionBankOptionDto> options)
    {
        if (dto.QuestionType == QuestionType.SingleChoice || dto.QuestionType == QuestionType.MultipleChoice)
        {
            return options != null && options.Count >= 2;
        }
        return true;
    }
}
