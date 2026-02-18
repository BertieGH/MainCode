using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using Survey.Core.Entities;

namespace Survey.Infrastructure.Data.Configurations;

public class QuestionBankConfiguration : IEntityTypeConfiguration<QuestionBank>
{
    public void Configure(EntityTypeBuilder<QuestionBank> builder)
    {
        builder.ToTable("QuestionBank");

        builder.HasKey(q => q.Id);

        builder.Property(q => q.QuestionText)
            .IsRequired()
            .HasColumnType("TEXT");

        builder.Property(q => q.QuestionType)
            .IsRequired()
            .HasMaxLength(50);

        builder.Property(q => q.Version)
            .IsRequired()
            .HasDefaultValue(1);

        builder.Property(q => q.IsActive)
            .IsRequired()
            .HasDefaultValue(true);

        builder.Property(q => q.Tags)
            .HasMaxLength(500);

        builder.Property(q => q.CreatedBy)
            .HasMaxLength(100);

        builder.HasMany(q => q.Options)
            .WithOne(o => o.QuestionBank)
            .HasForeignKey(o => o.QuestionBankId)
            .OnDelete(DeleteBehavior.Cascade);
    }
}
