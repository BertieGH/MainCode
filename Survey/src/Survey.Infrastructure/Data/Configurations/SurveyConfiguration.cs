using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using Survey.Core.Enums;

namespace Survey.Infrastructure.Data.Configurations;

public class SurveyConfiguration : IEntityTypeConfiguration<Core.Entities.Survey>
{
    public void Configure(EntityTypeBuilder<Core.Entities.Survey> builder)
    {
        builder.ToTable("Surveys");

        builder.HasKey(s => s.Id);

        builder.Property(s => s.Title)
            .IsRequired()
            .HasMaxLength(300);

        builder.Property(s => s.Description)
            .HasColumnType("TEXT");

        builder.Property(s => s.Status)
            .IsRequired()
            .HasConversion<string>()
            .HasMaxLength(50)
            .HasDefaultValue(SurveyStatus.Draft);

        builder.Property(s => s.CreatedBy)
            .HasMaxLength(100);

        builder.HasMany(s => s.Questions)
            .WithOne(q => q.Survey)
            .HasForeignKey(q => q.SurveyId)
            .OnDelete(DeleteBehavior.Cascade);

        builder.HasMany(s => s.Responses)
            .WithOne(r => r.Survey)
            .HasForeignKey(r => r.SurveyId)
            .OnDelete(DeleteBehavior.Restrict);
    }
}
