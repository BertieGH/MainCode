using FluentValidation;
using Survey.Core.DTOs.User;
using Survey.Core.Enums;

namespace Survey.Application.Validators;

public class UpdateUserDtoValidator : AbstractValidator<UpdateUserDto>
{
    public UpdateUserDtoValidator()
    {
        RuleFor(x => x.Username)
            .NotEmpty().WithMessage("Username is required")
            .MinimumLength(3).WithMessage("Username must be at least 3 characters")
            .MaximumLength(100).WithMessage("Username cannot exceed 100 characters")
            .Matches(@"^[a-zA-Z0-9_]+$").WithMessage("Username can only contain letters, numbers, and underscores");

        RuleFor(x => x.Email)
            .NotEmpty().WithMessage("Email is required")
            .EmailAddress().WithMessage("Invalid email format")
            .MaximumLength(200).WithMessage("Email cannot exceed 200 characters");

        RuleFor(x => x.Role)
            .Must(role => string.IsNullOrEmpty(role) || Enum.TryParse<UserRole>(role, out _))
            .WithMessage("Invalid role. Must be Admin, Manager, or User");
    }
}
