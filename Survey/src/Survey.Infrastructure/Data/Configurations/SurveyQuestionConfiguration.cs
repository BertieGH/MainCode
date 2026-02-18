using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using Survey.Core.Entities;

namespace Survey.Infrastructure.Data.Configurations;

public class SurveyQuestionConfiguration : IEntityTypeConfiguration<SurveyQuestion>
{
    public void Configure(EntityTypeBuilder<SurveyQuestion> builder)
    {
        builder.ToTable("SurveyQuestions");

        builder.HasKey(sq => sq.Id);

        builder.Property(sq => sq.QuestionText)
            .HasColumnType("TEXT");

        builder.Property(sq => sq.QuestionType)
            .IsRequired()
            .HasMaxLength(50);

        builder.Property(sq => sq.IsRequired)
            .HasDefaultValue(false);

        builder.Property(sq => sq.OrderIndex)
            .HasDefaultValue(0);

        builder.Property(sq => sq.IsModified)
            .HasDefaultValue(false);

        builder.HasOne(sq => sq.QuestionBank)
            .WithMany(qb => qb.SurveyQuestions)
            .HasForeignKey(sq => sq.QuestionBankId)
            .OnDelete(DeleteBehavior.Restrict);

        builder.HasMany(sq => sq.Options)
            .WithOne(o => o.SurveyQuestion)
            .HasForeignKey(o => o.SurveyQuestionId)
            .OnDelete(DeleteBehavior.Cascade);
    }
}
