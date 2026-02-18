using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using Survey.Core.Entities;

namespace Survey.Infrastructure.Data.Configurations;

public class QuestionCategoryConfiguration : IEntityTypeConfiguration<QuestionCategory>
{
    public void Configure(EntityTypeBuilder<QuestionCategory> builder)
    {
        builder.ToTable("QuestionCategories");

        builder.HasKey(c => c.Id);

        builder.Property(c => c.Name)
            .IsRequired()
            .HasMaxLength(200);

        builder.Property(c => c.Description)
            .HasColumnType("TEXT");

        builder.Property(c => c.CreatedAt)
            .IsRequired();

        // Self-referencing relationship
        builder.HasOne(c => c.ParentCategory)
            .WithMany(c => c.SubCategories)
            .HasForeignKey(c => c.ParentCategoryId)
            .OnDelete(DeleteBehavior.SetNull);

        builder.HasMany(c => c.Questions)
            .WithOne(q => q.Category)
            .HasForeignKey(q => q.CategoryId)
            .OnDelete(DeleteBehavior.SetNull);
    }
}
